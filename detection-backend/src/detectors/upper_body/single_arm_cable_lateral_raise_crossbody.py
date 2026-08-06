"""
Single Arm Cable Lateral Raise (Crossbody) detector.

The exercise-specific cable path is intentionally not used as a hard gate.
Pose landmarks cannot reliably prove where the cable handle starts, so the
detector focuses on the user-visible movement:

    arm low -> arm rises to shoulder height -> arm comes back down

Either arm can work independently. The other arm may be on the hip, outside
the frame, or simply not moving.
"""

import math
from dataclasses import dataclass
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_SHOULDER,
    LEFT_WRIST,
    PoseEngine,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)

MIN_LANDMARK_VISIBILITY = 0.40
PERSON_VISIBILITY = 0.55

CORE_LANDMARKS = (
    LEFT_SHOULDER,
    RIGHT_SHOULDER,
    LEFT_HIP,
    RIGHT_HIP,
)

# Elevation is measured from the downward vertical between shoulder and wrist.
# These thresholds deliberately favor detecting the rise over enforcing a
# perfect lateral-raise shape.
DOWN_ENTER_DEG = 42.0
TOP_ENTER_DEG = 46.0
MIN_RISE_TRAVEL_DEG = 18.0
TOP_WRIST_Y_TOLERANCE = 0.28

ELEVATION_SMOOTH_ALPHA = 0.72
TOP_CONFIRM_FRAMES = 2
DOWN_CONFIRM_FRAMES = 2
MIN_REP_DURATION = 0.20
MAX_REP_DURATION = 8.0

FRAME_EDGE_MARGIN = 0.02


@dataclass
class _ArmState:
    name: str
    rep_count: int = 0
    good_reps: int = 0
    flawed_reps: int = 0
    stage: str = "down"
    seen_down: bool = False
    smoothed_elevation: Optional[float] = None
    last_elevation: Optional[float] = None
    rep_start_time: Optional[float] = None
    rep_peak_elevation: Optional[float] = None
    rep_angle_acc: float = 0.0
    top_streak: int = 0
    down_streak: int = 0

    def reset_motion(self) -> None:
        self.rep_start_time = None
        self.rep_peak_elevation = None
        self.rep_angle_acc = 0.0
        self.top_streak = 0
        self.down_streak = 0


def _visible(
    points: tuple[Any, ...],
    threshold: float = MIN_LANDMARK_VISIBILITY,
) -> bool:
    return all(
        point is not None
        and (
            getattr(point, "visibility", None) is None
            or getattr(point, "visibility", 0.0) >= threshold
        )
        for point in points
    )


def _looks_like_a_person(landmarks: list[Any]) -> bool:
    if len(landmarks) < 33:
        return False
    visible_core = sum(
        1
        for index in CORE_LANDMARKS
        if getattr(landmarks[index], "visibility", None) is not None
        and landmarks[index].visibility >= PERSON_VISIBILITY
    )
    return visible_core >= 2


def _xyz(point: Any) -> tuple[float, float, float]:
    if isinstance(point, (tuple, list)) and len(point) >= 3:
        return float(point[0]), float(point[1]), float(point[2])
    return (
        float(getattr(point, "x", 0.0)),
        float(getattr(point, "y", 0.0)),
        float(getattr(point, "z", 0.0) or 0.0),
    )


def _distance(a: Any, b: Any) -> float:
    ax, ay, az = _xyz(a)
    bx, by, bz = _xyz(b)
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2)


def _arm_elevation_deg(shoulder: Any, wrist: Any) -> Optional[float]:
    """0° is down; 90° is approximately shoulder height."""
    sx, sy, _ = _xyz(shoulder)
    wx, wy, _ = _xyz(wrist)
    dx = wx - sx
    dy = wy - sy
    length = math.hypot(dx, dy)
    if length < 1e-8:
        return None
    return math.degrees(math.acos(max(-1.0, min(1.0, dy / length))))


def _angle_at(a: Any, b: Any, c: Any) -> Optional[float]:
    ax, ay, az = _xyz(a)
    bx, by, bz = _xyz(b)
    cx, cy, cz = _xyz(c)
    first = (ax - bx, ay - by, az - bz)
    second = (cx - bx, cy - by, cz - bz)
    first_length = math.sqrt(sum(value * value for value in first))
    second_length = math.sqrt(sum(value * value for value in second))
    if first_length < 1e-8 or second_length < 1e-8:
        return None
    cosine = sum(first[i] * second[i] for i in range(3)) / (
        first_length * second_length
    )
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _framing_feedback(points: list[Any]) -> Optional[str]:
    for point in points:
        if point is None:
            continue
        if (
            point.x < FRAME_EDGE_MARGIN
            or point.x > 1.0 - FRAME_EDGE_MARGIN
            or point.y < FRAME_EDGE_MARGIN
            or point.y > 1.0 - FRAME_EDGE_MARGIN
        ):
            return "Keep the working shoulder, elbow, and wrist inside the frame."
    return None


class SingleArmCableLateralRaiseCrossbodyAnalyzer:
    """Counts a clear upward and downward movement on either arm."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps
        self.left = _ArmState("left")
        self.right = _ArmState("right")
        self.stage = "down"
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.session_start_time: Optional[float] = None

    def _complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    @staticmethod
    def _tempo(duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration < 0.25:
            return "too_fast"
        if duration < 0.70:
            return "fast"
        if duration < 1.80:
            return "good"
        if duration < 3.50:
            return "slow"
        return "too_slow"

    def _base_response(self, elapsed: float) -> dict[str, Any]:
        return {
            "pose_detected": False,
            "view_mode": "front",
            "position_ok": False,
            "position_message": None,
            "ready": False,
            "stage": self.stage,
            "active_side": None,
            "rep_count": self.rep_count,
            "left_rep_count": self.left.rep_count,
            "right_rep_count": self.right.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "left_good_reps": self.left.good_reps,
            "right_good_reps": self.right.good_reps,
            "left_flawed_reps": self.left.flawed_reps,
            "right_flawed_reps": self.right.flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": self._complete(),
            "rep_completed": False,
            "rep_arms": [],
            "rep_side": None,
            "rep_duration": None,
            "rep_avg_speed": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "left_elevation_angle": None,
            "right_elevation_angle": None,
            "left_smoothed_elevation": None,
            "right_smoothed_elevation": None,
            "left_elbow_angle": None,
            "right_elbow_angle": None,
            "left_rising": False,
            "right_rising": False,
            "left_top_reached": False,
            "right_top_reached": False,
            "top_reached": False,
            "crossbody_ready": False,
            "standing": True,
            "torso_lean_angle": None,
            "left_arm_visible": False,
            "right_arm_visible": False,
            "framing_ok": True,
            "framing_message": None,
            "alignment_ok": True,
            "alignment_issue": None,
            "feedback": None,
            "low_visibility": False,
            "equipment_note": "Counting is based on the visible arm rise; cable position is not required.",
            "elapsed_time": round(elapsed, 2),
        }

    def _finish_at_top(
        self,
        arm: _ArmState,
        timestamp_s: float,
        elbow_angle: Optional[float],
    ) -> dict[str, Any]:
        duration = (
            max(0.0, timestamp_s - arm.rep_start_time)
            if arm.rep_start_time is not None
            else 0.0
        )
        issues: set[str] = set()
        if duration < MIN_REP_DURATION:
            issues.add("rushed_rep")
        if duration > MAX_REP_DURATION:
            issues.add("too_slow")
        if elbow_angle is not None and elbow_angle < 95.0:
            issues.add("bent_elbow")
        quality = "good" if not issues else "needs_improvement"

        arm.rep_count += 1
        if quality == "good":
            arm.good_reps += 1
        else:
            arm.flawed_reps += 1

        event = {
            "arm": arm.name,
            "duration": duration,
            "avg_speed": arm.rep_angle_acc / duration if duration > 0 else None,
            "classification": self._tempo(duration),
            "quality": quality,
        }
        arm.stage = "raised"
        arm.reset_motion()
        return event

    def _update_arm(
        self,
        arm: _ArmState,
        shoulder: Any,
        elbow: Any,
        wrist: Any,
        timestamp_s: float,
    ) -> Optional[dict[str, Any]]:
        elevation = _arm_elevation_deg(shoulder, wrist)
        if elevation is None:
            return None
        arm.smoothed_elevation = (
            elevation
            if arm.smoothed_elevation is None
            else ELEVATION_SMOOTH_ALPHA * elevation
            + (1.0 - ELEVATION_SMOOTH_ALPHA) * arm.smoothed_elevation
        )
        current = arm.smoothed_elevation
        _, shoulder_y, _ = _xyz(shoulder)
        _, wrist_y, _ = _xyz(wrist)

        # Use either signal for the low position. This is intentionally broad:
        # crossbody, beside-the-leg, or a slightly bent start are all valid.
        is_down = current <= DOWN_ENTER_DEG or wrist_y >= shoulder_y + 0.10
        is_top = (
            current >= TOP_ENTER_DEG and wrist_y <= shoulder_y + TOP_WRIST_Y_TOLERANCE
        )

        if is_down:
            arm.seen_down = True
            arm.down_streak += 1
            arm.top_streak = 0
        else:
            arm.down_streak = 0

        if is_top and arm.seen_down and arm.stage == "down":
            arm.top_streak += 1
        else:
            if not is_top:
                arm.top_streak = 0

        event = None
        if arm.top_streak >= TOP_CONFIRM_FRAMES and arm.stage == "down":
            arm.rep_start_time = timestamp_s
            arm.rep_peak_elevation = current
            arm.rep_angle_acc = 0.0
            arm.last_elevation = current
            elbow_angle = _angle_at(shoulder, elbow, wrist)
            event = self._finish_at_top(arm, timestamp_s, elbow_angle)

        # After counting at the top, remain locked until this same arm comes
        # back down. This prevents repeated counts from held raised poses.
        if arm.stage == "raised":
            if arm.rep_peak_elevation is None or current > arm.rep_peak_elevation:
                arm.rep_peak_elevation = current
            if arm.last_elevation is not None:
                arm.rep_angle_acc += abs(current - arm.last_elevation)
            if is_down and arm.down_streak >= DOWN_CONFIRM_FRAMES:
                arm.stage = "down"
                arm.seen_down = True
                arm.reset_motion()
        arm.last_elevation = current
        return event

    def update(
        self, landmarks: Optional[list[Any]], timestamp_ms: int
    ) -> dict[str, Any]:
        timestamp_s = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = timestamp_s
        elapsed = max(0.0, timestamp_s - self.session_start_time)
        response = self._base_response(elapsed)

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = (
                "No person detected — keep one arm and shoulder in view."
            )
            return response

        left_shoulder = landmarks[LEFT_SHOULDER]
        right_shoulder = landmarks[RIGHT_SHOULDER]
        left_hip = landmarks[LEFT_HIP]
        right_hip = landmarks[RIGHT_HIP]
        left_elbow = landmarks[LEFT_ELBOW]
        right_elbow = landmarks[RIGHT_ELBOW]
        left_wrist = landmarks[LEFT_WRIST]
        right_wrist = landmarks[RIGHT_WRIST]

        left_visible = _visible((left_shoulder, left_elbow, left_wrist))
        right_visible = _visible((right_shoulder, right_elbow, right_wrist))
        response["pose_detected"] = True
        response["left_arm_visible"] = left_visible
        response["right_arm_visible"] = right_visible
        response["low_visibility"] = not (left_visible or right_visible)
        if not (left_visible or right_visible):
            response["feedback"] = (
                "Keep at least one shoulder, elbow, and wrist visible."
            )
            return response

        framing_points = []
        if left_visible:
            framing_points.extend((left_shoulder, left_elbow, left_wrist))
        if right_visible:
            framing_points.extend((right_shoulder, right_elbow, right_wrist))
        framing_message = _framing_feedback(framing_points)
        framing_ok = framing_message is None

        events: list[dict[str, Any]] = []
        if left_visible:
            event = self._update_arm(
                self.left,
                left_shoulder,
                left_elbow,
                left_wrist,
                timestamp_s,
            )
            if event:
                events.append(event)
        if right_visible:
            event = self._update_arm(
                self.right,
                right_shoulder,
                right_elbow,
                right_wrist,
                timestamp_s,
            )
            if event:
                events.append(event)

        # Each completed arm rise is one rep. A single-arm exercise should not
        # lose a rep when the user changes sides during the same session.
        self.rep_count = self.left.rep_count + self.right.rep_count
        self.good_reps = self.left.good_reps + self.right.good_reps
        self.flawed_reps = self.left.flawed_reps + self.right.flawed_reps

        if self.left.stage == "raised" and self.right.stage == "raised":
            self.stage = "raised"
        elif self.left.stage == "raised":
            self.stage = "left_raised"
        elif self.right.stage == "raised":
            self.stage = "right_raised"
        else:
            self.stage = "down"
        active_side = (
            "left"
            if self.left.stage == "raised"
            else "right" if self.right.stage == "raised" else None
        )

        left_angle = (
            _arm_elevation_deg(left_shoulder, left_wrist) if left_visible else None
        )
        right_angle = (
            _arm_elevation_deg(right_shoulder, right_wrist) if right_visible else None
        )
        left_elbow_angle = (
            _angle_at(left_shoulder, left_elbow, left_wrist) if left_visible else None
        )
        right_elbow_angle = (
            _angle_at(right_shoulder, right_elbow, right_wrist)
            if right_visible
            else None
        )
        left_smoothed = self.left.smoothed_elevation
        right_smoothed = self.right.smoothed_elevation

        left_rising = (
            left_smoothed is not None
            and left_smoothed > DOWN_ENTER_DEG
            and self.left.stage == "down"
        )
        right_rising = (
            right_smoothed is not None
            and right_smoothed > DOWN_ENTER_DEG
            and self.right.stage == "down"
        )
        left_top = left_smoothed is not None and left_smoothed >= TOP_ENTER_DEG
        right_top = right_smoothed is not None and right_smoothed >= TOP_ENTER_DEG

        if events:
            first = events[0]
            response.update(
                {
                    "rep_completed": True,
                    "rep_arms": [event["arm"] for event in events],
                    "rep_side": first["arm"],
                    "rep_duration": round(first["duration"], 3),
                    "rep_avg_speed": (
                        round(first["avg_speed"], 2)
                        if first["avg_speed"] is not None
                        else None
                    ),
                    "rep_classification": first["classification"],
                    "rep_form_quality": (
                        "good"
                        if all(event["quality"] == "good" for event in events)
                        else "needs_improvement"
                    ),
                }
            )
            feedback = f"{first['arm'].capitalize()} arm counted — lower it to reset."
        elif active_side:
            feedback = f"Good {active_side} raise — lower that arm to reset."
        elif left_rising or right_rising:
            side = "left" if left_rising else "right"
            feedback = f"Keep raising your {side} arm to shoulder height."
        elif self._complete():
            feedback = f"Target reached — {self.target_reps} raises completed."
        else:
            feedback = "Raise either arm from low to shoulder height."

        response.update(
            {
                "position_ok": bool(left_visible or right_visible),
                "position_message": (
                    None
                    if (left_visible or right_visible)
                    else "Show one working arm clearly."
                ),
                "ready": bool(left_visible or right_visible),
                "active_side": active_side,
                "stage": self.stage,
                "rep_count": self.rep_count,
                "left_rep_count": self.left.rep_count,
                "right_rep_count": self.right.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "left_good_reps": self.left.good_reps,
                "right_good_reps": self.right.good_reps,
                "left_flawed_reps": self.left.flawed_reps,
                "right_flawed_reps": self.right.flawed_reps,
                "left_elevation_angle": (
                    round(left_angle, 1) if left_angle is not None else None
                ),
                "right_elevation_angle": (
                    round(right_angle, 1) if right_angle is not None else None
                ),
                "left_smoothed_elevation": (
                    round(left_smoothed, 1) if left_smoothed is not None else None
                ),
                "right_smoothed_elevation": (
                    round(right_smoothed, 1) if right_smoothed is not None else None
                ),
                "left_elbow_angle": (
                    round(left_elbow_angle, 1) if left_elbow_angle is not None else None
                ),
                "right_elbow_angle": (
                    round(right_elbow_angle, 1)
                    if right_elbow_angle is not None
                    else None
                ),
                "left_rising": left_rising,
                "right_rising": right_rising,
                "left_top_reached": left_top,
                "right_top_reached": right_top,
                "top_reached": left_top or right_top,
                "crossbody_ready": False,
                "standing": True,
                "framing_ok": framing_ok,
                "framing_message": framing_message,
                "alignment_ok": True,
                "alignment_issue": None,
                "feedback": feedback,
                "session_complete": self._complete(),
            }
        )
        return response


class SingleArmCableLateralRaiseCrossbodySession:
    """Session wrapper using one shared PoseEngine."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = SingleArmCableLateralRaiseCrossbodyAnalyzer(target_reps)
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
