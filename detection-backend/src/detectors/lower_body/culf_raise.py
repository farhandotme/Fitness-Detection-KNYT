"""
Calf Raise Analyzer (Leg-Only Restricted Version).

This version tracks Calf Raises strictly from the hips down. Upper body,
shoulders, and torso deviations are no longer required to be visible in frame.
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_FOOT_INDEX,
    LEFT_HEEL,
    LEFT_HIP,
    LEFT_KNEE,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_FOOT_INDEX,
    RIGHT_HEEL,
    RIGHT_HIP,
    RIGHT_KNEE,
)

MIN_LANDMARK_VISIBILITY = 0.4
MIN_FOOT_VISIBILITY = 0.2

UP_LIFT = 0.10
DOWN_LIFT = 0.03
MIN_LIFT_DELTA = 0.07
MIN_PER_FOOT_LIFT = 0.03

MIN_REP_DURATION = 0.25
MAX_REP_DURATION = 4.0

KNEE_STRAIGHT_MIN_DEG = 155.0
KNEE_HARD_BEND_DEG = 140.0
HIP_RISE_JUMP_RATIO = 0.18

STABLE_STANDING_FRAMES = 5
GRACE_FRAMES = 8
CALIBRATION_FRAMES = 12

FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.97
BBOX_TOO_FAR = 0.12


class _Point:
    __slots__ = ("x", "y")

    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y


def _midpoint(a, b) -> _Point:
    return _Point((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)


def _visible(points, min_vis: float = MIN_LANDMARK_VISIBILITY) -> bool:
    for p in points:
        if p is None:
            return False
        v = getattr(p, "visibility", None)
        if v is not None and v < min_vis:
            return False
    return True


def _angle_deg(a, b, c) -> float:
    ang = math.degrees(
        math.atan2(c.y - b.y, c.x - b.x) - math.atan2(a.y - b.y, a.x - b.x)
    )
    ang = abs(ang)
    if ang > 180:
        ang = 360 - ang
    return ang


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _framing_feedback(points: list[_Point]) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "Legs partly out of frame — adjust camera so hips, knees, "
                "and feet are fully visible."
            )

    if len(points) < 4:
        return None

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "Legs too close to camera — step back so lower body fits."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "Too far from camera — move closer for accurate foot tracking."

    return None


class CalfRaiseAnalyzer:
    """Stateful Calf Raise analyzer restricted exclusively to leg tracking."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps
        self.stage = "down"
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        self.smoothed_lift: Optional[float] = None
        self.last_lift: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None
        self.rep_start_time: Optional[float] = None
        self.lift_smooth_alpha = 0.45

        self._rep_hip_start_y: Optional[float] = None
        self._rep_min_knee_angle: Optional[float] = None
        self._rep_left_peak: float = 0.0
        self._rep_right_peak: float = 0.0
        self._current_rep_issues: set[str] = set()

        self.session_start_time: Optional[float] = None

        self._standing_streak = 0
        self._bad_streak = 0
        self.ready = False

        self._calib_left: list[float] = []
        self._calib_right: list[float] = []
        self._calib_ankle_left: list[float] = []
        self._calib_ankle_right: list[float] = []

        self.baseline_left: Optional[float] = None
        self.baseline_right: Optional[float] = None
        self.baseline_ankle_left: Optional[float] = None
        self.baseline_ankle_right: Optional[float] = None

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _calibrated(self) -> bool:
        return (
            self.baseline_left is not None
            and self.baseline_right is not None
            and self.baseline_ankle_left is not None
            and self.baseline_ankle_right is not None
        )

    def _normalize_lift(
        self, current_y: float, baseline_y: float, shin_length: float
    ) -> float:
        return (baseline_y - current_y) / max(shin_length, 1e-6)

    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "position_ok": False,
            "position_message": None,
            "ready": self.ready,
            "calibrated": self._calibrated(),
            "lift": None,
            "smoothed_lift": None,
            "left_lift": None,
            "right_lift": None,
            "knee_angle": None,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_duration": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None:
            response["feedback"] = "No person detected — step into frame."
            return response

        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]
        l_heel, r_heel = landmarks[LEFT_HEEL], landmarks[RIGHT_HEEL]
        l_toe, r_toe = landmarks[LEFT_FOOT_INDEX], landmarks[RIGHT_FOOT_INDEX]

        # Only require lower body landmarks (Hips, Knees, Ankles)
        legs_visible = _visible((l_hip, r_hip, l_knee, r_knee, l_ankle, r_ankle))

        if not legs_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see lower body clearly — adjust camera so your hips, "
                "knees, and ankles are in frame."
            )
            return response

        response["pose_detected"] = True

        mid_hip = _midpoint(l_hip, r_hip)
        shin_left = _dist(l_knee, l_ankle)
        shin_right = _dist(r_knee, r_ankle)
        shin_length = max((shin_left + shin_right) / 2.0, 1e-6)

        bbox_points = [
            _Point(p.x, p.y)
            for p in (
                l_hip,
                r_hip,
                l_knee,
                r_knee,
                l_ankle,
                r_ankle,
                l_heel,
                r_heel,
                l_toe,
                r_toe,
            )
        ]
        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        left_knee_angle = _angle_deg(l_hip, l_knee, l_ankle)
        right_knee_angle = _angle_deg(r_hip, r_knee, r_ankle)
        knee_angle = (left_knee_angle + right_knee_angle) / 2.0

        # Leg-Only Standing Check (based purely on knee extension angle)
        is_standing = (
            left_knee_angle >= KNEE_STRAIGHT_MIN_DEG
            and right_knee_angle >= KNEE_STRAIGHT_MIN_DEG
        )

        if is_standing:
            self._standing_streak += 1
            self._bad_streak = 0
        else:
            self._standing_streak = 0
            self._bad_streak += 1

        if self._standing_streak >= STABLE_STANDING_FRAMES:
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES:
            self.ready = False
            self._calib_left.clear()
            self._calib_right.clear()
            self._calib_ankle_left.clear()
            self._calib_ankle_right.clear()

        response["position_ok"] = self.ready
        response["ready"] = self.ready
        response["knee_angle"] = knee_angle

        if not self.ready:
            response["position_message"] = (
                "Stand up straight with your legs nearly extended and feet flat "
                "facing the camera."
            )

        feet_visible = _visible(
            (l_heel, r_heel, l_toe, r_toe), min_vis=MIN_FOOT_VISIBILITY
        )

        left_lift_raw = 0.0
        right_lift_raw = 0.0
        if feet_visible:
            if l_heel is not None and l_toe is not None:
                left_lift_raw = (l_toe.y - l_heel.y) / max(shin_length, 1e-6)
            if r_heel is not None and r_toe is not None:
                right_lift_raw = (r_toe.y - r_heel.y) / max(shin_length, 1e-6)

        if self.ready and not self._calibrated():
            self._calib_left.append(left_lift_raw)
            self._calib_right.append(right_lift_raw)
            self._calib_ankle_left.append(l_ankle.y)
            self._calib_ankle_right.append(r_ankle.y)

            if len(self._calib_ankle_left) >= CALIBRATION_FRAMES:
                self.baseline_left = sum(self._calib_left) / len(self._calib_left)
                self.baseline_right = sum(self._calib_right) / len(self._calib_right)
                self.baseline_ankle_left = sum(self._calib_ankle_left) / len(
                    self._calib_ankle_left
                )
                self.baseline_ankle_right = sum(self._calib_ankle_right) / len(
                    self._calib_ankle_right
                )

        response["calibrated"] = self._calibrated()

        feedback = framing_message
        if not self.ready:
            feedback = feedback or response["position_message"]
            self.last_lift = None
            self.last_timestamp_s = t
            response["feedback"] = feedback or "Good form — keep going."
            return response

        if not self._calibrated():
            response["feedback"] = (
                feedback
                or "Hold still for a moment with your heels flat so we can calibrate your baseline..."
            )
            self.last_timestamp_s = t
            return response

        left_lift = self._normalize_lift(
            l_ankle.y, self.baseline_ankle_left, shin_length
        )
        right_lift = self._normalize_lift(
            r_ankle.y, self.baseline_ankle_right, shin_length
        )

        if self.smoothed_lift is None:
            self.smoothed_lift = (left_lift + right_lift) / 2.0
        else:
            raw_lift = (left_lift + right_lift) / 2.0
            self.smoothed_lift = (
                self.lift_smooth_alpha * raw_lift
                + (1 - self.lift_smooth_alpha) * self.smoothed_lift
            )

        raw_lift = (left_lift + right_lift) / 2.0

        response["left_lift"] = left_lift
        response["right_lift"] = right_lift
        response["lift"] = raw_lift
        response["smoothed_lift"] = self.smoothed_lift

        hip_rise = None
        if self._rep_hip_start_y is not None:
            hip_rise = (self._rep_hip_start_y - mid_hip.y) / shin_length

        rep_completed = False
        rep_duration = rep_class = rep_form_quality = None

        if self.stage == "down":
            self._rep_left_peak = max(self._rep_left_peak, left_lift)
            self._rep_right_peak = max(self._rep_right_peak, right_lift)

            if self.smoothed_lift > UP_LIFT:
                self.stage = "up"
                self.rep_start_time = t
                self._rep_hip_start_y = mid_hip.y
                self._rep_min_knee_angle = knee_angle
                self._current_rep_issues = set()
                self._rep_left_peak = left_lift
                self._rep_right_peak = right_lift
        else:
            self._rep_left_peak = max(self._rep_left_peak, left_lift)
            self._rep_right_peak = max(self._rep_right_peak, right_lift)

            if self._rep_min_knee_angle is not None:
                self._rep_min_knee_angle = min(self._rep_min_knee_angle, knee_angle)

            if knee_angle < KNEE_HARD_BEND_DEG:
                self._current_rep_issues.add("bent_knees")
            elif knee_angle < KNEE_STRAIGHT_MIN_DEG:
                self._current_rep_issues.add("slight_knee_bend")

            if hip_rise is not None and hip_rise > HIP_RISE_JUMP_RATIO:
                self._current_rep_issues.add("jumping")

            if self.smoothed_lift < DOWN_LIFT:
                self.stage = "down"
                rep_completed = True

        if rep_completed:
            rep_duration = (
                (t - self.rep_start_time) if self.rep_start_time is not None else None
            )
            lift_delta = min(self._rep_left_peak, self._rep_right_peak)
            both_feet_moved = (
                self._rep_left_peak >= MIN_PER_FOOT_LIFT
                and self._rep_right_peak >= MIN_PER_FOOT_LIFT
            )

            valid = (
                rep_duration is not None
                and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                and lift_delta >= MIN_LIFT_DELTA
                and both_feet_moved
                and "bent_knees" not in self._current_rep_issues
                and "jumping" not in self._current_rep_issues
            )

            if valid:
                self.rep_count += 1
                if rep_duration < 0.6:
                    rep_class = "fast"
                elif rep_duration <= 1.8:
                    rep_class = "good"
                else:
                    rep_class = "slow"

                if self._current_rep_issues:
                    rep_form_quality = "needs_improvement"
                    self.flawed_reps += 1
                    issue_text = ", ".join(
                        i.replace("_", " ") for i in sorted(self._current_rep_issues)
                    )
                    feedback = f"Rep {self.rep_count} counted, but watch your form ({issue_text})."
                else:
                    rep_form_quality = "good"
                    self.good_reps += 1
                    feedback = f"Clean rep — full heel raise ({rep_duration:.2f}s)."
            else:
                rep_completed = False
                if not both_feet_moved:
                    feedback = "Only one foot really lifted — raise both heels evenly."
                elif "bent_knees" in self._current_rep_issues:
                    feedback = (
                        "Keep legs straight — calf raises require non-bent knees."
                    )
                elif "jumping" in self._current_rep_issues:
                    feedback = "Controlled extension only — do not jump."
                elif rep_duration is not None and rep_duration < MIN_REP_DURATION:
                    feedback = "Too fast — control the movement."
                elif rep_duration is not None and rep_duration > MAX_REP_DURATION:
                    feedback = "Movement too slow — keep a steady rhythm."
                else:
                    feedback = "Not enough heel lift — rise higher onto your toes."

            self.rep_start_time = None
            self._rep_hip_start_y = None
            self._rep_min_knee_angle = None
            self._current_rep_issues = set()
            self._rep_left_peak = 0.0
            self._rep_right_peak = 0.0

        self.last_lift = self.smoothed_lift
        self.last_timestamp_s = t

        response.update(
            {
                "stage": self.stage,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_duration": rep_duration,
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "feedback": feedback or "Good form — keep going.",
            }
        )
        return response


class CalfRaiseSession:
    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = CalfRaiseAnalyzer(target_reps)
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
