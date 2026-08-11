"""
Skandha Chakra (Shoulder Rotation) Analyzer & Counter — Production Precision Version.

Fixes Applied:
  - Eliminated phase-sync bug that falsely flagged perfect reps as flawed.
  - Replaced hard cooldown lockouts with seamless angle carry-over for 100% rep capture.
  - Evaluates form based on bilateral arm movement contribution.
  - Full telemetry compatibility for UI dashboard displays.
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_SHOULDER,
    PoseEngine,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_SHOULDER,
)

# -------------------------------------------------------------------------
# Calibrated Production Constants
# -------------------------------------------------------------------------

MIN_LANDMARK_VISIBILITY = 0.10

# Measured 2D polar sweep required for 1 full physical rotation
REP_ROTATION_DEG = 250.0

MIN_REP_DURATION = 0.7  # Minimum duration per valid rotation (seconds)
MAX_REP_DURATION = 12.0  # Maximum duration per rotation (seconds)

MAX_SINGLE_FRAME_DELTA_DEG = 75.0  # Discards landmark flicker jumps
MIN_ELBOW_DIST = 0.015  # Prevents origin singularities

VALID_DIRECTIONS = ("forward", "backward", "either")


def _get_val(obj: Any, key: str, default: float = 0.0) -> float:
    """Safely extract coordinate values from either dicts or class objects."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return float(obj.get(key, default))
    return float(getattr(obj, key, default))


def _get_vis(obj: Any) -> float:
    """Safely extract landmark visibility."""
    if obj is None:
        return 0.0
    if isinstance(obj, dict):
        return float(obj.get("visibility", 1.0))
    return float(getattr(obj, "visibility", 1.0))


def _visible(points) -> bool:
    for p in points:
        if p is None:
            return False
        if _get_vis(p) < MIN_LANDMARK_VISIBILITY:
            return False
    return True


def _dist(p1, p2) -> float:
    x1, y1 = _get_val(p1, "x"), _get_val(p1, "y")
    x2, y2 = _get_val(p2, "x"), _get_val(p2, "y")
    return math.hypot(x1 - x2, y1 - y2)


def _angle_delta_deg(new_deg: float, old_deg: float) -> float:
    """Calculates minimal signed angular step handling +/-180 deg wraparound."""
    delta = new_deg - old_deg
    while delta > 180.0:
        delta -= 360.0
    while delta < -180.0:
        delta += 360.0
    return delta


class SkandhaChakraAnalyzer:
    """Precision Skandha Chakra shoulder rotation analyzer and counter."""

    def __init__(self, target_reps: Optional[int] = None, direction: str = "either"):
        self.target_reps = target_reps
        self.direction = direction if direction in VALID_DIRECTIONS else "either"

        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        self._last_left_theta: Optional[float] = None
        self._last_right_theta: Optional[float] = None

        self.cumulative_arc = 0.0  # Degrees accumulated toward current rep
        self.signed_accumulator = 0.0  # Direction tracking (+ = forward, - = backward)

        self.rep_start_time: Optional[float] = None

        # Bilateral participation tracking for form quality
        self._total_active_frames = 0
        self._both_arms_active_frames = 0

        self.session_start_time: Optional[float] = None
        self.ready = True

    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 4.5:
            return "too_slow"
        if duration >= 2.5:
            return "slow"
        if duration >= 1.0:
            return "good"
        if duration >= 0.5:
            return "fast"
        return "too_fast"

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "ready": True,
            "stage": "rotating",
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "rep_completed": False,
            "rep_classification": None,
            "rep_form_quality": None,
            "position_ok": True,
            "position_message": None,
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
            "left_angle": 0.0,
            "right_angle": 0.0,
            "left_arm_angle": 0.0,
            "right_arm_angle": 0.0,
            "angle": 0.0,
            "arms_in_sync": True,
            "rotation_progress": 0.0,
            "rotation_direction": None,
            "target_direction": self.direction,
            "rep_duration": None,
        }

        if landmarks is None or len(landmarks) < 15:
            response["ready"] = False
            response["position_ok"] = False
            response["feedback"] = "No person detected — step into frame."
            return response

        l_shoulder = landmarks[LEFT_SHOULDER]
        r_shoulder = landmarks[RIGHT_SHOULDER]
        l_elbow = landmarks[LEFT_ELBOW]
        r_elbow = landmarks[RIGHT_ELBOW]

        if not _visible((l_shoulder, r_shoulder)):
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = "Keep both shoulders visible in frame."
            return response

        response["pose_detected"] = True

        ls_x, ls_y = _get_val(l_shoulder, "x"), _get_val(l_shoulder, "y")
        rs_x, rs_y = _get_val(r_shoulder, "x"), _get_val(r_shoulder, "y")

        le_x, le_y = _get_val(l_elbow, "x"), _get_val(l_elbow, "y")
        re_x, re_y = _get_val(r_elbow, "x"), _get_val(r_elbow, "y")

        left_dist = _dist(l_shoulder, l_elbow)
        right_dist = _dist(r_shoulder, r_elbow)

        left_ok = _visible((l_shoulder, l_elbow)) and left_dist > MIN_ELBOW_DIST
        right_ok = _visible((r_shoulder, r_elbow)) and right_dist > MIN_ELBOW_DIST

        # ---- Polar Angle Calculation [0°, 360°) ----
        left_theta = None
        if left_ok:
            left_theta = (
                math.degrees(math.atan2(le_y - ls_y, le_x - ls_x)) + 360.0
            ) % 360.0

        right_theta = None
        if right_ok:
            right_theta = (
                math.degrees(math.atan2(re_y - rs_y, re_x - rs_x)) + 360.0
            ) % 360.0

        if left_theta is None and right_theta is None:
            response["low_visibility"] = True
            response["feedback"] = "Place fingers on shoulders and rotate elbows."
            return response

        # Populate telemetry keys for frontend UI
        l_ang = round(left_theta, 1) if left_theta is not None else 0.0
        r_ang = round(right_theta, 1) if right_theta is not None else 0.0
        avg_ang = (
            round((l_ang + r_ang) / 2.0, 1)
            if (left_theta and right_theta)
            else (l_ang or r_ang)
        )

        response["left_angle"] = l_ang
        response["right_angle"] = r_ang
        response["left_arm_angle"] = l_ang
        response["right_arm_angle"] = r_ang
        response["angle"] = avg_ang

        # ---- Calculate Delta Steps per Arm ----
        step_l, signed_l = 0.0, 0.0
        if left_theta is not None and self._last_left_theta is not None:
            d_l = _angle_delta_deg(left_theta, self._last_left_theta)
            if abs(d_l) <= MAX_SINGLE_FRAME_DELTA_DEG:
                step_l = abs(d_l)
                signed_l = d_l

        step_r, signed_r = 0.0, 0.0
        if right_theta is not None and self._last_right_theta is not None:
            d_r = _angle_delta_deg(right_theta, self._last_right_theta)
            if abs(d_r) <= MAX_SINGLE_FRAME_DELTA_DEG:
                step_r = abs(d_r)
                signed_r = d_r

        # ---- Accumulate Motion Arc ----
        active_steps = []
        signed_steps = []
        if step_l > 0:
            active_steps.append(step_l)
            signed_steps.append(signed_l)
        if step_r > 0:
            active_steps.append(step_r)
            signed_steps.append(signed_r)

        if active_steps:
            avg_step = sum(active_steps) / len(active_steps)
            avg_signed = sum(signed_steps) / len(signed_steps)

            if self.rep_start_time is None:
                self.rep_start_time = t
                self._total_active_frames = 0
                self._both_arms_active_frames = 0

            self.cumulative_arc += avg_step
            self.signed_accumulator += avg_signed

            # Form tracking: record if both arms are moving together
            self._total_active_frames += 1
            if step_l > 0.3 and step_r > 0.3:
                self._both_arms_active_frames += 1

            progress = min(1.0, self.cumulative_arc / REP_ROTATION_DEG)
            response["rotation_progress"] = round(progress, 2)

            going_direction = "forward" if self.signed_accumulator >= 0 else "backward"
            response["rotation_direction"] = going_direction

            # ---- Rep Trigger Evaluation ----
            if self.cumulative_arc >= REP_ROTATION_DEG:
                rep_duration = (
                    (t - self.rep_start_time)
                    if self.rep_start_time is not None
                    else 1.0
                )

                direction_ok = (
                    self.direction == "either" or self.direction == going_direction
                )

                if direction_ok and rep_duration >= MIN_REP_DURATION:
                    self.rep_count += 1
                    rep_class = self._classify_tempo(rep_duration)

                    # Form evaluation: both arms active during >= 40% of frames = GOOD REP
                    bilateral_ratio = self._both_arms_active_frames / max(
                        1, self._total_active_frames
                    )

                    if bilateral_ratio >= 0.40 or (
                        left_theta is None or right_theta is None
                    ):
                        rep_form_quality = "good"
                        self.good_reps += 1
                        feedback = f"Great rotation — Rep {self.rep_count}!"
                    else:
                        rep_form_quality = "needs_improvement"
                        self.flawed_reps += 1
                        feedback = f"Rep {self.rep_count} counted — try rotating both elbows equally."

                    # Carry over remaining arc progress for seamless continuous counting
                    self.cumulative_arc %= REP_ROTATION_DEG
                    self.signed_accumulator = 0.0
                    self.rep_start_time = t
                    self._total_active_frames = 0
                    self._both_arms_active_frames = 0

                    response.update(
                        {
                            "rep_count": self.rep_count,
                            "good_reps": self.good_reps,
                            "flawed_reps": self.flawed_reps,
                            "session_complete": self._is_complete(),
                            "rep_completed": True,
                            "rep_classification": rep_class,
                            "rep_form_quality": rep_form_quality,
                            "feedback": feedback,
                            "rep_duration": round(rep_duration, 2),
                        }
                    )

        # Update frame state
        if left_theta is not None:
            self._last_left_theta = left_theta
        if right_theta is not None:
            self._last_right_theta = right_theta

        if response["feedback"] is None:
            response["feedback"] = (
                "Keep rotating your elbows in big, continuous circles."
            )

        return response


class SkandhaChakraSession:
    """Session wrapper for Skandha Chakra Pose detection & analysis."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
        direction: str = "either",
    ):
        self.engine = PoseEngine()
        self.analyzer = SkandhaChakraAnalyzer(target_reps, direction=direction)
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
