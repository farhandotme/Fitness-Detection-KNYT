"""
Lunge to Knee Drive rep counting + posture correction.

The movement
------------
A compound, two-phase movement, not a simple bend/extend: one leg steps
back into a reverse lunge (both knees bend, working leg's knee drops
toward the floor), then explosively drives forward and up into a high
knee — hip flexion bringing the thigh up in front — while the other leg
straightens to standing, balancing on one leg at the top. The leg then
resets. Rep-based, alternating; each leg's full lunge-then-drive-then-
reset cycle counts toward the total, same "both legs tracked
independently, each contributes to the combined total" convention as
Standing Side Leg Raise and Standing Hamstring Curl.

Why this needed a different design from every exercise before it
---------------------------------------------------------------------
Every previous rep counter in this codebase reduces to one axis of
motion per cycle: a joint bends then extends, or a limb swings out then
back. This exercise genuinely has two *different* axes that must happen
in order — knee flexion (the lunge) first, then hip flexion (the drive)
— and counting either alone would count the wrong thing: knee flexion
alone can't tell a lunge from a squat, hip flexion alone can't tell a
knee drive from a plain high-knee with no lunge at all. So each leg gets
a proper three-state sequential machine instead of a two-state
hysteresis tracker:

    neutral -> lunged -> driven -> neutral (rep counted)

`lunged` requires knee flexion (the lunge dip). `driven` requires hip
flexion (the knee raising up in front) and can only be reached *from*
`lunged` — reaching a high knee without first dipping into a lunge does
not advance the state, which is exactly the check that makes this
"lunge to knee drive" rather than "lunge" or "knee drive" in isolation.
Returning to `neutral` (both knee and hip re-extended) is what counts
the rep — same "count on return to start" convention used everywhere
else in this codebase.

Thresholds are deliberately generous
----------------------------------------
Calibrated toward "don't miss a real rep" over "reject anything short of
a textbook-deep lunge and a hip-height knee drive," for the same reason
documented in the Skier Jumping Jacks analyzer: an overly strict depth
requirement on a multi-part movement compounds fast and has silently
produced zero counts on genuinely correct reps before. The `_IDEAL`
thresholds reward real depth (a proper lunge, a high knee drive) via
the quality tier, without gatekeeping the count on it.

What's graded, not gated
-----------------------------
The support leg staying extended and balanced during the drive is a
real form cue, but it's graded into `rep_form_quality`, not required to
count — same reasoning as every other secondary form check in this
codebase now: balance varies, camera angle varies, and a hard
requirement on a secondary characteristic risks blocking a rep that
was, in every way that actually defines this exercise, done correctly.

A known simplification: telling a lunge from a plain high-knee
--------------------------------------------------------------------
Knee angle and hip angle of one leg alone can't fully distinguish "step
back into a lunge, then drive the knee" from "just do a high knee,"
since a high knee's thigh-raise often bends the knee somewhat too,
which could in principle satisfy the `lunged` threshold on its own. The
best available signal for the difference — without adding a strict,
compounding requirement that risks the same silent-zero-counting
failure documented throughout this codebase — is that a genuine lunge
keeps the working foot planted on the ground while the knee bends,
whereas a high knee lifts the foot right away. `EARLY_LIFT_RATIO` grades
that (foot lifting well off the ground during the `lunged` phase, before
the drive even starts, tags the rep `needs_improvement`) rather than
blocking the count on it — a genuine, unambiguous limitation of judging
stance from 2D joint angles alone, handled as honestly as it can be
without over-constraining the count.
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
)

# -------------------------------------------------------------------------
# Tunable constants
# -------------------------------------------------------------------------

MIN_LANDMARK_VISIBILITY = 0.25

# ---- knee angle (hip-knee-ankle), degrees — the "lunge" phase signal ----
LUNGE_KNEE_BELOW = 130.0        # a moderate lunge dip — enters "lunged"
LUNGE_KNEE_IDEAL_BELOW = 105.0  # a proper, deeper lunge — "good" tier

# ---- hip angle (shoulder-hip-knee), degrees — the "drive" phase signal ----
DRIVE_HIP_BELOW = 110.0        # a clear knee drive — enters "driven" (only from "lunged")
DRIVE_HIP_IDEAL_BELOW = 85.0   # a strong, hip-height knee drive — "good" tier

# ---- reset back to neutral (both knee and hip re-extended) ----
RESET_KNEE_ABOVE = 150.0
RESET_HIP_ABOVE = 150.0

# ---- support (standing) leg staying extended during the drive — graded, not gated ----
SUPPORT_LEG_UNSTABLE_BELOW = 150.0

# ---- working-foot lift-off during the lunge phase, normalized by torso length ----
# Graded, not gated. See _LungeKneeDriveTracker.
EARLY_LIFT_RATIO = 0.12

MISTAKE_PENALTY = {
    "shallow_lunge": 10,
    "shallow_drive": 10,
    "support_leg_unstable": 8,
}

SCORE_HISTORY = 30

# ---- framing (front-facing or 3/4 angle, standing) ----
FRAME_EDGE_MARGIN = 0.02
BBOX_TOO_CLOSE = 0.97
BBOX_TOO_FAR = 0.10


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


def _angle_scale(a, b) -> float:
    """Euclidean distance between two landmarks — used only as a
    camera-distance-normalizing scale reference, never as an angle."""
    return math.hypot(a.x - b.x, a.y - b.y)


def _angle_deg(a, b, c) -> float:
    ang = math.degrees(
        math.atan2(c.y - b.y, c.x - b.x) - math.atan2(a.y - b.y, a.x - b.x)
    )
    ang = abs(ang)
    if ang > 180:
        ang = 360 - ang
    return ang


def _framing_feedback(points) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — step back so your whole body "
                "fits in the shot."
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


class _LungeKneeDriveTracker:
    """Three-state sequential machine for one leg: neutral -> lunged ->
    driven -> neutral (rep counted). See module docstring for why this
    needs to be sequential rather than a simple two-state hysteresis
    tracker — the defining feature of this exercise is that the knee
    bend and the hip drive happen *in order*, not independently."""

    def __init__(self):
        self.stage: str = "neutral"  # "neutral" | "lunged" | "driven"
        self.reps = 0
        self.lunge_knee_extreme = 180.0  # min knee angle seen during "lunged" (lower = deeper)
        self.drive_hip_extreme = 180.0  # min hip angle seen during "driven" (lower = higher knee)
        self.just_completed = False  # edge-triggered, true for one update() call
        self.last_rep_quality: Optional[str] = None
        self._had_unstable_support = False
        self._lunge_ankle_y_start: Optional[float] = None
        self._lifted_off_early = False

    def update(
        self,
        knee_angle: float,
        hip_angle: float,
        ankle_y: float,
        scale: float,
        support_unstable: bool,
    ) -> None:
        self.just_completed = False

        if self.stage == "neutral":
            if knee_angle < LUNGE_KNEE_BELOW:
                self.stage = "lunged"
                self.lunge_knee_extreme = knee_angle
                self._had_unstable_support = False
                self._lunge_ankle_y_start = ankle_y
                self._lifted_off_early = False

        elif self.stage == "lunged":
            self.lunge_knee_extreme = min(self.lunge_knee_extreme, knee_angle)
            self._had_unstable_support = self._had_unstable_support or support_unstable
            # A genuine lunge keeps the working foot planted while the
            # knee bends; the foot lifting well off the ground during
            # this phase (rather than only during the drive that
            # follows) looks more like a plain high-knee that happened
            # to also bend the knee along the way. Graded, not gated —
            # see module docstring. Normalized by torso length so this
            # holds regardless of camera distance.
            if self._lunge_ankle_y_start is not None:
                lift = (self._lunge_ankle_y_start - ankle_y) / max(scale, 1e-6)
                if lift > EARLY_LIFT_RATIO:
                    self._lifted_off_early = True
            if hip_angle < DRIVE_HIP_BELOW:
                self.stage = "driven"
                self.drive_hip_extreme = hip_angle
            elif knee_angle > RESET_KNEE_ABOVE:
                # Stood back up out of the lunge without ever driving the
                # knee — not a completed rep, reset silently and wait for
                # the next genuine attempt. No penalty, nothing counted.
                self.stage = "neutral"

        else:  # "driven"
            self.drive_hip_extreme = min(self.drive_hip_extreme, hip_angle)
            self._had_unstable_support = self._had_unstable_support or support_unstable
            if knee_angle > RESET_KNEE_ABOVE and hip_angle > RESET_HIP_ABOVE:
                self.stage = "neutral"

                shallow_lunge = self.lunge_knee_extreme > LUNGE_KNEE_IDEAL_BELOW
                shallow_drive = self.drive_hip_extreme > DRIVE_HIP_IDEAL_BELOW
                flawed = (
                    shallow_lunge
                    or shallow_drive
                    or self._had_unstable_support
                    or self._lifted_off_early
                )

                self.reps += 1
                self.just_completed = True
                self.last_rep_quality = "needs_improvement" if flawed else "good"


class LungeToKneeDriveAnalyzer:
    """Stateful Lunge to Knee Drive rep counter — left and right legs
    tracked fully independently via the sequential per-leg state
    machine, each contributing to the combined total."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.left_leg = _LungeKneeDriveTracker()
        self.right_leg = _LungeKneeDriveTracker()

        self.good_reps = 0
        self.flawed_reps = 0

        self.session_start_time: Optional[float] = None

    # ---------------------------------------------------------------
    @property
    def rep_count(self) -> int:
        return self.left_leg.reps + self.right_leg.reps

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

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
            "left_knee_angle": None,
            "right_knee_angle": None,
            "left_hip_angle": None,
            "right_hip_angle": None,
            "left_leg_stage": self.left_leg.stage,
            "right_leg_stage": self.right_leg.stage,
            "left_leg_reps": self.left_leg.reps,
            "right_leg_reps": self.right_leg.reps,
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
            response["feedback"] = "No person detected — step into frame, facing the camera."
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        # Core counting needs hip/knee/ankle per leg (for knee_angle) plus
        # shoulders (for hip_angle) — both signals are load-bearing here,
        # unlike the exercises where shoulder-derived checks were grading
        # -only, so shoulders are part of the required set this time.
        required_ok = _visible(
            (l_shoulder, r_shoulder, l_hip, r_hip, l_knee, r_knee, l_ankle, r_ankle)
        )
        if not required_ok:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your full body clearly — make sure your shoulders, "
                "hips, knees and ankles are all visible, facing the camera."
            )
            return response

        response["pose_detected"] = True

        # Framing checked against shoulders + hips — a real torso-sized
        # span (see the Standing Hamstring Curl fix for why a degenerate
        # 2-point span is a real bug, not just a style choice) — and never
        # the knees/ankles, which are supposed to move through a large
        # range during this exercise.
        framing_message = _framing_feedback((l_shoulder, r_shoulder, l_hip, r_hip))
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        if framing_message is not None:
            response["feedback"] = framing_message
            return response

        left_knee_angle = _angle_deg(l_hip, l_knee, l_ankle)
        right_knee_angle = _angle_deg(r_hip, r_knee, r_ankle)
        left_hip_angle = _angle_deg(l_shoulder, l_hip, l_knee)
        right_hip_angle = _angle_deg(r_shoulder, r_hip, r_knee)

        response["left_knee_angle"] = round(left_knee_angle, 1)
        response["right_knee_angle"] = round(right_knee_angle, 1)
        response["left_hip_angle"] = round(left_hip_angle, 1)
        response["right_hip_angle"] = round(right_hip_angle, 1)

        # Which leg is currently active is approximated each frame as
        # whichever leg has the more-flexed hip (i.e. is further into its
        # own cycle) — used for both the support-leg quality grading below.
        left_is_active = left_hip_angle <= right_hip_angle
        left_support_unstable = right_knee_angle < SUPPORT_LEG_UNSTABLE_BELOW
        right_support_unstable = left_knee_angle < SUPPORT_LEG_UNSTABLE_BELOW

        left_scale = max(_angle_scale(l_shoulder, l_hip), 1e-6)
        right_scale = max(_angle_scale(r_shoulder, r_hip), 1e-6)

        self.left_leg.update(
            left_knee_angle,
            left_hip_angle,
            ankle_y=l_ankle.y,
            scale=left_scale,
            support_unstable=left_support_unstable if left_is_active else False,
        )
        self.right_leg.update(
            right_knee_angle,
            right_hip_angle,
            ankle_y=r_ankle.y,
            scale=right_scale,
            support_unstable=right_support_unstable if not left_is_active else False,
        )

        response["left_leg_stage"] = self.left_leg.stage
        response["right_leg_stage"] = self.right_leg.stage

        rep_completed = False
        quality: Optional[str] = None
        feedback: Optional[str] = None

        if self.left_leg.just_completed:
            rep_completed = True
            quality = self.left_leg.last_rep_quality
            if quality == "good":
                self.good_reps += 1
                feedback = f"Left leg rep {self.left_leg.reps} counted!"
            else:
                self.flawed_reps += 1
                feedback = (
                    f"Left leg rep {self.left_leg.reps} counted — dip deeper into "
                    "the lunge, drive the knee higher."
                )

        if self.right_leg.just_completed:
            rep_completed = True
            right_quality = self.right_leg.last_rep_quality
            if right_quality == "good":
                self.good_reps += 1
            else:
                self.flawed_reps += 1
            if feedback is None:
                quality = right_quality
                if right_quality == "good":
                    feedback = f"Right leg rep {self.right_leg.reps} counted!"
                else:
                    feedback = (
                        f"Right leg rep {self.right_leg.reps} counted — dip deeper into "
                        "the lunge, drive the knee higher."
                    )
            elif right_quality == "needs_improvement":
                quality = "needs_improvement"

        if feedback is None:
            if self.left_leg.stage == "driven":
                feedback = "Left knee driven up — reset back to standing."
            elif self.right_leg.stage == "driven":
                feedback = "Right knee driven up — reset back to standing."
            elif self.left_leg.stage == "lunged":
                feedback = "Left leg lunged — drive that knee up and forward."
            elif self.right_leg.stage == "lunged":
                feedback = "Right leg lunged — drive that knee up and forward."
            else:
                feedback = "Ready — step back into a lunge, then drive the knee up."

        response.update(
            {
                "left_leg_reps": self.left_leg.reps,
                "right_leg_reps": self.right_leg.reps,
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


class LungeToKneeDriveSession:
    """Full session: one shared pose model + one analyzer.

    `target_reps` / `target_sets` / `set_number` are the coach-assigned
    plan for this user, supplied by the caller (the websocket route, from
    query params) — same convention as every other rep-based session in
    this codebase. The frontend does not decide on its own whether a
    set/exercise is done; `session_complete` and `exercise_complete` are
    both computed here.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = LungeToKneeDriveAnalyzer(target_reps)
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
