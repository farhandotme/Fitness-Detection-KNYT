"""
Lying Dumbbell Chest Fly rep counting + posture correction.

The movement
------------
Lying flat on a bench (supine position), dumbbells start held directly above
the chest with arms extended upwards (wrist reach close to shoulder alignment).
The arms lower outward in a wide arc until parallel with the chest/torso, keeping
a light bend in the elbows, then squeeze back together at the top. Reps are
counted when both arms return to the top extended position after a confirmed
bottom stretch.

Two independent wrist trackers, required to sync
----------------------------------------------------
This exercise is bilateral. To prevent single-arm bias, each arm is tracked
independently using reach ratio (horizontal wrist-to-shoulder distance normalized
by shoulder width).

Hysteresis Stage:
  - "up": Wrists aligned close above chest/shoulders.
  - "down": Wrists flared wide to the sides.

Thresholds are deliberately generous to avoid missing legitimate reps while
grading quality via form metrics.
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
WRIST_UP_BELOW = 0.45  # Near top position (close to shoulders/chest midline)
WRIST_DOWN_ABOVE = 0.85  # Wide outwards extension (fly bottom)
WRIST_UP_IDEAL_BELOW = 0.30  # Ideal top squeeze
WRIST_DOWN_IDEAL_ABOVE = 1.10  # Deep, ideal chest fly range

# ---- both-wrist sync window ----
SYNC_WINDOW_SECONDS = 0.8

# ---- elbow softness (shoulder-elbow-wrist), degrees — graded, not gated ----
ELBOW_TOO_BENT_BELOW = 100.0  # Locked into a press instead of a fly
ELBOW_TOO_STRAIGHT_ABOVE = 175.0  # Hyper-extended elbows

MISTAKE_PENALTY = {
    "shallow_fly": 12,
    "elbows_too_bent": 10,
    "elbows_hyper_extended": 8,
}

SCORE_HISTORY = 30

# ---- framing constants ----
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
                "You're partly out of frame — adjust camera so your upper body "
                "and full arm extension are in view."
            )

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "You're too close to the camera — step back or move camera further."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class _ArmFlyTracker:
    """Hysteresis tracker for chest fly motion per wrist.
    Starts in 'up' position (arms held up high above chest)."""

    def __init__(self):
        self.stage: str = "up"  # "up" (top) | "down" (wide bottom)
        self.confirmed_up_time: Optional[float] = None
        self.confirmed_down_time: Optional[float] = None
        self.up_extreme = 0.0  # min reach ratio seen at top
        self.down_extreme = 0.0  # max reach ratio seen at bottom

    def update(self, ratio: float, t: float) -> None:
        if self.stage == "up":
            self.up_extreme = min(
                self.up_extreme if self.up_extreme > 0 else ratio, ratio
            )
            if ratio > WRIST_DOWN_ABOVE:
                self.stage = "down"
                self.down_extreme = ratio
                self.confirmed_down_time = t
        else:  # "down"
            self.down_extreme = max(self.down_extreme, ratio)
            if ratio < WRIST_UP_BELOW:
                self.stage = "up"
                self.up_extreme = ratio
                self.confirmed_up_time = t


class ChestFlyAnalyzer:
    """Stateful Lying Dumbbell Chest Fly rep counter and form analyzer."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.left_arm = _ArmFlyTracker()
        self.right_arm = _ArmFlyTracker()

        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        self._awaiting_up_confirmation = False
        self._pending_flawed = False
        self._rep_elbows_too_bent = False
        self._rep_elbows_hyper_extended = False

        self.session_start_time: Optional[float] = None

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    @staticmethod
    def _synced(a: Optional[float], b: Optional[float]) -> bool:
        return a is not None and b is not None and abs(a - b) <= SYNC_WINDOW_SECONDS

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
                "No person detected — position yourself in frame lying down."
            )
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]

        required_ok = _visible(
            (l_shoulder, r_shoulder, l_elbow, r_elbow, l_wrist, r_wrist, l_hip, r_hip)
        )
        if not required_ok:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see upper body clearly — ensure arms, chest, and shoulders "
                "are completely visible."
            )
            return response

        response["pose_detected"] = True
        shoulder_width = max(_dist(l_shoulder, r_shoulder), 1e-6)

        framing_points = [
            p
            for p in (l_shoulder, r_shoulder, l_elbow, r_elbow, l_wrist, r_wrist)
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

        if (
            left_elbow_angle < ELBOW_TOO_BENT_BELOW
            or right_elbow_angle < ELBOW_TOO_BENT_BELOW
        ):
            self._rep_elbows_too_bent = True
        elif (
            left_elbow_angle > ELBOW_TOO_STRAIGHT_ABOVE
            or right_elbow_angle > ELBOW_TOO_STRAIGHT_ABOVE
        ):
            self._rep_elbows_hyper_extended = True

        prev_left_down_time = self.left_arm.confirmed_down_time
        prev_right_down_time = self.right_arm.confirmed_down_time
        prev_left_up_time = self.left_arm.confirmed_up_time
        prev_right_up_time = self.right_arm.confirmed_up_time

        self.left_arm.update(left_reach_ratio, t)
        self.right_arm.update(right_reach_ratio, t)

        response["left_arm_stage"] = self.left_arm.stage
        response["right_arm_stage"] = self.right_arm.stage

        rep_completed = False
        quality: Optional[str] = None
        feedback: Optional[str] = None

        # ---- Down confirmation (bottom wide stretch reached) ----
        left_just_down = self.left_arm.confirmed_down_time != prev_left_down_time
        right_just_down = self.right_arm.confirmed_down_time != prev_right_down_time
        if (left_just_down or right_just_down) and self._synced(
            self.left_arm.confirmed_down_time, self.right_arm.confirmed_down_time
        ):
            self._awaiting_up_confirmation = True
            shallow = (
                self.left_arm.down_extreme < WRIST_DOWN_IDEAL_ABOVE
                or self.right_arm.down_extreme < WRIST_DOWN_IDEAL_ABOVE
            )
            self._pending_flawed = shallow
            feedback = "Good stretch — now bring weights back up above your chest."

        # ---- Up confirmation (returned to top position) ----
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
                self.left_arm.up_extreme > WRIST_UP_IDEAL_BELOW
                or self.right_arm.up_extreme > WRIST_UP_IDEAL_BELOW
            )

            flawed = (
                self._pending_flawed
                or shallow_up
                or self._rep_elbows_too_bent
                or self._rep_elbows_hyper_extended
            )

            self.rep_count += 1
            if flawed:
                self.flawed_reps += 1
                quality = "needs_improvement"
                if self._rep_elbows_too_bent:
                    hint = "avoid bending elbows too much into a press"
                elif self._rep_elbows_hyper_extended:
                    hint = "keep a slight bend in your elbows to protect joints"
                else:
                    hint = "open wide at the bottom and bring dumbbells together at top"
                feedback = f"Rep {self.rep_count} counted — {hint}."
            else:
                self.good_reps += 1
                quality = "good"
                feedback = f"Rep {self.rep_count} counted!"

            rep_completed = True
            self._awaiting_up_confirmation = False
            self._pending_flawed = False
            self._rep_elbows_too_bent = False
            self._rep_elbows_hyper_extended = False

        if feedback is None:
            if self.left_arm.stage == "down" and self.right_arm.stage == "down":
                feedback = "Arms extended wide — squeeze chest to bring arms back up."
            elif self.left_arm.stage == "up" and self.right_arm.stage == "up":
                feedback = "Ready — lower arms outward in a controlled wide arc."
            else:
                feedback = "Keep both arms moving symmetrically."

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


class ChestFlySession:
    """Full session manager for Lying Chest Fly."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = ChestFlyAnalyzer(target_reps)
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
