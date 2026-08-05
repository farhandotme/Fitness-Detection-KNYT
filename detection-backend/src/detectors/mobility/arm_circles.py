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

MIN_LANDMARK_VISIBILITY = 0.4

SMOOTH_ALPHA = 0.5
MAX_STEP_DEG = 45.0
NOISE_FLOOR_DEG = 3.0
REVERSAL_TOLERANCE_DEG = 10.0
ROUND_DEG = 360.0

MIN_RADIUS_RATIO = 0.7
ELBOW_STRAIGHT_DEG = 150.0

FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.95
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


def _signed_delta_deg(new_angle: float, old_angle: float) -> float:
    return ((new_angle - old_angle + 180.0) % 360.0) - 180.0


def _framing_feedback(points) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — step back so both arms fit "
                "fully in the shot."
            )

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "You're too close to the camera — step back so both arms fit in frame."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class _ArmRotationTracker:
    def __init__(self):
        self.smoothed_dx: Optional[float] = None
        self.smoothed_dy: Optional[float] = None
        self.last_angle: Optional[float] = None
        self.direction: Optional[int] = None
        self.cumulative_deg = 0.0
        self.extended = False
        self.round_had_bend = False
        self.rounds = 0

    def update(
        self, dx: float, dy: float, extended: bool
    ) -> tuple[bool, Optional[str]]:
        if not extended:
            self.extended = False
            return False, None

        self.extended = True

        if self.smoothed_dx is None:
            self.smoothed_dx, self.smoothed_dy = dx, dy
        else:
            self.smoothed_dx = SMOOTH_ALPHA * dx + (1 - SMOOTH_ALPHA) * self.smoothed_dx
            self.smoothed_dy = SMOOTH_ALPHA * dy + (1 - SMOOTH_ALPHA) * self.smoothed_dy

        angle = math.degrees(math.atan2(self.smoothed_dy, self.smoothed_dx))

        if self.last_angle is None:
            self.last_angle = angle
            return False, None

        step = _signed_delta_deg(angle, self.last_angle)
        self.last_angle = angle

        if abs(step) > MAX_STEP_DEG:
            return False, None

        if abs(step) < NOISE_FLOOR_DEG:
            return False, None

        step_sign = 1 if step > 0 else -1

        if self.direction is None:
            self.direction = step_sign
            self.cumulative_deg = step
        elif step_sign == self.direction:
            self.cumulative_deg += step
        else:
            if abs(step) <= REVERSAL_TOLERANCE_DEG:
                self.cumulative_deg += step
            else:
                self.direction = step_sign
                self.cumulative_deg = step
                self.round_had_bend = False

        completed = False
        if abs(self.cumulative_deg) >= ROUND_DEG:
            completed = True
            self.rounds += 1
            self.cumulative_deg -= ROUND_DEG * self.direction

        return completed, ("forward" if self.direction == 1 else "backward")

    def mark_bend(self):
        self.round_had_bend = True

    def consume_bend_flag(self) -> bool:
        had = self.round_had_bend
        self.round_had_bend = False
        return had


class ArmCirclesAnalyzer:
    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps
        self.left = _ArmRotationTracker()
        self.right = _ArmRotationTracker()

        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        self.session_start_time: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "framing_ok": True,
            "framing_message": None,
            "left_arm_extended": False,
            "right_arm_extended": False,
            "left_elbow_angle": None,
            "right_elbow_angle": None,
            "left_direction": None,
            "right_direction": None,
            "left_arm_rounds": self.left.rounds,
            "right_arm_rounds": self.right.rounds,
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

        left_arm_ok = _visible((l_shoulder, l_elbow, l_wrist))
        right_arm_ok = _visible((r_shoulder, r_elbow, r_wrist))
        torso_ok = _visible((l_shoulder, r_shoulder, l_hip, r_hip))

        if not torso_ok or (not left_arm_ok and not right_arm_ok):
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see you clearly — stand facing the camera with both "
                "shoulders and arms visible."
            )
            return response

        response["pose_detected"] = True

        shoulder_width = max(_dist(l_shoulder, r_shoulder), 1e-6)

        bbox_points = [
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
        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        feedback = framing_message
        rep_completed = False
        quality = None

        if framing_message is None:
            if left_arm_ok:
                left_elbow_angle = _angle_deg(l_shoulder, l_elbow, l_wrist)
                response["left_elbow_angle"] = round(left_elbow_angle, 1)
                left_radius = _dist(l_shoulder, l_wrist) / shoulder_width
                left_extended = left_radius >= MIN_RADIUS_RATIO
                response["left_arm_extended"] = left_extended

                if left_extended and left_elbow_angle < ELBOW_STRAIGHT_DEG:
                    self.left.mark_bend()

                left_completed, left_dir = self.left.update(
                    l_wrist.x - l_shoulder.x, l_wrist.y - l_shoulder.y, left_extended
                )
                response["left_direction"] = left_dir

                if left_completed:
                    self.left.consume_bend_flag()
                    self.rep_count += 1
                    self.left.rounds = max(self.left.rounds, self.rep_count)
                    rep_completed = True
                    quality = (
                        "good" if not self.left.round_had_bend else "needs_improvement"
                    )
                    if self.left.consume_bend_flag():
                        self.flawed_reps += 1
                    else:
                        self.good_reps += 1

            if right_arm_ok:
                right_elbow_angle = _angle_deg(r_shoulder, r_elbow, r_wrist)
                response["right_elbow_angle"] = round(right_elbow_angle, 1)
                right_radius = _dist(r_shoulder, r_wrist) / shoulder_width
                right_extended = right_radius >= MIN_RADIUS_RATIO
                response["right_arm_extended"] = right_extended

                if right_extended and right_elbow_angle < ELBOW_STRAIGHT_DEG:
                    self.right.mark_bend()

                right_completed, right_dir = self.right.update(
                    r_wrist.x - r_shoulder.x, r_wrist.y - r_shoulder.y, right_extended
                )
                response["right_direction"] = right_dir

                if right_completed:
                    flawed = self.right.consume_bend_flag()
                    self.rep_count += 1
                    rep_completed = True
                    quality = "needs_improvement" if flawed else "good"
                    if flawed:
                        self.flawed_reps += 1
                    else:
                        self.good_reps += 1

        response["left_arm_rounds"] = self.left.rounds
        response["right_arm_rounds"] = self.right.rounds
        response["rep_count"] = self.rep_count
        response["session_complete"] = self._is_complete()
        response["rep_completed"] = rep_completed
        response["rep_form_quality"] = quality
        response["feedback"] = feedback or (
            "Keep circling — each arm counts when it completes a full round."
        )

        self.last_timestamp_s = t
        return response


class ArmCirclesSession:
    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = ArmCirclesAnalyzer(target_reps)
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
