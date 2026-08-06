"""
Dumbbell Pullover detector.

Movement contract
-----------------
The user lies on their back in a side or three-quarter view:

    setup -> dumbbell over chest -> lower behind head -> return over chest

The position gate runs before the rep state machine. A rep cannot count until
the detector has confirmed a mostly horizontal torso, both shoulders/hips, and
both arms. The user must also bring the weight over the chest once before the
first lowering phase, which prevents a session that starts behind the head from
being counted accidentally.
"""

import math
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

MIN_VISIBILITY = 0.30
PERSON_VISIBILITY = 0.52
ARM_VISIBILITY = 0.26
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)

# The torso axis is measured from the hip midpoint toward the shoulder
# midpoint. A supine user has that axis close to horizontal in the image.
MIN_SUPINE_INCLINE_DEG = 52.0

# Shoulder flexion is measured as the angle between shoulder->hip and
# shoulder->wrist. Over-chest is roughly perpendicular to the torso; behind
# the head is close to the torso axis. The vertical check below separates a
# true over-chest position from simply dropping the arms toward the floor.
CHEST_ENTER_DEG = 130.0
CHEST_MIN_DEG = 48.0
HEAD_ENTER_DEG = 148.0
MIN_TRAVEL_DEG = 22.0
MIN_ELBOW_EXTENSION_DEG = 122.0
ANGLE_SMOOTH_ALPHA = 0.58

POSITION_CONFIRM_FRAMES = 4
POSITION_GRACE_FRAMES = 5
CHEST_CONFIRM_FRAMES = 2
HEAD_CONFIRM_FRAMES = 2
MIN_REP_DURATION = 0.35
MAX_REP_DURATION = 10.0
FRAME_EDGE_MARGIN = 0.035


def _visible(points: tuple[Any, ...], threshold: float = MIN_VISIBILITY) -> bool:
    return all(
        point is not None
        and (
            getattr(point, "visibility", None) is None
            or getattr(point, "visibility", 0.0) >= threshold
        )
        for point in points
    )


def _looks_like_person(landmarks: list[Any]) -> bool:
    if len(landmarks) < 33:
        return False
    visible_core = sum(
        1
        for index in CORE_LANDMARKS
        if getattr(landmarks[index], "visibility", 0.0) >= PERSON_VISIBILITY
    )
    return visible_core >= 3


def _distance(a: Any, b: Any) -> float:
    return math.hypot(float(a.x) - float(b.x), float(a.y) - float(b.y))


def _midpoint(a: Any, b: Any) -> tuple[float, float]:
    return ((float(a.x) + float(b.x)) / 2.0, (float(a.y) + float(b.y)) / 2.0)


def _angle_at(a: Any, b: Any, c: Any) -> Optional[float]:
    """Angle at b between b->a and b->c, in degrees."""
    first = (float(a.x) - float(b.x), float(a.y) - float(b.y))
    second = (float(c.x) - float(b.x), float(c.y) - float(b.y))
    first_len = math.hypot(*first)
    second_len = math.hypot(*second)
    if first_len < 1e-7 or second_len < 1e-7:
        return None
    cosine = (first[0] * second[0] + first[1] * second[1]) / (first_len * second_len)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _torso_incline_deg(
    shoulder: tuple[float, float], hip: tuple[float, float]
) -> float:
    """0° is upright; 90° is horizontal."""
    dx = hip[0] - shoulder[0]
    dy = hip[1] - shoulder[1]
    return math.degrees(math.atan2(abs(dx), max(abs(dy), 1e-7)))


def _view_mode(shoulder_width: float, torso_length: float) -> str:
    ratio = shoulder_width / max(torso_length, 1e-7)
    if ratio >= 1.02:
        return "front"
    if ratio <= 0.56:
        return "side"
    return "angled"


def _framing_feedback(points: list[Any]) -> Optional[str]:
    for point in points:
        if point.x < FRAME_EDGE_MARGIN or point.x > 1.0 - FRAME_EDGE_MARGIN:
            return "Move back or turn the phone so both arms fit inside the frame."
        if point.y < FRAME_EDGE_MARGIN or point.y > 1.0 - FRAME_EDGE_MARGIN:
            return "Keep your shoulders, elbows, and wrists inside the frame."
    return None


def _tempo(duration: Optional[float]) -> Optional[str]:
    if duration is None:
        return None
    if duration < 0.35:
        return "too_fast"
    if duration < 0.80:
        return "fast"
    if duration < 2.20:
        return "good"
    if duration < 4.0:
        return "slow"
    return "too_slow"


class DumbbellPulloverAnalyzer:
    """Stateful supine pullover counter with an explicit setup confirmation."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.stage = "setup"
        self.ready = False
        self._position_good_streak = 0
        self._position_bad_streak = 0
        self._chest_streak = 0
        self._head_streak = 0
        self._seen_chest = False
        self._rep_start_time: Optional[float] = None
        self._rep_min_angle: Optional[float] = None
        self._smoothed_angle: Optional[float] = None
        self._last_angle: Optional[float] = None
        self._last_timestamp_s: Optional[float] = None
        self._angle_acc = 0.0
        self._issues: set[str] = set()
        self._session_start_time: Optional[float] = None

    def _complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _base_response(self, elapsed: float) -> dict[str, Any]:
        return {
            "pose_detected": False,
            "view_mode": None,
            "position_ok": False,
            "position_message": None,
            "ready": self.ready,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": self._complete(),
            "rep_completed": False,
            "rep_duration": None,
            "rep_avg_speed": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "angle": None,
            "smoothed_angle": None,
            "left_elbow_angle": None,
            "right_elbow_angle": None,
            "angle_velocity": None,
            "alignment_ok": False,
            "alignment_issue": None,
            "framing_ok": True,
            "framing_message": None,
            "torso_incline": None,
            "arm_path": None,
            "elbow_extension": None,
            "arms_extended": False,
            "chest_position": False,
            "behind_head_position": False,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

    def _finish_rep(
        self, response: dict[str, Any], timestamp_s: float, angle: float
    ) -> None:
        duration = (
            max(0.0, timestamp_s - self._rep_start_time)
            if self._rep_start_time is not None
            else None
        )
        travel = self._rep_min_angle - angle if self._rep_min_angle is not None else 0.0
        if duration is None or duration > MAX_REP_DURATION or travel < MIN_TRAVEL_DEG:
            self._issues.add("insufficient_range")
            self._reset_rep()
            return

        self.rep_count += 1
        response["rep_completed"] = True
        response["rep_duration"] = round(duration, 3)
        response["rep_avg_speed"] = (
            round(self._angle_acc / duration, 2) if duration else None
        )
        response["rep_classification"] = _tempo(duration)
        if duration < MIN_REP_DURATION:
            self._issues.add("rushed_rep")
        if duration > 4.0:
            self._issues.add("slow_rep")

        response["rep_form_quality"] = (
            "good" if not self._issues else "needs_improvement"
        )
        if response["rep_form_quality"] == "good":
            self.good_reps += 1
        else:
            self.flawed_reps += 1
        self._reset_rep()

    def _reset_rep(self) -> None:
        self._rep_start_time = None
        self._rep_min_angle = None
        self._angle_acc = 0.0
        self._issues = set()

    def update(
        self, landmarks: Optional[list[Any]], timestamp_ms: int
    ) -> dict[str, Any]:
        timestamp_s = timestamp_ms / 1000.0
        if self._session_start_time is None:
            self._session_start_time = timestamp_s
        elapsed = max(0.0, timestamp_s - self._session_start_time)
        response = self._base_response(elapsed)

        if landmarks is None or not _looks_like_person(landmarks):
            response["feedback"] = (
                "No person detected — lie on your back in a side or three-quarter view."
            )
            self._position_good_streak = 0
            self._position_bad_streak += 1
            if self._position_bad_streak >= POSITION_GRACE_FRAMES:
                self.ready = False
            return response

        left_shoulder = landmarks[LEFT_SHOULDER]
        right_shoulder = landmarks[RIGHT_SHOULDER]
        left_hip = landmarks[LEFT_HIP]
        right_hip = landmarks[RIGHT_HIP]
        left_elbow = landmarks[LEFT_ELBOW]
        right_elbow = landmarks[RIGHT_ELBOW]
        left_wrist = landmarks[LEFT_WRIST]
        right_wrist = landmarks[RIGHT_WRIST]

        mid_shoulder = _midpoint(left_shoulder, right_shoulder)
        mid_hip = _midpoint(left_hip, right_hip)
        torso_length = max(
            _distance(left_shoulder, left_hip), _distance(right_shoulder, right_hip)
        )
        shoulder_width = _distance(left_shoulder, right_shoulder)
        torso_incline = _torso_incline_deg(mid_shoulder, mid_hip)
        view_mode = _view_mode(shoulder_width, torso_length)
        response.update(
            {
                "pose_detected": True,
                "view_mode": view_mode,
                "torso_incline": round(torso_incline, 1),
            }
        )

        arm_points = (
            left_shoulder,
            left_elbow,
            left_wrist,
            right_shoulder,
            right_elbow,
            right_wrist,
        )
        arms_visible = _visible(arm_points, ARM_VISIBILITY)
        core_visible = _visible(
            (left_shoulder, right_shoulder, left_hip, right_hip),
            MIN_VISIBILITY,
        )
        framing_points = list(arm_points) + [
            left_shoulder,
            right_shoulder,
            left_hip,
            right_hip,
        ]
        framing_message = _framing_feedback(framing_points)
        framing_ok = framing_message is None
        supine_ok = torso_incline >= MIN_SUPINE_INCLINE_DEG
        view_ok = view_mode != "front"
        arm_angles = [
            angle
            for angle in (
                (
                    _angle_at(left_hip, left_shoulder, left_wrist)
                    if _visible((left_hip, left_shoulder, left_wrist), ARM_VISIBILITY)
                    else None
                ),
                (
                    _angle_at(right_hip, right_shoulder, right_wrist)
                    if _visible(
                        (right_hip, right_shoulder, right_wrist), ARM_VISIBILITY
                    )
                    else None
                ),
            )
            if angle is not None
        ]
        raw_angle = sum(arm_angles) / len(arm_angles) if arm_angles else None
        elbow_angles = [
            angle
            for angle in (
                (
                    _angle_at(left_shoulder, left_elbow, left_wrist)
                    if _visible((left_shoulder, left_elbow, left_wrist), ARM_VISIBILITY)
                    else None
                ),
                (
                    _angle_at(right_shoulder, right_elbow, right_wrist)
                    if _visible(
                        (right_shoulder, right_elbow, right_wrist), ARM_VISIBILITY
                    )
                    else None
                ),
            )
            if angle is not None
        ]
        elbow_extension = (
            sum(elbow_angles) / len(elbow_angles) if elbow_angles else None
        )
        arms_extended = (
            elbow_extension is not None and elbow_extension >= MIN_ELBOW_EXTENSION_DEG
        )
        position_now_ok = (
            core_visible
            and arms_visible
            and supine_ok
            and view_ok
            and framing_ok
            and arms_extended
        )

        if position_now_ok:
            self._position_good_streak += 1
            self._position_bad_streak = 0
        else:
            self._position_good_streak = 0
            self._position_bad_streak += 1
        if self._position_good_streak >= POSITION_CONFIRM_FRAMES:
            self.ready = True
        elif self._position_bad_streak >= POSITION_GRACE_FRAMES:
            self.ready = False
        current_angle = raw_angle
        if raw_angle is not None:
            self._smoothed_angle = (
                raw_angle
                if self._smoothed_angle is None
                else ANGLE_SMOOTH_ALPHA * raw_angle
                + (1.0 - ANGLE_SMOOTH_ALPHA) * self._smoothed_angle
            )
            current_angle = self._smoothed_angle

        angle_velocity = None
        if (
            current_angle is not None
            and self._last_angle is not None
            and self._last_timestamp_s is not None
        ):
            dt = max(timestamp_s - self._last_timestamp_s, 1e-6)
            angle_velocity = (current_angle - self._last_angle) / dt

        wrists_above_shoulders = (
            left_wrist.y <= left_shoulder.y + 0.08
            and right_wrist.y <= right_shoulder.y + 0.08
        )
        chest_now = bool(
            current_angle is not None
            and CHEST_MIN_DEG <= current_angle <= CHEST_ENTER_DEG
            and wrists_above_shoulders
            and arms_extended
        )
        head_now = bool(current_angle is not None and current_angle >= HEAD_ENTER_DEG)
        self._chest_streak = self._chest_streak + 1 if chest_now else 0
        self._head_streak = self._head_streak + 1 if head_now else 0
        chest_confirmed = self._chest_streak >= CHEST_CONFIRM_FRAMES
        head_confirmed = self._head_streak >= HEAD_CONFIRM_FRAMES

        position_message: Optional[str] = None
        if not core_visible:
            position_message = "Keep both shoulders and both hips visible so I can confirm you are lying flat."
        elif not arms_visible:
            position_message = (
                "Extend both arms and keep both elbows and wrists visible."
            )
        elif not supine_ok:
            position_message = (
                "Lie flat on your back with your shoulders and hips nearly level."
            )
        elif not view_ok:
            position_message = (
                "Turn to a side or three-quarter view so the arm path is visible."
            )
        elif not framing_ok:
            position_message = framing_message
        elif not arms_extended:
            position_message = "Keep both elbows softly straight — do not bend them as you move the dumbbell."
        elif not self.ready:
            position_message = "Hold still for a moment while I confirm your position."

        position_ok = self.ready and position_now_ok
        response.update(
            {
                "position_ok": position_ok,
                "position_message": position_message,
                "ready": self.ready,
                "angle": round(raw_angle, 1) if raw_angle is not None else None,
                "smoothed_angle": (
                    round(current_angle, 1) if current_angle is not None else None
                ),
                "left_elbow_angle": None,
                "right_elbow_angle": None,
                "angle_velocity": (
                    round(angle_velocity, 2) if angle_velocity is not None else None
                ),
                "elbow_extension": (
                    round(elbow_extension, 1) if elbow_extension is not None else None
                ),
                "arms_extended": arms_extended,
                "chest_position": chest_confirmed,
                "behind_head_position": head_confirmed,
                "framing_ok": framing_ok,
                "framing_message": framing_message,
                "alignment_ok": position_ok,
                "alignment_issue": position_message,
            }
        )

        if position_ok and current_angle is not None:
            if chest_confirmed:
                self._seen_chest = True
                if self.stage == "lowered":
                    self.stage = "chest"
                    self._finish_rep(response, timestamp_s, current_angle)
                elif self.stage in ("setup", "chest"):
                    self.stage = "chest"
            elif head_confirmed and self._seen_chest:
                if self.stage == "chest":
                    self.stage = "lowered"
                    self._rep_start_time = timestamp_s
                    self._rep_min_angle = current_angle
                    self._angle_acc = 0.0
                    self._issues = set()
                elif self.stage == "lowered":
                    self._rep_min_angle = max(
                        self._rep_min_angle or current_angle, current_angle
                    )

            if self.stage == "lowered" and self._last_angle is not None:
                self._angle_acc += abs(current_angle - self._last_angle)
                if self._rep_min_angle is None or current_angle > self._rep_min_angle:
                    self._rep_min_angle = current_angle

        if response["rep_completed"]:
            response["feedback"] = (
                f"Rep {self.rep_count} counted — bring the dumbbell over your chest with control."
            )
        elif position_message:
            response["feedback"] = position_message
        elif not self._seen_chest:
            response["feedback"] = (
                "Position confirmed — bring the dumbbell over your chest to start."
            )
        elif self.stage == "chest":
            response["feedback"] = "Ready — lower the dumbbell slowly behind your head."
        elif self.stage == "lowered":
            response["feedback"] = (
                "Good stretch — pull the dumbbell back over your chest without bending your elbows."
            )
        elif self._complete():
            response["feedback"] = (
                f"Target reached — {self.target_reps} dumbbell pullovers completed."
            )
        else:
            response["feedback"] = "Keep the movement slow and controlled."

        response.update(
            {
                "stage": self.stage,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._complete(),
                "arm_path": (
                    round(current_angle, 1) if current_angle is not None else None
                ),
            }
        )
        self._last_angle = current_angle
        self._last_timestamp_s = timestamp_s
        return response


class DumbbellPulloverSession:
    """Standalone detector session using one shared PoseEngine."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = DumbbellPulloverAnalyzer(target_reps)
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
