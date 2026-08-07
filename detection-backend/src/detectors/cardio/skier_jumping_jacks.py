"""
Skier Jumping Jacks rep counting + posture correction.

The movement
------------
Not a standard jumping jack: the legs stay together (a narrow hop/bounce
in place, not spreading wide), while **both arms swing together**, in
the same direction at the same time, from up-and-forward (near shoulder
height) down and back. What makes this a *different* exercise from a
regular jumping jack isn't the arms alone, it's the combination: synced
front-back arm swing + legs that mostly stay together. Leg spread is
tracked and graded into `rep_form_quality` rather than gating the count
— see "Legs stay together — graded, not gated" below for why an earlier,
stricter version of this got that wrong.

Two independent wrist trackers, required to sync
----------------------------------------------------
`swing_ratio` (per wrist) = (wrist.y - shoulder.y) / torso_length. Small
or negative when the arm is up near/above shoulder height, positive and
growing as the wrist swings down and back. Each wrist gets its own
hysteresis state machine (up/down), same convention as the limb-pair
trackers in the Cross Jacks analyzer — and exactly like Cross Jacks, a
rep only counts when **both** wrists independently confirm "down" within
`SYNC_WINDOW_SECONDS` of each other, then both confirm "up" within the
same window. This is deliberately tolerant of the two arms not being in
perfect lockstep, while still refusing to count a rep where only one arm
actually swung.

Legs stay together — graded, not gated
------------------------------------------
An earlier version treated "legs spread wide" as a hard, continuous
block: any frame where the ankles separated past a threshold froze all
arm-swing tracking, on the reasoning that wide-spread legs mean this has
become a regular jumping jack instead. That turned out to be the wrong
call to make a hard gate: landing from the hop naturally causes a brief
ankle separation for a frame or two even in a correctly-performed rep,
and freezing tracking at exactly that moment — right as the arms are
also at a swing extreme — was silently preventing reps from ever
completing. Combined with the swing-depth threshold being stricter than
how people actually perform the movement (see below), nothing was
counting at all. Leg spread is now tracked and folded into
`rep_form_quality` instead — a rep with wide legs still counts, just
tagged `needs_improvement`.

Swing depth
-------------
An earlier version required the wrist to drop a full torso-length below
the shoulder (down to hip level) before counting "down" — a deeper,
more extended swing than most people actually perform, especially at a
fast hop tempo. Genuine, correctly-executed reps were reaching only
partway down and never triggering "down" at all. The threshold now asks
for a clear, deliberate downward swing without demanding elite-level
extension all the way to the hip; a deeper swing still earns the
`good` quality tier, it's just no longer required to count as a rep.

Tuned for fast tempo
----------------------
Same reasoning as the Cross Jacks analyzer: at real tempo a full
up->down->up swing can complete in well under half a second, so the
thresholds and margins below are kept as tight as they can be while
still keeping "up" and "down" clearly separated — a wide dead zone or an
overly strict framing/visibility gate just makes it easier for a fast,
correct rep to fall between two sampled frames and never get recorded.

A rep is counted on the return to UP after a confirmed DOWN (same
"count on completing the full cycle back to start" convention used
throughout this codebase) — edge-triggered, one-shot per cycle, so it
can't double-count.
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_HIP,
    LEFT_SHOULDER,
    LEFT_WRIST,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_HIP,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)

# -------------------------------------------------------------------------
# Tunable constants
# -------------------------------------------------------------------------

# Loosened from a stricter default — fast swings blur the wrist
# landmarks momentarily; a strict floor drops tracking right when a fast
# rep needs the sample most (see the Cross Jacks analyzer for the same
# reasoning).
MIN_LANDMARK_VISIBILITY = 0.3

# ---- arm swing (wrist.y - shoulder.y, normalized by torso length) ----
# UP: wrist at/above shoulder height (ratio near/below 0).
# DOWN: wrist has swung down and back (ratio comfortably positive).
#
# An earlier version required the wrist to drop a FULL torso-length below
# the shoulder (ratio > 0.95, i.e. down to hip level) to register "down".
# That's a deeper, more extended swing than most people actually perform
# — plenty of genuine, correctly-executed reps only swing the wrist to
# roughly mid-torso before reversing, especially at a fast hop tempo —
# so real reps were never reaching "down" at all and nothing ever counted.
# Lowered to require a clear, deliberate downward swing without demanding
# elite-level extension all the way to the hip.
SWING_UP_BELOW = 0.3
SWING_DOWN_ABOVE = 0.55
SWING_UP_IDEAL_BELOW = 0.15  # arm genuinely reaches shoulder height or above
SWING_DOWN_IDEAL_ABOVE = (
    0.85  # a deep swing toward/past the hip — good-tier, not required to count
)

# ---- both-wrist sync window ----
SYNC_WINDOW_SECONDS = 0.8

# ---- legs-together (ankle-to-ankle / shoulder width) ----
# Graded as a form note now, not a hard gate — see the note on
# `_legs_too_wide_this_rep` below for why a hard gate here was the other
# main reason nothing was counting.
MAX_LEG_SPREAD_RATIO = 1.3

# ---- hip bounce (jump quality note only — doesn't gate the count) ----
MIN_BOUNCE_RATIO = 0.04

MISTAKE_PENALTY = {
    "shallow_swing": 12,
    "legs_too_wide": 20,
    "no_bounce": 8,
}

SCORE_HISTORY = 30

# ---- framing (front-facing, standing) ----
# Edge margin loosened slightly — a fast, full arm swing can legitimately
# bring a wrist close to the frame edge at the top of the motion, and
# that's often the exact sample the rep needs recorded.
FRAME_EDGE_MARGIN = 0.015
BBOX_TOO_CLOSE = 0.97
BBOX_TOO_FAR = 0.12


def _looks_like_a_person(landmarks) -> bool:
    core = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)
    visible = sum(
        1
        for i in core
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible >= 3


def _visible(points) -> bool:
    for p in points:
        if p is None:
            return False
        v = getattr(p, "visibility", None)
        if v is not None and v < MIN_LANDMARK_VISIBILITY:
            return False
    return True


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _framing_feedback(points) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — step back so your whole body, "
                "arms included, fits in the shot."
            )

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "You're too close to the camera — step back so your whole body fits in frame."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class _ArmSwingTracker:
    """One up/down hysteresis state machine for one wrist, relative to
    that side's shoulder/torso scale. Tracks the extreme value reached
    in each phase for depth/quality grading."""

    def __init__(self):
        self.stage: str = "up"  # "up" | "down"
        self.confirmed_down_time: Optional[float] = None
        self.confirmed_up_time: Optional[float] = None
        self.up_extreme = 1.0  # min ratio seen since entering "up" (lower = better)
        self.down_extreme = (
            0.0  # max ratio seen since entering "down" (higher = better)
        )

    def update(self, ratio: float, t: float) -> None:
        if self.stage == "up":
            self.up_extreme = min(self.up_extreme, ratio)
            if ratio > SWING_DOWN_ABOVE:
                self.stage = "down"
                self.down_extreme = ratio
                self.confirmed_down_time = t
        else:  # "down"
            self.down_extreme = max(self.down_extreme, ratio)
            if ratio < SWING_UP_BELOW:
                self.stage = "up"
                self.up_extreme = ratio
                self.confirmed_up_time = t


class SkierJumpingJacksAnalyzer:
    """Stateful Skier Jumping Jacks rep counter — both wrists tracked
    independently and required to sync, legs required to stay together
    throughout for a rep to count."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.left_arm = _ArmSwingTracker()
        self.right_arm = _ArmSwingTracker()

        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        self._awaiting_up_confirmation = False
        self._pending_flawed = False
        self._rep_hip_min: Optional[float] = None
        self._rep_hip_max: Optional[float] = None
        self._legs_too_wide_this_rep = False

        self.session_start_time: Optional[float] = None

    # ---------------------------------------------------------------
    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    @staticmethod
    def _synced(a: Optional[float], b: Optional[float]) -> bool:
        return a is not None and b is not None and abs(a - b) <= SYNC_WINDOW_SECONDS

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "framing_ok": True,
            "framing_message": None,
            "left_swing_ratio": None,
            "right_swing_ratio": None,
            "left_arm_stage": self.left_arm.stage,
            "right_arm_stage": self.right_arm.stage,
            "leg_spread_ratio": None,
            "legs_together": True,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_form_quality": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = (
                "No person detected — step into frame, facing the camera."
            )
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        required_ok = _visible(
            (l_shoulder, r_shoulder, l_wrist, r_wrist, l_hip, r_hip, l_ankle, r_ankle)
        )
        if not required_ok:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your full body clearly — make sure both arms and "
                "both feet are visible, facing the camera."
            )
            return response

        response["pose_detected"] = True

        shoulder_width = max(_dist(l_shoulder, r_shoulder), 1e-6)
        mid_shoulder_y = (l_shoulder.y + r_shoulder.y) / 2.0
        mid_hip_y = (l_hip.y + r_hip.y) / 2.0
        torso_length = max(abs(mid_hip_y - mid_shoulder_y), 1e-6)

        framing_message = _framing_feedback(
            (l_shoulder, r_shoulder, l_wrist, r_wrist, l_hip, r_hip, l_ankle, r_ankle)
        )
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        if framing_message is not None:
            response["feedback"] = framing_message
            return response

        left_swing_ratio = (l_wrist.y - mid_shoulder_y) / torso_length
        right_swing_ratio = (r_wrist.y - mid_shoulder_y) / torso_length
        leg_spread_ratio = _dist(l_ankle, r_ankle) / shoulder_width
        legs_together = leg_spread_ratio <= MAX_LEG_SPREAD_RATIO

        response["left_swing_ratio"] = round(left_swing_ratio, 2)
        response["right_swing_ratio"] = round(right_swing_ratio, 2)
        response["leg_spread_ratio"] = round(leg_spread_ratio, 2)
        response["legs_together"] = legs_together

        # Track jump-bounce range across the whole rep.
        if self._rep_hip_min is None or mid_hip_y < self._rep_hip_min:
            self._rep_hip_min = mid_hip_y
        if self._rep_hip_max is None or mid_hip_y > self._rep_hip_max:
            self._rep_hip_max = mid_hip_y

        feedback: Optional[str] = None

        if not legs_together:
            # Graded, not gated (see module docstring) — track it for the
            # quality tier, but never stop arm tracking from progressing.
            self._legs_too_wide_this_rep = True

        prev_left_down_time = self.left_arm.confirmed_down_time
        prev_right_down_time = self.right_arm.confirmed_down_time
        prev_left_up_time = self.left_arm.confirmed_up_time
        prev_right_up_time = self.right_arm.confirmed_up_time

        self.left_arm.update(left_swing_ratio, t)
        self.right_arm.update(right_swing_ratio, t)

        response["left_arm_stage"] = self.left_arm.stage
        response["right_arm_stage"] = self.right_arm.stage

        rep_completed = False
        quality: Optional[str] = None

        # ---- down confirmation: both wrists swung down within the sync window ----
        left_just_down = self.left_arm.confirmed_down_time != prev_left_down_time
        right_just_down = self.right_arm.confirmed_down_time != prev_right_down_time
        if (left_just_down or right_just_down) and self._synced(
            self.left_arm.confirmed_down_time, self.right_arm.confirmed_down_time
        ):
            self._awaiting_up_confirmation = True
            shallow = (
                self.left_arm.down_extreme < SWING_DOWN_IDEAL_ABOVE
                or self.right_arm.down_extreme < SWING_DOWN_IDEAL_ABOVE
            )
            self._pending_flawed = shallow
            feedback = "Swung back — now bring your arms forward."

        # ---- up confirmation: both wrists swung back up within the sync window ----
        left_just_up = self.left_arm.confirmed_up_time != prev_left_up_time
        right_just_up = self.right_arm.confirmed_up_time != prev_right_up_time
        if (
            self._awaiting_up_confirmation
            and (left_just_up or right_just_up)
            and self._synced(
                self.left_arm.confirmed_up_time, self.right_arm.confirmed_up_time
            )
        ):
            shallow_up = (
                self.left_arm.up_extreme > SWING_UP_IDEAL_BELOW
                or self.right_arm.up_extreme > SWING_UP_IDEAL_BELOW
            )

            bounce_ratio = 0.0
            if self._rep_hip_min is not None and self._rep_hip_max is not None:
                bounce_ratio = (self._rep_hip_max - self._rep_hip_min) / torso_length
            no_bounce = bounce_ratio < MIN_BOUNCE_RATIO

            flawed = (
                self._pending_flawed
                or shallow_up
                or no_bounce
                or self._legs_too_wide_this_rep
            )

            self.rep_count += 1
            if flawed:
                self.flawed_reps += 1
                quality = "needs_improvement"
                hint = (
                    "keep your feet together"
                    if self._legs_too_wide_this_rep
                    else "swing fully forward and back, and add a little hop"
                )
                feedback = f"Rep {self.rep_count} counted — {hint}."
            else:
                self.good_reps += 1
                quality = "good"
                feedback = f"Rep {self.rep_count} counted!"

            rep_completed = True
            self._awaiting_up_confirmation = False
            self._pending_flawed = False
            self._legs_too_wide_this_rep = False
            self._rep_hip_min = None
            self._rep_hip_max = None

        if feedback is None:
            if self.left_arm.stage == "down" and self.right_arm.stage == "down":
                feedback = "Arms are back — swing forward to finish the rep."
            elif self.left_arm.stage == "up" and self.right_arm.stage == "up":
                feedback = (
                    "Bring your feet in a bit closer together."
                    if not legs_together
                    else "Ready — swing both arms back together."
                )
            else:
                feedback = "Keep both arms swinging together, in sync."

        response.update(
            {
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_form_quality": quality,
                "feedback": feedback,
            }
        )
        return response


class SkierJumpingJacksSession:
    """Full session: one shared pose model + one analyzer.

    `target_reps` / `target_sets` / `set_number` are the coach-assigned
    plan for this user, supplied by the caller (the websocket route, from
    query params) — same convention as `PushupSession` / `ArmCirclesSession`
    / `CrossJacksSession`. The frontend does not decide on its own whether
    a set/exercise is done; `session_complete` and `exercise_complete` are
    both computed here.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = SkierJumpingJacksAnalyzer(target_reps)
        self.target_sets = max(1, target_sets)
        self.set_number = max(1, min(set_number, self.target_sets))

    def detect(self, frame, timestamp_ms: int) -> dict[str, Any]:
        landmarks = self.engine.detect(frame, timestamp_ms)
        result = self.analyzer.update(landmarks, timestamp_ms)
        result["landmarks"] = (
            PoseEngine.landmarks_to_json(landmarks) if landmarks else []
        )

        result["set_number"] = self.set_number
        result["target_sets"] = self.target_sets
        result["exercise_complete"] = bool(
            result["session_complete"] and self.set_number >= self.target_sets
        )
        return result

    def close(self):
        self.engine.close()
