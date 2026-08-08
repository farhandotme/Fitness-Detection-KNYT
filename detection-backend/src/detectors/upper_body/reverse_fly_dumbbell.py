"""
Reverse Fly (Dumbbell) rep counting + posture correction.

The movement
------------
Hinged forward at the hips (standing bent-over, or seated bent-over —
either is fine, see "Hip hinge" below), arms hang straight down holding
the dumbbells, then both arms raise out to the sides — like the top of a
"T" — squeezing the shoulder blades together, then lower back down under
control. Rep-based, counted on the return to the hanging-down start
position after a confirmed raised position.

Two independent wrist trackers, required to sync
----------------------------------------------------
This exercise is bilateral by definition — a real rep raises *both*
arms together. Measuring only the distance between the two wrists would
let one arm doing all the work (the other staying at the side) still
read as "wider apart" and falsely count. So each arm is tracked
independently:

    `reach_ratio` (per wrist) = horizontal distance from the wrist to
    its *own* shoulder (not the body midline), normalized by shoulder
    width. Near 0 when the arm hangs straight down under its shoulder;
    grows as the arm swings out to the side.

Each wrist gets its own hysteresis state machine (down/up), same
convention as the limb-pair trackers in Cross Jacks / Skier Jumping
Jacks — and a rep only counts when **both** wrists independently confirm
"up" within `SYNC_WINDOW_SECONDS` of each other, then both confirm
"down" within the same window. Tolerant of the two arms not being in
perfect lockstep, while still refusing to count a rep where only one arm
actually moved.

Hip hinge is graded, not gated
----------------------------------
Reverse fly is usually done bent forward at the hips, and that hinge
angle is genuinely part of good form — but making it a hard requirement
risks the exact failure the Skier Jumping Jacks analyzer had: real
people do this seated (chest resting on the legs), on an incline bench,
or with a shallower hinge than a textbook demo, and any of those could
trip a strict continuous gate at the wrong moment and silently block
every rep. So `hip_hinge_angle` is tracked and folded into
`rep_form_quality` (upright/barely-hinged reps still count, just tagged
`needs_improvement`) rather than blocking the count outright.

Thresholds are deliberately generous
----------------------------------------
Calibrated toward "don't miss a real rep" over "reject anything short of
textbook form," for the same reason documented in the Skier Jumping
Jacks analyzer: an overly strict depth requirement (there, a full
torso-length arm swing) silently produced zero counts on genuinely
correct reps. `WRIST_UP_ABOVE` here asks for a clear, deliberate
outward raise, not full shoulder-height horizontal extension — the
`_IDEAL` thresholds reward the deeper, textbook version via the quality
tier without gatekeeping the count on it.
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    LEFT_WRIST,
    PoseEngine,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)

# -------------------------------------------------------------------------
# Tunable constants
# -------------------------------------------------------------------------

MIN_LANDMARK_VISIBILITY = 0.3

# ---- per-arm reach (wrist-to-own-shoulder horizontal distance / shoulder width) ----
WRIST_DOWN_BELOW = 0.35
WRIST_UP_ABOVE = 0.75
WRIST_DOWN_IDEAL_BELOW = 0.2  # arms hang controlled, close under the shoulders
WRIST_UP_IDEAL_ABOVE = 1.0  # a genuinely full, wide raise to the "T"

# ---- both-wrist sync window ----
SYNC_WINDOW_SECONDS = 0.8

# ---- hip hinge (shoulder-hip-knee), degrees — graded, not gated ----
# Upright/standing reads near 180°; a deep hinge reads much lower. Only
# used for the quality tier — see module docstring.
HINGE_IDEAL_BELOW = 150.0

# ---- elbow softness (shoulder-elbow-wrist), degrees — graded, not gated ----
# A reverse fly keeps a soft bend in the elbows, not a hard lock and not
# a sharp row-like bend. Only flagged if collapsed well past a relaxed bend.
ELBOW_TOO_BENT_BELOW = 110.0

MISTAKE_PENALTY = {
    "shallow_raise": 12,
    "not_hinged": 10,
    "elbows_too_bent": 8,
}

SCORE_HISTORY = 30

# ---- framing (front-facing, standing or bent-over) ----
FRAME_EDGE_MARGIN = 0.02
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
                "You're partly out of frame — step back so your whole body, "
                "both arms included, fits in the shot."
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


class _ArmReachTracker:
    """One down/up hysteresis state machine for one wrist's outward reach.
    Tracks the extreme value reached in each phase for depth/quality
    grading."""

    def __init__(self):
        self.stage: str = "down"  # "down" | "up"
        self.confirmed_up_time: Optional[float] = None
        self.confirmed_down_time: Optional[float] = None
        self.down_extreme = 1.0  # min ratio seen since entering "down" (lower = better)
        self.up_extreme = 0.0  # max ratio seen since entering "up" (higher = better)

    def update(self, ratio: float, t: float) -> None:
        if self.stage == "down":
            self.down_extreme = min(self.down_extreme, ratio)
            if ratio > WRIST_UP_ABOVE:
                self.stage = "up"
                self.up_extreme = ratio
                self.confirmed_up_time = t
        else:  # "up"
            self.up_extreme = max(self.up_extreme, ratio)
            if ratio < WRIST_DOWN_BELOW:
                self.stage = "down"
                self.down_extreme = ratio
                self.confirmed_down_time = t


class ReverseFlyAnalyzer:
    """Stateful Reverse Fly rep counter — both wrists tracked
    independently and required to sync; hip hinge and elbow softness
    graded into quality, never gating the count."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.left_arm = _ArmReachTracker()
        self.right_arm = _ArmReachTracker()

        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        self._awaiting_down_confirmation = False
        self._pending_flawed = False
        self._rep_not_hinged = False
        self._rep_elbows_too_bent = False

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
            "left_reach_ratio": None,
            "right_reach_ratio": None,
            "left_arm_stage": self.left_arm.stage,
            "right_arm_stage": self.right_arm.stage,
            "hip_hinge_angle": None,
            "left_elbow_angle": None,
            "right_elbow_angle": None,
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
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]

        required_ok = _visible(
            (l_shoulder, r_shoulder, l_elbow, r_elbow, l_wrist, r_wrist, l_hip, r_hip)
        )
        if not required_ok:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your upper body clearly — make sure both arms, "
                "shoulders and hips are visible, facing the camera."
            )
            return response

        response["pose_detected"] = True

        shoulder_width = max(_dist(l_shoulder, r_shoulder), 1e-6)

        framing_points = [
            p
            for p in (
                l_shoulder,
                r_shoulder,
                l_elbow,
                r_elbow,
                l_wrist,
                r_wrist,
                l_hip,
                r_hip,
            )
            if _visible((p,))
        ]
        framing_message = _framing_feedback(framing_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        if framing_message is not None:
            response["feedback"] = framing_message
            return response

        left_reach_ratio = abs(l_wrist.x - l_shoulder.x) / shoulder_width
        right_reach_ratio = abs(r_wrist.x - r_shoulder.x) / shoulder_width
        response["left_reach_ratio"] = round(left_reach_ratio, 2)
        response["right_reach_ratio"] = round(right_reach_ratio, 2)

        left_elbow_angle = _angle_deg(l_shoulder, l_elbow, l_wrist)
        right_elbow_angle = _angle_deg(r_shoulder, r_elbow, r_wrist)
        response["left_elbow_angle"] = round(left_elbow_angle, 1)
        response["right_elbow_angle"] = round(right_elbow_angle, 1)

        hip_hinge_angle = None
        if _visible((l_knee, r_knee)):
            left_hinge = _angle_deg(l_shoulder, l_hip, l_knee)
            right_hinge = _angle_deg(r_shoulder, r_hip, r_knee)
            hip_hinge_angle = (left_hinge + right_hinge) / 2.0
            response["hip_hinge_angle"] = round(hip_hinge_angle, 1)

        if hip_hinge_angle is not None and hip_hinge_angle > HINGE_IDEAL_BELOW:
            self._rep_not_hinged = True
        if (
            left_elbow_angle < ELBOW_TOO_BENT_BELOW
            or right_elbow_angle < ELBOW_TOO_BENT_BELOW
        ):
            self._rep_elbows_too_bent = True

        prev_left_up_time = self.left_arm.confirmed_up_time
        prev_right_up_time = self.right_arm.confirmed_up_time
        prev_left_down_time = self.left_arm.confirmed_down_time
        prev_right_down_time = self.right_arm.confirmed_down_time

        self.left_arm.update(left_reach_ratio, t)
        self.right_arm.update(right_reach_ratio, t)

        response["left_arm_stage"] = self.left_arm.stage
        response["right_arm_stage"] = self.right_arm.stage

        rep_completed = False
        quality: Optional[str] = None
        feedback: Optional[str] = None

        # ---- up confirmation: both wrists raised within the sync window ----
        left_just_up = self.left_arm.confirmed_up_time != prev_left_up_time
        right_just_up = self.right_arm.confirmed_up_time != prev_right_up_time
        if (left_just_up or right_just_up) and self._synced(
            self.left_arm.confirmed_up_time, self.right_arm.confirmed_up_time
        ):
            self._awaiting_down_confirmation = True
            shallow = (
                self.left_arm.up_extreme < WRIST_UP_IDEAL_ABOVE
                or self.right_arm.up_extreme < WRIST_UP_IDEAL_ABOVE
            )
            self._pending_flawed = shallow
            feedback = "Raised — now lower back down with control."

        # ---- down confirmation: both wrists back down within the sync window ----
        left_just_down = self.left_arm.confirmed_down_time != prev_left_down_time
        right_just_down = self.right_arm.confirmed_down_time != prev_right_down_time
        if (
            self._awaiting_down_confirmation
            and (left_just_down or right_just_down)
            and self._synced(
                self.left_arm.confirmed_down_time, self.right_arm.confirmed_down_time
            )
        ):
            shallow_down = (
                self.left_arm.down_extreme > WRIST_DOWN_IDEAL_BELOW
                or self.right_arm.down_extreme > WRIST_DOWN_IDEAL_BELOW
            )

            flawed = (
                self._pending_flawed
                or shallow_down
                or self._rep_not_hinged
                or self._rep_elbows_too_bent
            )

            self.rep_count += 1
            if flawed:
                self.flawed_reps += 1
                quality = "needs_improvement"
                if self._rep_not_hinged:
                    hint = "hinge forward more at the hips"
                elif self._rep_elbows_too_bent:
                    hint = "keep a softer bend in your elbows"
                else:
                    hint = "raise wider and lower with more control"
                feedback = f"Rep {self.rep_count} counted — {hint}."
            else:
                self.good_reps += 1
                quality = "good"
                feedback = f"Rep {self.rep_count} counted!"

            rep_completed = True
            self._awaiting_down_confirmation = False
            self._pending_flawed = False
            self._rep_not_hinged = False
            self._rep_elbows_too_bent = False

        if feedback is None:
            if self.left_arm.stage == "up" and self.right_arm.stage == "up":
                feedback = "Arms are raised — lower back down to finish the rep."
            elif self.left_arm.stage == "down" and self.right_arm.stage == "down":
                feedback = "Ready — raise both arms out to the sides together."
            else:
                feedback = "Keep both arms moving together, in sync."

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


class ReverseFlySession:
    """Full session: one shared pose model + one analyzer.

    `target_reps` / `target_sets` / `set_number` are the coach-assigned
    plan for this user, supplied by the caller (the websocket route, from
    query params) — same convention as `PushupSession` / `ArmCirclesSession`
    / `CrossJacksSession` / `SkierJumpingJacksSession`. The frontend does
    not decide on its own whether a set/exercise is done; `session_complete`
    and `exercise_complete` are both computed here.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = ReverseFlyAnalyzer(target_reps)
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
