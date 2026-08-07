"""
Cross Jacks rep counting + posture correction.

The movement
------------
Like a jumping jack, but instead of arms going overhead and legs opening
wide, the limbs **cross in front of the body**: feet cross in front of
each other and arms cross in front of the chest (like self-hug), then
open back out to the start position — alternating which foot/arm leads
each rep. Counting doesn't need to know *which* limb is in front on a
given rep (that's a stylistic detail); it only needs to detect the
open <-> crossed cycle reliably, for both arms and legs together.

Two independent distance signals, one state machine per limb pair
--------------------------------------------------------------------
  * `leg_spread_ratio` = ankle-to-ankle distance, normalized by shoulder
    width. Large when feet are apart, small when they're crossed
    together.
  * `arm_spread_ratio` = wrist-to-wrist distance, same normalization.
    Large when arms are out to the sides, small when crossed at the chest.

Each gets its own hysteresis state machine (open/crossed), same
convention as the elbow up/down state machine in `PushupAnalyzer` — a
band between the "crossed" and "open" thresholds so a value sitting
right on the boundary doesn't flicker the state every frame.

Why arms and legs are required to sync, not just checked independently
-------------------------------------------------------------------------
A Cross Jack is a *whole-body* movement — legs crossing without the arms
crossing (or vice versa) is a different, incomplete motion, not a real
rep. So a rep only counts when both the leg tracker and the arm tracker
independently confirm "crossed" within `SYNC_WINDOW_SECONDS` of each
other, and then both confirm "open" within the same window — mirroring
the both-arms-synced approach in the Arm Circles analyzer. This is
deliberately tolerant of natural timing skew between arms and legs
(nobody's limbs move in perfect lockstep), while still refusing to count
a rep from just one half of the body swinging on its own.

A rep is counted on the return to OPEN after a confirmed CROSSED (same
"count on completing the full cycle back to start" convention as the
push-up down->up counter) — this is an edge-triggered, one-shot count
per cycle, so it can't double-count a single rep and can't be fooled by
holding position or by camera jitter re-confirming the same state.
Tuned for fast tempo
----------------------
At real Cross Jacks speed a full open->crossed->open cycle can complete
in well under half a second. Whatever frames actually get sampled in
that window have to land on values that cross the OPEN/CROSSED
thresholds — so every threshold and margin below is deliberately set as
tight as it can be while still keeping the two states clearly separated,
rather than requiring a slow, deep, held-open or held-crossed position.
A wide dead zone or a strict framing/visibility gate doesn't make
tracking more accurate here; it just makes it easier for a fast,
correctly-performed rep to slip between two sampled frames and never get
recorded at all. See the inline comments on `MIN_LANDMARK_VISIBILITY`,
`FRAME_EDGE_MARGIN`, and the OPEN/CROSSED thresholds for the reasoning
behind each specific value.
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

MIN_LANDMARK_VISIBILITY = 0.3  # loosened from 0.4 — fast swings blur the
# wrist/ankle landmarks a bit; a stricter floor here drops tracking right
# at the moment (peak speed) it's most likely to blur, which is exactly
# when a fast rep needs a sample.

# ---- leg spread (ankle-to-ankle / shoulder width) ----
# The gap between OPEN and CROSSED thresholds is deliberately not huge:
# at real Cross Jacks tempo a full open->crossed->open cycle can take
# well under half a second, so however many frames actually get sampled
# in that window have to land on values that cross both thresholds. A
# wide "dead zone" between them makes that easy to miss on a fast,
# smaller-amplitude rep — not because the rep was wrong, but because no
# sampled frame happened to fall inside a narrow catch-zone. These bands
# are set as tight as they can be while still keeping OPEN and CROSSED
# clearly separated, so a fast rep is more likely to register.
LEG_OPEN_ABOVE = 1.15
LEG_CROSSED_BELOW = 0.65
# "Ideal" (good-tier) thresholds are intentionally looser than they'd be
# for a slow, held pose — fast tempo naturally means less time spent at
# each extreme, so requiring the same depth as a slow rep would tag a
# fast, genuinely correct rep as "needs_improvement" for no real reason.
LEG_OPEN_IDEAL_ABOVE = 1.5
LEG_CROSSED_IDEAL_BELOW = 0.5

# ---- arm spread (wrist-to-wrist / shoulder width) ----
ARM_OPEN_ABOVE = 1.7
ARM_CROSSED_BELOW = 0.95
ARM_OPEN_IDEAL_ABOVE = 2.2
ARM_CROSSED_IDEAL_BELOW = 0.7

# ---- both-limb-pairs sync window ----
SYNC_WINDOW_SECONDS = 0.6

MISTAKE_PENALTY = {
    "shallow_open": 12,
    "shallow_cross": 12,
}

SCORE_HISTORY = 30

# ---- framing (front-facing, standing) ----
# Edge margin loosened slightly from the other exercises' 0.03 — a fast,
# wide arm swing can legitimately bring a wrist close to the frame edge
# for an instant, and that instant is often the exact "open" peak the
# rep needs recorded. A hard framing block right at that moment would
# drop the sample that mattered most.
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
                "You're partly out of frame — step back so your full body, "
                "arms and legs included, fits in the shot."
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


class _LimbPairTracker:
    """One open/crossed hysteresis state machine for one limb pair
    (both ankles, or both wrists). Tracks the extreme value reached in
    each phase for depth/quality grading."""

    def __init__(self):
        self.stage: str = "open"  # "open" | "crossed"
        self.confirmed_crossed_time: Optional[float] = None
        self.confirmed_open_time: Optional[float] = None
        self.open_extreme = 0.0  # max ratio seen since entering "open"
        self.crossed_extreme = float("inf")  # min ratio seen since entering "crossed"

    def update(
        self, ratio: float, t: float, open_above: float, crossed_below: float
    ) -> None:
        if self.stage == "open":
            self.open_extreme = max(self.open_extreme, ratio)
            if ratio < crossed_below:
                self.stage = "crossed"
                self.crossed_extreme = ratio
                self.confirmed_crossed_time = t
        else:  # "crossed"
            self.crossed_extreme = min(self.crossed_extreme, ratio)
            if ratio > open_above:
                self.stage = "open"
                self.open_extreme = ratio
                self.confirmed_open_time = t


class CrossJacksAnalyzer:
    """Stateful Cross Jacks rep counter, arms and legs tracked
    independently and required to sync for a rep to count."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.legs = _LimbPairTracker()
        self.arms = _LimbPairTracker()

        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        self._awaiting_open_confirmation = False
        self._pending_flawed = False

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
            "leg_spread_ratio": None,
            "arm_spread_ratio": None,
            "legs_stage": self.legs.stage,
            "arms_stage": self.arms.stage,
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
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]

        required_ok = _visible(
            (l_shoulder, r_shoulder, l_wrist, r_wrist, l_ankle, r_ankle, l_hip, r_hip)
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

        framing_message = _framing_feedback(
            (l_shoulder, r_shoulder, l_wrist, r_wrist, l_ankle, r_ankle, l_hip, r_hip)
        )
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        if framing_message is not None:
            response["feedback"] = framing_message
            return response

        leg_spread_ratio = _dist(l_ankle, r_ankle) / shoulder_width
        arm_spread_ratio = _dist(l_wrist, r_wrist) / shoulder_width
        response["leg_spread_ratio"] = round(leg_spread_ratio, 2)
        response["arm_spread_ratio"] = round(arm_spread_ratio, 2)

        prev_legs_crossed_time = self.legs.confirmed_crossed_time
        prev_arms_crossed_time = self.arms.confirmed_crossed_time
        prev_legs_open_time = self.legs.confirmed_open_time
        prev_arms_open_time = self.arms.confirmed_open_time

        self.legs.update(leg_spread_ratio, t, LEG_OPEN_ABOVE, LEG_CROSSED_BELOW)
        self.arms.update(arm_spread_ratio, t, ARM_OPEN_ABOVE, ARM_CROSSED_BELOW)

        response["legs_stage"] = self.legs.stage
        response["arms_stage"] = self.arms.stage

        rep_completed = False
        quality: Optional[str] = None
        feedback: Optional[str] = None

        # ---- crossed confirmation: both limb pairs crossed within the sync window ----
        legs_just_crossed = self.legs.confirmed_crossed_time != prev_legs_crossed_time
        arms_just_crossed = self.arms.confirmed_crossed_time != prev_arms_crossed_time
        if (legs_just_crossed or arms_just_crossed) and self._synced(
            self.legs.confirmed_crossed_time, self.arms.confirmed_crossed_time
        ):
            self._awaiting_open_confirmation = True
            shallow = (
                self.legs.crossed_extreme > LEG_CROSSED_IDEAL_BELOW
                or self.arms.crossed_extreme > ARM_CROSSED_IDEAL_BELOW
            )
            self._pending_flawed = shallow
            feedback = "Crossed — now open back out."

        # ---- open confirmation: both limb pairs open within the sync window ----
        legs_just_opened = self.legs.confirmed_open_time != prev_legs_open_time
        arms_just_opened = self.arms.confirmed_open_time != prev_arms_open_time
        if (
            self._awaiting_open_confirmation
            and (legs_just_opened or arms_just_opened)
            and self._synced(
                self.legs.confirmed_open_time, self.arms.confirmed_open_time
            )
        ):
            shallow_open = (
                self.legs.open_extreme < LEG_OPEN_IDEAL_ABOVE
                or self.arms.open_extreme < ARM_OPEN_IDEAL_ABOVE
            )
            flawed = self._pending_flawed or shallow_open

            self.rep_count += 1
            if flawed:
                self.flawed_reps += 1
                quality = "needs_improvement"
                feedback = f"Rep {self.rep_count} counted — go wider on the open, deeper on the cross."
            else:
                self.good_reps += 1
                quality = "good"
                feedback = f"Rep {self.rep_count} counted!"

            rep_completed = True
            self._awaiting_open_confirmation = False
            self._pending_flawed = False

        if feedback is None:
            if self.legs.stage == "crossed" and self.arms.stage == "crossed":
                feedback = "Crossed — now open back out to finish the rep."
            elif self.legs.stage == "open" and self.arms.stage == "open":
                feedback = "Ready — cross your arms and legs together."
            else:
                feedback = "Keep your arms and legs moving together."

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


class CrossJacksSession:
    """Full session: one shared pose model + one analyzer.

    `target_reps` / `target_sets` / `set_number` are the coach-assigned
    plan for this user, supplied by the caller (the websocket route, from
    query params) — same convention as `PushupSession` / `ArmCirclesSession`.
    The frontend does not decide on its own whether a set/exercise is
    done; `session_complete` and `exercise_complete` are both computed here.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = CrossJacksAnalyzer(target_reps)
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
