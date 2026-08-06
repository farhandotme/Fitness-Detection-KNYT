"""
Standing trunk rotation detector.

Movement contract
-----------------
The user stands upright and rotates the torso to either side:

    neutral -> left/right rotation -> neutral

Each completed turn to one side counts as one repetition. The user may
alternate sides or repeat the same side. The detector uses the relative
horizontal depth orientation of the shoulder line versus the hip line, which
is available from the existing MediaPipe PoseEngine landmarks.
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

MIN_LANDMARK_VISIBILITY = 0.45
PERSON_VISIBILITY = 0.60

CORE_LANDMARKS = (
    LEFT_SHOULDER,
    RIGHT_SHOULDER,
    LEFT_HIP,
    RIGHT_HIP,
)
STANDING_LANDMARKS = CORE_LANDMARKS + (
    LEFT_KNEE,
    RIGHT_KNEE,
    LEFT_ANKLE,
    RIGHT_ANKLE,
)

# Relative torso-yaw thresholds with hysteresis. A comfortable standing
# rotation does not need a dramatic turn toward profile, so the entry threshold
# is deliberately moderate. Consecutive-frame confirmation supplies the noise
# protection instead of demanding an unnecessarily large movement.
NEUTRAL_ENTER_DEG = 12.0
ROTATION_ENTER_DEG = 17.0
MIN_ROTATION_TRAVEL_DEG = 14.0
MAX_ROTATION_DEG = 72.0

YAW_SMOOTH_ALPHA = 0.62
NEUTRAL_STABLE_FRAMES = 5
POSITION_STABLE_FRAMES = 4
POSITION_GRACE_FRAMES = 8
ROTATION_CONFIRM_FRAMES = 3
NEUTRAL_RETURN_CONFIRM_FRAMES = 3
MIN_REP_DURATION = 0.25
MAX_REP_DURATION = 8.0

FRAME_EDGE_MARGIN = 0.035
BBOX_TOO_CLOSE = 0.96
BBOX_TOO_FAR = 0.08


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
    return visible_core >= 3


def _xyz(point: Any) -> tuple[float, float, float]:
    if isinstance(point, (tuple, list)) and len(point) >= 3:
        return (
            float(point[0]),
            float(point[1]),
            float(point[2]),
        )
    return (
        float(getattr(point, "x", 0.0)),
        float(getattr(point, "y", 0.0)),
        float(getattr(point, "z", 0.0) or 0.0),
    )


def _distance(a: Any, b: Any) -> float:
    ax, ay, az = _xyz(a)
    bx, by, bz = _xyz(b)
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2)


def _midpoint(a: Any, b: Any) -> tuple[float, float, float]:
    ax, ay, az = _xyz(a)
    bx, by, bz = _xyz(b)
    return (float((ax + bx) / 2), float((ay + by) / 2), float((az + bz) / 2))


def _normalize_angle(degrees: float) -> float:
    while degrees > 180.0:
        degrees -= 360.0
    while degrees < -180.0:
        degrees += 360.0
    return degrees


def _horizontal_line_yaw(left: Any, right: Any) -> Optional[float]:
    """Return the left-to-right line orientation in the x/z plane."""
    lx, _, lz = _xyz(left)
    rx, _, rz = _xyz(right)
    dx = rx - lx
    dz = rz - lz
    if math.hypot(dx, dz) < 1e-8:
        return None
    return math.degrees(math.atan2(dz, dx))


def _framing_feedback(points: list[Any]) -> Optional[str]:
    valid = [point for point in points if point is not None]
    for point in valid:
        if (
            point.x < FRAME_EDGE_MARGIN
            or point.x > 1.0 - FRAME_EDGE_MARGIN
            or point.y < FRAME_EDGE_MARGIN
            or point.y > 1.0 - FRAME_EDGE_MARGIN
        ):
            return (
                "Keep your shoulders, hips, knees, and ankles fully inside the frame."
            )

    if len(valid) < 4:
        return None
    xs = [point.x for point in valid]
    ys = [point.y for point in valid]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return (
            "You're too close to the camera — step back so your standing position fits."
        )
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for clearer tracking."
    return None


class StandingTrunkRotationAnalyzer:
    """Stateful standing trunk-rotation counter."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps
        self.stage = "neutral"
        self.rep_count = 0
        self.left_rep_count = 0
        self.right_rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        self.rotation_angle: Optional[float] = None
        self.smoothed_rotation: Optional[float] = None
        self.neutral_yaw: Optional[float] = None
        self.left_peak_rotation = 0.0
        self.right_peak_rotation = 0.0
        self._active_peak = 0.0
        self._active_side: Optional[str] = None
        self.rep_start_time: Optional[float] = None
        self._rotation_acc = 0.0
        self._last_rotation: Optional[float] = None
        self._last_timestamp_s: Optional[float] = None
        self._candidate_side: Optional[str] = None
        self._candidate_streak = 0
        self._neutral_return_streak = 0

        self._neutral_streak = 0
        self._position_good_streak = 0
        self._position_bad_streak = 0
        self.ready = False
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
            "ready": self.ready,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "left_rep_count": self.left_rep_count,
            "right_rep_count": self.right_rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": self._complete(),
            "rep_completed": False,
            "rep_side": None,
            "rep_duration": None,
            "rep_avg_speed": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "rotation_angle": None,
            "smoothed_rotation": None,
            "left_rotation": 0.0,
            "right_rotation": 0.0,
            "left_peak_rotation": round(self.left_peak_rotation, 1),
            "right_peak_rotation": round(self.right_peak_rotation, 1),
            "neutral_yaw": None,
            "torso_lean_angle": None,
            "standing": False,
            "framing_ok": True,
            "framing_message": None,
            "alignment_ok": True,
            "alignment_issue": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

    def _complete_active_rep(
        self,
        timestamp_s: float,
        torso_ok: bool,
    ) -> Optional[dict[str, Any]]:
        if self._active_side is None or self.rep_start_time is None:
            return None

        duration = max(0.0, timestamp_s - self.rep_start_time)
        issues: set[str] = set()
        if duration < MIN_REP_DURATION:
            issues.add("rushed_rep")
        if duration > MAX_REP_DURATION:
            issues.add("too_slow")
        if not torso_ok:
            issues.add("torso_lean")
        if self._active_peak < ROTATION_ENTER_DEG:
            issues.add("insufficient_rotation")

        quality = "good" if not issues else "needs_improvement"
        self.rep_count += 1
        if self._active_side == "left":
            self.left_rep_count += 1
        else:
            self.right_rep_count += 1
        if quality == "good":
            self.good_reps += 1
        else:
            self.flawed_reps += 1

        result = {
            "side": self._active_side,
            "duration": duration,
            "avg_speed": (self._rotation_acc / duration if duration > 0 else None),
            "classification": self._tempo(duration),
            "quality": quality,
        }
        self._active_side = None
        self.rep_start_time = None
        self._active_peak = 0.0
        self._rotation_acc = 0.0
        return result

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
                "No person detected — stand upright and face the camera."
            )
            return response

        left_shoulder = landmarks[LEFT_SHOULDER]
        right_shoulder = landmarks[RIGHT_SHOULDER]
        left_hip = landmarks[LEFT_HIP]
        right_hip = landmarks[RIGHT_HIP]
        left_knee = landmarks[LEFT_KNEE]
        right_knee = landmarks[RIGHT_KNEE]
        left_ankle = landmarks[LEFT_ANKLE]
        right_ankle = landmarks[RIGHT_ANKLE]

        torso_points = (
            left_shoulder,
            right_shoulder,
            left_hip,
            right_hip,
        )
        knee_points = (
            left_knee,
            right_knee,
        )
        ankle_points = (
            left_ankle,
            right_ankle,
        )
        response["pose_detected"] = True
        # Ankles are useful when available, but a normal camera crop often
        # cuts off the feet. Hips, shoulders, and knees are sufficient to
        # confirm an upright standing torso.
        response["low_visibility"] = not _visible(torso_points + knee_points)
        if response["low_visibility"]:
            response["feedback"] = (
                "Keep both shoulders, hips, and knees visible so I can "
                "measure your standing rotation."
            )
            return response

        visible_frame_points = list(torso_points + knee_points)
        visible_frame_points.extend(
            point
            for point in ankle_points
            if point is not None
            and (
                getattr(point, "visibility", None) is None
                or getattr(point, "visibility", 0.0) >= MIN_LANDMARK_VISIBILITY
            )
        )
        framing_message = _framing_feedback(visible_frame_points)
        framing_ok = framing_message is None

        mid_shoulder = _midpoint(left_shoulder, right_shoulder)
        mid_hip = _midpoint(left_hip, right_hip)
        torso_dx = abs(mid_hip[0] - mid_shoulder[0])
        torso_dy = abs(mid_hip[1] - mid_shoulder[1])
        torso_lean_angle = math.degrees(math.atan2(torso_dx, max(torso_dy, 1e-8)))
        torso_ok = torso_lean_angle <= 20.0

        left_knee_y = left_knee.y
        right_knee_y = right_knee.y
        left_ankle_y = left_ankle.y
        right_ankle_y = right_ankle.y
        left_ankle_visible = _visible((left_ankle,))
        right_ankle_visible = _visible((right_ankle,))
        legs_extended = (
            left_hip.y < left_knee_y
            and right_hip.y < right_knee_y
            and (not left_ankle_visible or left_knee_y < left_ankle_y)
            and (not right_ankle_visible or right_knee_y < right_ankle_y)
        )
        torso_height = max(
            _distance(
                _midpoint(left_shoulder, right_shoulder), _midpoint(left_hip, right_hip)
            ),
            1e-8,
        )
        # A standing detector should not accept a crouch/squat simply because
        # the landmarks remain vertically ordered. Require both visible leg
        # segments to retain a meaningful portion of the torso height.
        legs_long_enough = (
            left_knee_y - left_hip.y > torso_height * 0.28
            and right_knee_y - right_hip.y > torso_height * 0.28
            and (
                not left_ankle_visible
                or left_ankle_y - left_knee_y > torso_height * 0.20
            )
            and (
                not right_ankle_visible
                or right_ankle_y - right_knee_y > torso_height * 0.20
            )
        )
        hip_width = max(_distance(left_hip, right_hip), 1e-8)
        shoulder_width = max(_distance(left_shoulder, right_shoulder), 1e-8)
        stable_width = 0.30 <= shoulder_width / hip_width <= 2.7
        standing_now_ok = (
            framing_ok
            and torso_ok
            and legs_extended
            and legs_long_enough
            and stable_width
        )

        if standing_now_ok:
            self._position_good_streak += 1
            self._position_bad_streak = 0
        else:
            self._position_good_streak = 0
            self._position_bad_streak += 1
        if self._position_good_streak >= POSITION_STABLE_FRAMES:
            self.ready = True
        elif self._position_bad_streak >= POSITION_GRACE_FRAMES:
            self.ready = False
        position_ok = self.ready and standing_now_ok

        shoulder_yaw = _horizontal_line_yaw(left_shoulder, right_shoulder)
        hip_yaw = _horizontal_line_yaw(left_hip, right_hip)
        if shoulder_yaw is None or hip_yaw is None:
            response["feedback"] = (
                "Turn your whole upper body toward the camera so your torso is clear."
            )
            return response

        raw_rotation = _normalize_angle(shoulder_yaw - hip_yaw)
        # Keep calibration stable while the user is still in the neutral pose.
        if self.neutral_yaw is None:
            if abs(raw_rotation) <= NEUTRAL_ENTER_DEG and position_ok:
                self._neutral_streak += 1
                if self._neutral_streak >= NEUTRAL_STABLE_FRAMES:
                    self.neutral_yaw = raw_rotation
            else:
                self._neutral_streak = 0
        elif abs(raw_rotation - self.neutral_yaw) <= 8.0 and position_ok:
            self.neutral_yaw = 0.96 * self.neutral_yaw + 0.04 * raw_rotation

        neutral_offset = self.neutral_yaw if self.neutral_yaw is not None else 0.0
        rotation = _normalize_angle(raw_rotation - neutral_offset)
        self.rotation_angle = rotation
        self.smoothed_rotation = (
            rotation
            if self.smoothed_rotation is None
            else YAW_SMOOTH_ALPHA * rotation
            + (1.0 - YAW_SMOOTH_ALPHA) * self.smoothed_rotation
        )
        current_rotation = self.smoothed_rotation
        left_rotation = max(0.0, -current_rotation)
        right_rotation = max(0.0, current_rotation)

        if current_rotation < -ROTATION_ENTER_DEG:
            side = "left"
        elif current_rotation > ROTATION_ENTER_DEG:
            side = "right"
        else:
            side = None
        in_neutral = abs(current_rotation) <= NEUTRAL_ENTER_DEG

        # Confirm a direction across several frames. This lets the threshold
        # be reachable for ordinary movement without counting one noisy pose.
        if side is not None:
            if side == self._candidate_side:
                self._candidate_streak += 1
            else:
                self._candidate_side = side
                self._candidate_streak = 1
        else:
            self._candidate_side = None
            self._candidate_streak = 0
        if in_neutral:
            self._neutral_return_streak += 1
        else:
            self._neutral_return_streak = 0

        angle_velocity = None
        if self._last_rotation is not None and self._last_timestamp_s is not None:
            dt = max(timestamp_s - self._last_timestamp_s, 1e-6)
            angle_velocity = (current_rotation - self._last_rotation) / dt

        completed = None
        confirmed_side = (
            side if self._candidate_streak >= ROTATION_CONFIRM_FRAMES else None
        )
        confirmed_neutral = (
            in_neutral and self._neutral_return_streak >= NEUTRAL_RETURN_CONFIRM_FRAMES
        )

        if position_ok and confirmed_side is not None:
            if self.stage == "neutral":
                self.stage = confirmed_side
                self._active_side = confirmed_side
                self.rep_start_time = timestamp_s
                self._active_peak = abs(current_rotation)
                self._rotation_acc = 0.0
            elif self._active_side == confirmed_side:
                self._active_peak = max(self._active_peak, abs(current_rotation))
            if self._active_side == confirmed_side:
                self._active_peak = max(self._active_peak, abs(current_rotation))
                if self._last_rotation is not None:
                    self._rotation_acc += abs(current_rotation - self._last_rotation)
                if confirmed_side == "left":
                    self.left_peak_rotation = max(
                        self.left_peak_rotation, abs(current_rotation)
                    )
                else:
                    self.right_peak_rotation = max(
                        self.right_peak_rotation, abs(current_rotation)
                    )
        elif position_ok and confirmed_neutral and self.stage in ("left", "right"):
            completed = self._complete_active_rep(timestamp_s, torso_ok)
            self.stage = "neutral"

        if completed:
            response.update(
                {
                    "rep_completed": True,
                    "rep_side": completed["side"],
                    "rep_duration": round(completed["duration"], 3),
                    "rep_avg_speed": (
                        round(completed["avg_speed"], 2)
                        if completed["avg_speed"] is not None
                        else None
                    ),
                    "rep_classification": completed["classification"],
                    "rep_form_quality": completed["quality"],
                }
            )
            feedback = (
                f"{completed['side'].capitalize()} turn counted — "
                f"total {self.rep_count}. Nice and controlled."
            )
        elif not position_ok:
            if not torso_ok:
                position_message = "Stand tall — rotate your torso without leaning."
            elif not legs_extended or not legs_long_enough:
                position_message = "Stand tall with your hips above your knees."
            elif not framing_ok:
                position_message = framing_message
            else:
                position_message = "Set your feet and stand tall before rotating."
            feedback = position_message
        elif self.neutral_yaw is None:
            feedback = "Face the camera and hold neutral for a moment to calibrate."
        elif self.stage in ("left", "right"):
            feedback = f"Good {self.stage} turn — bring your shoulders back to center."
        elif self._complete():
            feedback = f"Target reached — {self.target_reps} trunk rotations completed."
        else:
            feedback = (
                "Ready — turn your shoulders left or right; keep your hips steady."
            )

        response.update(
            {
                "position_ok": position_ok,
                "position_message": None if position_ok else feedback,
                "ready": self.ready,
                "stage": self.stage,
                "rep_count": self.rep_count,
                "left_rep_count": self.left_rep_count,
                "right_rep_count": self.right_rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._complete(),
                "rotation_angle": round(rotation, 1),
                "smoothed_rotation": round(current_rotation, 1),
                "left_rotation": round(left_rotation, 1),
                "right_rotation": round(right_rotation, 1),
                "left_peak_rotation": round(self.left_peak_rotation, 1),
                "right_peak_rotation": round(self.right_peak_rotation, 1),
                "neutral_yaw": (
                    round(self.neutral_yaw, 1) if self.neutral_yaw is not None else None
                ),
                "torso_lean_angle": round(torso_lean_angle, 1),
                "standing": standing_now_ok,
                "framing_ok": framing_ok,
                "framing_message": framing_message,
                "alignment_ok": torso_ok and legs_extended and legs_long_enough,
                "alignment_issue": (
                    "Keep your torso upright and your legs stable while rotating."
                    if not torso_ok or not legs_extended or not legs_long_enough
                    else None
                ),
                "angle_velocity": (
                    round(angle_velocity, 2) if angle_velocity is not None else None
                ),
                "feedback": feedback,
            }
        )
        self._last_rotation = current_rotation
        self._last_timestamp_s = timestamp_s
        return response


class StandingTrunkRotationSession:
    """Standing Trunk Rotation session using one shared PoseEngine."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = StandingTrunkRotationAnalyzer(target_reps)
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
