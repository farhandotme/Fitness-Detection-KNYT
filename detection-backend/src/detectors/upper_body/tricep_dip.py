"""
Tricep Dip detector.

Movement contract
-----------------
This detector is designed for a side or three-quarter camera view of a
bench/chair dip:

    1. Start supported with the elbows nearly straight.
    2. Lower the body under control until the elbows are meaningfully bent.
    3. Press back to the supported position.

The elbow angle (shoulder -> elbow -> wrist) is the primary movement signal.
The detector deliberately does not count a single bent-arm frame: a valid rep
must observe the extended position first, pass through the bent position, and
return to extension with enough angular travel.

The position gate is intentionally independent from the rep state machine.
It prevents a front-facing arm movement from being counted as a dip, while
short landmark drops do not immediately stop an in-progress rep.
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    LEFT_WRIST,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)

# ---------------------------------------------------------------------------
# Detection and geometry thresholds
# ---------------------------------------------------------------------------

MIN_LANDMARK_VISIBILITY = 0.42
PERSON_VISIBILITY = 0.60

CORE_LANDMARKS = (
    LEFT_SHOULDER,
    RIGHT_SHOULDER,
    LEFT_HIP,
    RIGHT_HIP,
)

# A dip is best tracked from the side or a three-quarter view. The front-view
# threshold is intentionally permissive because a phone may be offset.
FRONT_VIEW_RATIO = 1.05

# Angle at the elbow. These are hysteresis thresholds, not claims about a
# user's exact anatomy:
#   >= 155°: supported/extended
#   <= 105°: bottom/deep enough to count
EXTENDED_ENTER_DEG = 155.0
BOTTOM_ENTER_DEG = 105.0
MIN_REP_TRAVEL_DEG = 45.0

MIN_REP_DURATION = 0.30
MAX_REP_DURATION = 8.0
MIN_REP_DEPTH_DEG = 118.0

ANGLE_SMOOTH_ALPHA = 0.55
POSITION_STABLE_FRAMES = 4
POSITION_GRACE_FRAMES = 8

# Camera framing thresholds.
FRAME_EDGE_MARGIN = 0.035
BBOX_TOO_CLOSE = 0.96
BBOX_TOO_FAR = 0.10


class _Point:
    __slots__ = ("x", "y")

    def __init__(self, x: float, y: float):
        self.x = float(x)
        self.y = float(y)


def _visible(
    points: tuple[Any, ...], threshold: float = MIN_LANDMARK_VISIBILITY
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


def _angle_deg(a: Any, b: Any, c: Any) -> float:
    """Angle at b between b->a and b->c, normalized to [0, 180]."""
    angle = math.degrees(
        math.atan2(c.y - b.y, c.x - b.x) - math.atan2(a.y - b.y, a.x - b.x)
    )
    angle = abs(angle)
    return 360.0 - angle if angle > 180.0 else angle


def _distance(a: Any, b: Any) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _midpoint(a: Any, b: Any) -> _Point:
    return _Point((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)


def _torso_incline_deg(mid_shoulder: Any, mid_hip: Any) -> Optional[float]:
    """0° is upright; 90° is horizontal."""
    dx = mid_hip.x - mid_shoulder.x
    dy = mid_hip.y - mid_shoulder.y
    if abs(dx) < 1e-8 and abs(dy) < 1e-8:
        return None
    return math.degrees(math.atan2(abs(dx), max(abs(dy), 1e-8)))


def _view_mode(shoulder_width: float, torso_length: float) -> str:
    ratio = shoulder_width / max(torso_length, 1e-8)
    if ratio >= FRONT_VIEW_RATIO:
        return "front"
    if ratio <= 0.52:
        return "side"
    return "angled"


def _framing_feedback(points: list[Any]) -> Optional[str]:
    valid = [point for point in points if point is not None]
    for point in valid:
        if (
            point.x < FRAME_EDGE_MARGIN
            or point.x > 1.0 - FRAME_EDGE_MARGIN
            or point.y < FRAME_EDGE_MARGIN
            or point.y > 1.0 - FRAME_EDGE_MARGIN
        ):
            return "You're partly out of frame — keep your shoulders, hips, elbows, and wrists visible."

    if len(valid) < 4:
        return None

    xs = [point.x for point in valid]
    ys = [point.y for point in valid]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return (
            "You're too close to the camera — move back so your full dip position fits."
        )
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for a clearer elbow angle."
    return None


class TricepDipAnalyzer:
    """Stateful, side-view tricep-dip rep counter."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.stage = "up"
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        self.smoothed_angle: Optional[float] = None
        self.last_angle: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None
        self.rep_start_time: Optional[float] = None
        self._rep_angle_acc = 0.0
        self._rep_min_angle: Optional[float] = None
        self._rep_issues: set[str] = set()
        self._seen_extended = False

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
        if duration < 0.30:
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
            "depth_reached": False,
            "top_reached": False,
            "alignment_ok": True,
            "alignment_issue": None,
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

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
                "No person detected — sit in front of the camera and place your hands behind you on the support."
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
        left_knee = landmarks[LEFT_KNEE]
        right_knee = landmarks[RIGHT_KNEE]
        left_ankle = landmarks[LEFT_ANKLE]
        right_ankle = landmarks[RIGHT_ANKLE]

        mid_shoulder = _midpoint(left_shoulder, right_shoulder)
        mid_hip = _midpoint(left_hip, right_hip)
        torso_length = max(_distance(mid_shoulder, mid_hip), 1e-8)
        shoulder_width = _distance(left_shoulder, right_shoulder)
        view_mode = _view_mode(shoulder_width, torso_length)
        response["pose_detected"] = True
        response["view_mode"] = view_mode

        arm_candidates: list[tuple[float, str, Any, Any, Any]] = []
        if _visible((left_shoulder, left_elbow, left_wrist)):
            arm_candidates.append(
                (
                    float(getattr(left_elbow, "visibility", 1.0) or 1.0),
                    "left",
                    left_shoulder,
                    left_elbow,
                    left_wrist,
                )
            )
        if _visible((right_shoulder, right_elbow, right_wrist)):
            arm_candidates.append(
                (
                    float(getattr(right_elbow, "visibility", 1.0) or 1.0),
                    "right",
                    right_shoulder,
                    right_elbow,
                    right_wrist,
                )
            )

        if not arm_candidates:
            response["low_visibility"] = True
            response["feedback"] = (
                "I can't see your elbows and wrists clearly — turn slightly sideways and move your arms away from your body."
            )
            return response

        left_angle = (
            _angle_deg(left_shoulder, left_elbow, left_wrist)
            if _visible((left_shoulder, left_elbow, left_wrist))
            else None
        )
        right_angle = (
            _angle_deg(right_shoulder, right_elbow, right_wrist)
            if _visible((right_shoulder, right_elbow, right_wrist))
            else None
        )
        angles = [angle for angle in (left_angle, right_angle) if angle is not None]
        raw_angle = sum(angles) / len(angles)

        self.smoothed_angle = (
            raw_angle
            if self.smoothed_angle is None
            else ANGLE_SMOOTH_ALPHA * raw_angle
            + (1.0 - ANGLE_SMOOTH_ALPHA) * self.smoothed_angle
        )

        angle_velocity = None
        if self.last_angle is not None and self.last_timestamp_s is not None:
            dt = max(timestamp_s - self.last_timestamp_s, 1e-6)
            angle_velocity = (self.smoothed_angle - self.last_angle) / dt

        visible_body_points = [
            left_shoulder,
            right_shoulder,
            left_hip,
            right_hip,
            left_elbow,
            right_elbow,
            left_wrist,
            right_wrist,
            left_knee,
            right_knee,
            left_ankle,
            right_ankle,
        ]
        framing_message = _framing_feedback(visible_body_points)
        framing_ok = framing_message is None

        torso_incline = _torso_incline_deg(mid_shoulder, mid_hip)
        torso_ok = torso_incline is not None and torso_incline <= 58.0
        arms_below_shoulders = any(
            elbow.y >= shoulder.y - 0.08 and wrist.y >= shoulder.y - 0.08
            for shoulder, elbow, wrist in (
                (left_shoulder, left_elbow, left_wrist),
                (right_shoulder, right_elbow, right_wrist),
            )
            if _visible((shoulder, elbow, wrist))
        )
        side_view_ok = view_mode != "front"
        position_now_ok = (
            framing_ok and torso_ok and arms_below_shoulders and side_view_ok
        )

        if position_now_ok:
            self._position_good_streak += 1
            self._position_bad_streak = 0
        else:
            self._position_good_streak = 0
            self._position_bad_streak += 1

        if self._position_good_streak >= POSITION_STABLE_FRAMES:
            self.ready = True
        elif self._position_bad_streak >= POSITION_GRACE_FRAMES:
            self.ready = False

        position_ok = self.ready and position_now_ok
        if not side_view_ok:
            position_message = "Turn sideways or three-quarter to the camera so the elbow bend can be measured."
        elif not torso_ok:
            position_message = (
                "Sit tall with your shoulders above your hips and keep your chest open."
            )
        elif not arms_below_shoulders:
            position_message = "Place your hands behind you on the support and keep your elbows visible."
        elif not framing_ok:
            position_message = framing_message
        else:
            position_message = None

        current_angle = self.smoothed_angle
        extended = current_angle >= EXTENDED_ENTER_DEG
        bottom = current_angle <= BOTTOM_ENTER_DEG
        depth_reached = current_angle <= MIN_REP_DEPTH_DEG

        if extended and position_ok:
            self._seen_extended = True
            if self.stage == "down":
                self.stage = "up"
                if self.rep_start_time is not None and self._rep_min_angle is not None:
                    duration = max(0.0, timestamp_s - self.rep_start_time)
                    travel = EXTENDED_ENTER_DEG - self._rep_min_angle
                    if travel >= MIN_REP_TRAVEL_DEG:
                        self.rep_count += 1
                        rep_completed = True
                        rep_duration = duration
                        rep_avg_speed = (
                            self._rep_angle_acc / duration if duration > 0 else None
                        )
                        rep_classification = self._tempo(duration)
                        if self._rep_min_angle > MIN_REP_DEPTH_DEG:
                            self._rep_issues.add("shallow_depth")
                        if duration < MIN_REP_DURATION:
                            self._rep_issues.add("rushed_rep")
                        rep_form_quality = (
                            "good" if not self._rep_issues else "needs_improvement"
                        )
                        if rep_form_quality == "good":
                            self.good_reps += 1
                        else:
                            self.flawed_reps += 1
                        response.update(
                            {
                                "rep_completed": rep_completed,
                                "rep_duration": round(rep_duration, 3),
                                "rep_avg_speed": (
                                    round(rep_avg_speed, 2)
                                    if rep_avg_speed is not None
                                    else None
                                ),
                                "rep_classification": rep_classification,
                                "rep_form_quality": rep_form_quality,
                            }
                        )
                    else:
                        self._rep_issues.add("insufficient_range")

                self.rep_start_time = None
                self._rep_min_angle = None
                self._rep_angle_acc = 0.0
                self._rep_issues = set()

        elif bottom and position_ok and self._seen_extended:
            if self.stage == "up":
                self.stage = "down"
                self.rep_start_time = timestamp_s
                self._rep_min_angle = current_angle
                self._rep_angle_acc = 0.0
                self._rep_issues = set()
            elif self._rep_min_angle is None or current_angle < self._rep_min_angle:
                self._rep_min_angle = current_angle

        if self.stage == "down":
            if self._rep_min_angle is None or current_angle < self._rep_min_angle:
                self._rep_min_angle = current_angle
            if self.last_angle is not None:
                self._rep_angle_acc += abs(current_angle - self.last_angle)
            if self._rep_min_angle > MIN_REP_DEPTH_DEG:
                self._rep_issues.add("shallow_depth")
        if torso_incline is not None and torso_incline > 48.0:
            self._rep_issues.add("torso_lean")

        if response["rep_completed"]:
            feedback = (
                f"Rep {self.rep_count} counted — " "keep the next dip controlled."
                if response["rep_form_quality"] != "good"
                else f"Rep {self.rep_count} counted — strong, controlled dip."
            )
        elif not position_ok:
            feedback = position_message
        elif not self._seen_extended:
            feedback = (
                "Lock out your elbows at the top first, then lower under control."
            )
        elif self.stage == "down" and not depth_reached:
            feedback = (
                "Lower a little deeper — aim for roughly a right angle at the elbows."
            )
        elif self.stage == "down":
            feedback = (
                "Good depth — press through your hands and return to full extension."
            )
        elif self._complete():
            feedback = f"Target reached — {self.target_reps} tricep dips completed."
        else:
            feedback = "Ready — lower slowly, keep your shoulders down, then press up."

        response.update(
            {
                "position_ok": position_ok,
                "position_message": position_message,
                "ready": self.ready,
                "angle": round(raw_angle, 1),
                "smoothed_angle": round(current_angle, 1),
                "left_elbow_angle": (
                    round(left_angle, 1) if left_angle is not None else None
                ),
                "right_elbow_angle": (
                    round(right_angle, 1) if right_angle is not None else None
                ),
                "angle_velocity": (
                    round(angle_velocity, 2) if angle_velocity is not None else None
                ),
                "depth_reached": depth_reached,
                "top_reached": extended,
                "framing_ok": framing_ok,
                "framing_message": framing_message,
                "alignment_ok": torso_ok and side_view_ok,
                "alignment_issue": (
                    "Keep your torso upright and use a side or three-quarter view."
                    if not torso_ok or not side_view_ok
                    else None
                ),
                "stage": self.stage,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._complete(),
                "feedback": feedback,
            }
        )

        self.last_angle = current_angle
        self.last_timestamp_s = timestamp_s
        return response


class TricepDipSession:
    """Full Tricep Dip session using one shared PoseEngine and analyzer."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = TricepDipAnalyzer(target_reps)
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
