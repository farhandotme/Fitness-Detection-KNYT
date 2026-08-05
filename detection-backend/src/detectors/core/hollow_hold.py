import math
from collections import deque
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

MIN_LANDMARK_VISIBILITY = 0.4

SIDE_LANDMARKS = {
    "left": (
        LEFT_SHOULDER,
        LEFT_HIP,
        LEFT_KNEE,
        LEFT_ANKLE,
        LEFT_ELBOW,
        LEFT_WRIST,
    ),
    "right": (
        RIGHT_SHOULDER,
        RIGHT_HIP,
        RIGHT_KNEE,
        RIGHT_ANKLE,
        RIGHT_ELBOW,
        RIGHT_WRIST,
    ),
}

CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 2


SHOULDER_LIFT_BROKEN = 6.0
SHOULDER_LIFT_RESUME = 10.0

LEG_LIFT_BROKEN = 6.0
LEG_LIFT_RESUME = 10.0
LEG_LIFT_TOO_HIGH = 45.0

KNEE_STRAIGHT_BELOW = 155.0

ARM_UP_MARGIN = 0.03

HIP_RISE_TOLERANCE = 0.055
CALIBRATION_FRAMES = 15

MISTAKE_PENALTY = {
    "hip_lift": 24,
    "knee_bent": 12,
    "legs_too_high": 12,
    "arms_not_up": 8,
}

SCORE_HISTORY = 30
SCORE_SAMPLE_INTERVAL = 1.0

FRAME_EDGE_MARGIN = 0.03
BODY_SPAN_TOO_CLOSE = 0.9
BODY_SPAN_TOO_FAR = 0.3
MAX_UPRIGHT_RATIO = 0.6


class _Point:
    __slots__ = ("x", "y")

    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y


def _visible(points) -> bool:
    for p in points:
        if p is None:
            return False
        v = getattr(p, "visibility", None)
        if v is not None and v < MIN_LANDMARK_VISIBILITY:
            return False
    return True


def _side_visibility(landmarks, side: str) -> float:
    scores = []
    for idx in SIDE_LANDMARKS[side]:
        v = landmarks[idx].visibility
        scores.append(v if v is not None else 0.0)
    return min(scores) if scores else 0.0


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


def _lift_angle_deg(vertex, point) -> float:
    dx = abs(point.x - vertex.x)
    dy = vertex.y - point.y
    return math.degrees(math.atan2(dy, max(dx, 1e-9)))


def _reclining_feedback(shoulder, hip, ankle) -> Optional[str]:
    for p in (shoulder, hip, ankle):
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — reposition so your whole body, "
                "head to feet, fits in the shot."
            )

    dx = abs(ankle.x - shoulder.x)
    dy = abs(ankle.y - shoulder.y)
    if dx < 1e-6 or (dy / dx) > MAX_UPRIGHT_RATIO:
        return (
            "Lie flat on your back, side-on to the camera — I need a side "
            "view of your whole body to check the hollow hold."
        )

    body_span = math.hypot(dx, dy)
    if body_span > BODY_SPAN_TOO_CLOSE:
        return "You're too close to the camera — move back until your whole body fits in frame."
    if body_span < BODY_SPAN_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."
    return None


class HollowHoldAnalyzer:
    """Stateful hollow-hold timer + posture checker."""

    def __init__(self, target_seconds: Optional[int] = None):
        self.target_seconds = target_seconds
        self.active_side: Optional[str] = None

        self.hold_active = False
        self.started = False
        self.hold_seconds = 0.0
        self.good_seconds = 0.0
        self.flawed_seconds = 0.0
        self.current_streak_seconds = 0.0
        self.best_streak_seconds = 0.0
        self.break_count = 0

        self.last_timestamp_s: Optional[float] = None
        self.session_start_time: Optional[float] = None
        self._was_complete = False

        self._calib_samples: list[float] = []
        self.calibrated = False
        self._baseline_hip_y = 0.0

        self.form_scores: deque[int] = deque(maxlen=SCORE_HISTORY)
        self._last_score_sample_time: Optional[float] = None

    def _is_complete(self) -> bool:
        return (
            self.target_seconds is not None and self.hold_seconds >= self.target_seconds
        )

    def _finish_calibration(self):
        n = len(self._calib_samples)
        self._baseline_hip_y = sum(self._calib_samples) / n
        self.calibrated = True

    def _pick_active_side(self, landmarks) -> Optional[str]:
        vis = {side: _side_visibility(landmarks, side) for side in ("left", "right")}
        if (
            self.active_side is not None
            and vis[self.active_side] >= MIN_LANDMARK_VISIBILITY
        ):
            return self.active_side
        best_side = max(vis, key=lambda s: vis[s])
        return best_side if vis[best_side] >= MIN_LANDMARK_VISIBILITY else None

    def _avg(self, values: deque[int]) -> Optional[int]:
        if not values:
            return None
        return round(sum(values) / len(values))

    def _register_broken_frame(self):
        if self.hold_active:
            self.break_count += 1
        self.hold_active = False
        self.current_streak_seconds = 0.0

    def _progress_fields(self) -> dict[str, Any]:
        return {
            "hold_seconds": round(self.hold_seconds, 2),
            "good_seconds": round(self.good_seconds, 2),
            "flawed_seconds": round(self.flawed_seconds, 2),
            "current_streak_seconds": round(self.current_streak_seconds, 2),
            "best_streak_seconds": round(self.best_streak_seconds, 2),
            "break_count": self.break_count,
            "session_complete": self._is_complete(),
        }

    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "active_side": self.active_side,
            "shoulder_lift_deg": None,
            "leg_lift_deg": None,
            "knee_angle": None,
            "elbow_angle": None,
            "hip_rise_ratio": None,
            "hold_state": (
                "holding"
                if self.started and self.hold_active
                else ("broken" if self.started else "not_started")
            ),
            "is_holding": False,
            "hold_seconds": round(self.hold_seconds, 2),
            "good_seconds": round(self.good_seconds, 2),
            "flawed_seconds": round(self.flawed_seconds, 2),
            "current_streak_seconds": round(self.current_streak_seconds, 2),
            "best_streak_seconds": round(self.best_streak_seconds, 2),
            "break_count": self.break_count,
            "target_seconds": self.target_seconds,
            "session_complete": self._is_complete(),
            "target_reached": False,
            "hold_quality": None,
            "calibrated": self.calibrated,
            "posture_ok": True,
            "posture_issues": [],
            "posture_messages": [],
            "framing_ok": True,
            "framing_message": None,
            "form_score": None,
            "avg_form_score": self._avg(self.form_scores),
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        dt = 0.0
        if self.last_timestamp_s is not None:
            dt = max(0.0, min(t - self.last_timestamp_s, 0.5))
        self.last_timestamp_s = t

        if landmarks is None or not _looks_like_a_person(landmarks):
            self._register_broken_frame()
            response["feedback"] = (
                "No person detected — get into frame, lying on your back, side-on to the camera."
            )
            response.update(self._progress_fields())
            return response

        self.active_side = self._pick_active_side(landmarks)
        if self.active_side is None:
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._register_broken_frame()
            response["feedback"] = (
                "Can't see your body clearly — step back and make sure you're filmed side-on, whole body in frame."
            )
            response.update(self._progress_fields())
            return response

        s_idx, h_idx, k_idx, a_idx, e_idx, w_idx = SIDE_LANDMARKS[self.active_side]
        shoulder = landmarks[s_idx]
        hip = landmarks[h_idx]
        knee = landmarks[k_idx]
        ankle = landmarks[a_idx]
        elbow = landmarks[e_idx]
        wrist = landmarks[w_idx]

        framing_message = _reclining_feedback(shoulder, hip, ankle)

        shoulder_lift_deg = _lift_angle_deg(hip, shoulder)
        leg_lift_deg = _lift_angle_deg(hip, ankle)
        knee_angle = _angle_deg(hip, knee, ankle)
        elbow_angle = _angle_deg(shoulder, elbow, wrist)

        if self.hold_active:
            shoulder_broken = shoulder_lift_deg < SHOULDER_LIFT_BROKEN
            legs_broken = leg_lift_deg < LEG_LIFT_BROKEN
        else:
            shoulder_broken = shoulder_lift_deg < SHOULDER_LIFT_RESUME
            legs_broken = leg_lift_deg < LEG_LIFT_RESUME

        holding_now = (
            framing_message is None and not shoulder_broken and not legs_broken
        )

        body_len = max(_dist(shoulder, ankle), 1e-6)
        is_resting_flat = (
            framing_message is None
            and shoulder_lift_deg < SHOULDER_LIFT_BROKEN
            and leg_lift_deg < LEG_LIFT_BROKEN
        )
        if not self.calibrated and is_resting_flat:
            self._calib_samples.append(hip.y)
            if len(self._calib_samples) >= CALIBRATION_FRAMES:
                self._finish_calibration()

        issues: list[str] = []
        messages: list[str] = []

        if holding_now:
            if self.calibrated:
                hip_rise_ratio = (self._baseline_hip_y - hip.y) / body_len
                response["hip_rise_ratio"] = round(hip_rise_ratio, 3)
                if hip_rise_ratio > HIP_RISE_TOLERANCE:
                    issues.append("hip_lift")
                    messages.append(
                        "Press your lower back into the mat — your hips are lifting up. Keep them anchored down."
                    )

            if knee_angle < KNEE_STRAIGHT_BELOW:
                issues.append("knee_bent")
                messages.append(
                    "Straighten your legs for a full hollow hold — a bent-knee tuck is a fine regression for now."
                )

            if leg_lift_deg > LEG_LIFT_TOO_HIGH:
                issues.append("legs_too_high")
                messages.append(
                    "Lower your legs a little — this is a hollow hold, not a V-up. Keep the lift shallow."
                )

            if wrist.y >= shoulder.y - ARM_UP_MARGIN:
                issues.append("arms_not_up")
                messages.append("Lift your hands higher — arms should be up.")

        form_score = None
        hold_quality = None

        if holding_now:
            if not self.hold_active:
                self.current_streak_seconds = 0.0
            self.hold_active = True
            self.started = True

            self.hold_seconds += dt
            self.current_streak_seconds += dt
            if self.current_streak_seconds > self.best_streak_seconds:
                self.best_streak_seconds = self.current_streak_seconds

            if issues:
                self.flawed_seconds += dt
                hold_quality = "needs_improvement"
            else:
                self.good_seconds += dt
                hold_quality = "good"

            form_score = 100
            for issue in issues:
                form_score -= MISTAKE_PENALTY.get(issue, 10)
            form_score = max(0, form_score)

            if (
                self._last_score_sample_time is None
                or t - self._last_score_sample_time >= SCORE_SAMPLE_INTERVAL
            ):
                self.form_scores.append(form_score)
                self._last_score_sample_time = t
        else:
            self._register_broken_frame()

        is_complete = self._is_complete()
        target_reached = is_complete and not self._was_complete
        self._was_complete = is_complete

        feedback = framing_message
        if feedback is None and (shoulder_broken or legs_broken):
            if shoulder_broken and legs_broken:
                feedback = "Lift your shoulders and legs off the mat together to start the hollow hold."
            elif shoulder_broken:
                feedback = "Lift your shoulders and upper back off the mat."
            else:
                feedback = "Lift your legs off the mat, knees straight."

        if feedback is None and messages:
            feedback = messages[0]
        if feedback is None and not self.calibrated and holding_now:
            feedback = "Great hollow position — hold it, calibrating your baseline."
        if feedback is None and target_reached:
            feedback = f"Target reached — {self.target_seconds}s held, nice work!"
        if feedback is None and holding_now:
            feedback = "Great hollow hold — keep holding!"
        if feedback is None:
            feedback = "Get back into hollow hold position to resume the timer."

        response.update(
            {
                "pose_detected": True,
                "active_side": self.active_side,
                "shoulder_lift_deg": round(shoulder_lift_deg, 1),
                "leg_lift_deg": round(leg_lift_deg, 1),
                "knee_angle": round(knee_angle, 1),
                "elbow_angle": round(elbow_angle, 1),
                "hold_state": "holding" if holding_now else "broken",
                "is_holding": holding_now,
                "target_reached": target_reached,
                "hold_quality": hold_quality,
                "calibrated": self.calibrated,
                "posture_ok": len(issues) == 0,
                "posture_issues": issues,
                "posture_messages": messages,
                "framing_ok": framing_message is None,
                "framing_message": framing_message,
                "form_score": form_score,
                "avg_form_score": self._avg(self.form_scores),
                "feedback": feedback,
            }
        )
        response.update(self._progress_fields())
        return response


class HollowHoldSession:
    """Full hollow-hold session: one shared pose model + one analyzer."""

    def __init__(
        self,
        target_seconds: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = HollowHoldAnalyzer(target_seconds)
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
