import math
from collections import deque
from typing import Any, Optional

from src.engines.poseEngine import (
    LEFT_ANKLE,
    LEFT_EAR,
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    LEFT_WRIST,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_EAR,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)

MIN_LANDMARK_VISIBILITY = 0.35

SIDE_LANDMARKS = {
    "left": (LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE),
    "right": (
        RIGHT_SHOULDER,
        RIGHT_ELBOW,
        RIGHT_WRIST,
        RIGHT_HIP,
        RIGHT_KNEE,
        RIGHT_ANKLE,
    ),
}

CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)

SUPPORT_ANGLE_IDEAL = 90.0
SUPPORT_ANGLE_TOLERANCE = 50.0

ALIGN_BROKEN = 135.0
ALIGN_RESUME = 145.0
ALIGN_IDEAL = 165.0

KNEE_FULL_MIN = 150.0
KNEE_MOD_MIN = 70.0

HIP_SAG_THRESHOLD = 0.08
HIP_PIKE_THRESHOLD = -0.12

HEAD_ANGLE_DELTA = 20.0
CALIBRATION_FRAMES = 12

MISTAKE_PENALTY = {
    "hip_sag": 20,
    "hip_pike": 15,
    "support_misalign": 12,
    "head_position": 8,
    "knee_bent_full": 18,
    "modified_side_plank": 0,
}

SCORE_HISTORY = 30
SCORE_SAMPLE_INTERVAL = 1.0

FRAME_EDGE_MARGIN = 0.03
BODY_SPAN_TOO_CLOSE = 0.90
BODY_SPAN_TOO_FAR = 0.20
MAX_STANDING_RATIO = 0.75


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.5
    )
    return visible_core >= 2


def _side_visibility(landmarks, side: str) -> float:
    vals = []
    for idx in SIDE_LANDMARKS[side]:
        v = getattr(landmarks[idx], "visibility", 0.0) or 0.0
        vals.append(v)
    return min(vals) if vals else 0.0


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


def _hip_deviation(shoulder, hip, ankle_or_knee) -> float:
    body_len = max(_dist(shoulder, ankle_or_knee), 1e-6)
    dx = ankle_or_knee.x - shoulder.x
    if abs(dx) < 1e-6:
        return 0.0
    frac = (hip.x - shoulder.x) / dx
    line_y = shoulder.y + frac * (ankle_or_knee.y - shoulder.y)
    return (hip.y - line_y) / body_len


def _framing_feedback(shoulder, hip, reference_point) -> Optional[str]:
    for p in (shoulder, hip, reference_point):
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return "You're partly out of frame — fit the whole body in the shot."

    dx = abs(reference_point.x - shoulder.x)
    dy = abs(reference_point.y - shoulder.y)
    if dx < 1e-6 or (dy / dx) > MAX_STANDING_RATIO:
        return "Turn sideways to the camera and lie into a side plank position."

    body_span = math.hypot(dx, dy)
    if body_span > BODY_SPAN_TOO_CLOSE:
        return "You're too close to the camera — step back a little."
    if body_span < BODY_SPAN_TOO_FAR:
        return "You're too far from the camera — move closer."

    return None


class SidePlankHoldAnalyzer:
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
        self._baseline_head_angle = 180.0
        self.form_scores: deque[int] = deque(maxlen=SCORE_HISTORY)
        self._last_score_sample_time: Optional[float] = None

    def _is_complete(self) -> bool:
        return (
            self.target_seconds is not None and self.hold_seconds >= self.target_seconds
        )

    def _finish_calibration(self):
        self._baseline_head_angle = sum(self._calib_samples) / len(self._calib_samples)
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

    @staticmethod
    def _avg(values: "deque[int]") -> Optional[int]:
        if not values:
            return None
        return round(sum(values) / len(values))

    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t

        dt = 0.0
        if self.last_timestamp_s is not None:
            dt = max(0.0, min(t - self.last_timestamp_s, 0.5))
        self.last_timestamp_s = t

        response: dict[str, Any] = {
            "pose_detected": False,
            "active_side": self.active_side,
            "support_angle": None,
            "alignment_angle": None,
            "knee_angle": None,
            "head_angle": None,
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
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            self._register_broken_frame()
            response["feedback"] = "No person detected."
            response.update(self._progress_fields())
            return response

        self.active_side = self._pick_active_side(landmarks)
        if self.active_side is None:
            self._register_broken_frame()
            response["feedback"] = "Body not visible enough."
            response.update(self._progress_fields())
            return response

        s_idx, e_idx, w_idx, h_idx, k_idx, a_idx = SIDE_LANDMARKS[self.active_side]
        shoulder = landmarks[s_idx]
        elbow = landmarks[e_idx]
        wrist = landmarks[w_idx]
        hip = landmarks[h_idx]
        knee = landmarks[k_idx]
        ankle = landmarks[a_idx]
        ear = landmarks[LEFT_EAR if self.active_side == "left" else RIGHT_EAR]
        ear_ok = ear is not None and getattr(ear, "visibility", 0.0) > 0.3

        support_angle = _angle_deg(shoulder, elbow, wrist)
        alignment_angle = _angle_deg(shoulder, hip, ankle)
        knee_angle = _angle_deg(hip, knee, ankle)
        head_angle = _angle_deg(ear, shoulder, hip) if ear_ok else None

        reference = ankle if knee_angle >= KNEE_MOD_MIN else knee
        framing_message = _framing_feedback(shoulder, hip, reference)

        knee_is_modified = knee_angle < KNEE_FULL_MIN
        knee_too_bent = knee_angle < KNEE_MOD_MIN
        align_broken = alignment_angle < (
            ALIGN_BROKEN if self.hold_active else ALIGN_RESUME
        )
        support_ok = abs(support_angle - SUPPORT_ANGLE_IDEAL) <= SUPPORT_ANGLE_TOLERANCE

        holding_now = (
            framing_message is None
            and not align_broken
            and not knee_too_bent
            and support_ok
        )

        issues = []
        messages = []

        if holding_now:
            dev_ref = ankle if not knee_is_modified else knee
            deviation = _hip_deviation(shoulder, hip, dev_ref)

            if deviation > HIP_SAG_THRESHOLD:
                issues.append("hip_sag")
                messages.append("Lift your hips — you are sagging.")
            elif deviation < HIP_PIKE_THRESHOLD:
                issues.append("hip_pike")
                messages.append("Lower your hips a little — you are piking too high.")

            if not support_ok:
                issues.append("support_misalign")
                messages.append("Place your elbow directly under your shoulder.")

            if self.calibrated and head_angle is not None:
                if abs(head_angle - self._baseline_head_angle) > HEAD_ANGLE_DELTA:
                    issues.append("head_position")
                    messages.append("Keep your neck neutral.")

            if not self.calibrated and head_angle is not None and not issues:
                self._calib_samples.append(head_angle)
                if len(self._calib_samples) >= CALIBRATION_FRAMES:
                    self._finish_calibration()

        form_score = None
        hold_quality = None
        if holding_now:
            if not self.hold_active:
                self.current_streak_seconds = 0.0
            self.hold_active = True
            self.started = True
            self.hold_seconds += dt
            self.current_streak_seconds += dt
            self.best_streak_seconds = max(
                self.best_streak_seconds, self.current_streak_seconds
            )

            if issues:
                self.flawed_seconds += dt
                hold_quality = "needs_improvement"
            else:
                self.good_seconds += dt
                hold_quality = "good"

            form_score = 100
            for issue in issues:
                form_score -= MISTAKE_PENALTY.get(issue, 10)
            if knee_is_modified:
                form_score -= 0
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
        if feedback is None and knee_too_bent:
            feedback = "That is too collapsed for a side plank."
        elif feedback is None and align_broken:
            feedback = "Get into a straighter side plank line."
        elif feedback is None and not support_ok:
            feedback = "Move your elbow under your shoulder."
        elif feedback is None and messages:
            feedback = messages[0]
        elif feedback is None and target_reached:
            feedback = f"Target reached — {self.target_seconds}s held."
        elif feedback is None and holding_now:
            feedback = "Great hold."
        elif feedback is None:
            feedback = "Resume the side plank to continue timing."

        response.update(
            {
                "pose_detected": True,
                "active_side": self.active_side,
                "support_angle": round(support_angle, 1),
                "alignment_angle": round(alignment_angle, 1),
                "knee_angle": round(knee_angle, 1),
                "head_angle": round(head_angle, 1) if head_angle is not None else None,
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


class SidePlankHoldSession:
    def __init__(
        self,
        target_seconds: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = SidePlankHoldAnalyzer(target_seconds)
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
