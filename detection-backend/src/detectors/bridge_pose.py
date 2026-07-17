import math
from collections import deque
from typing import Any, Optional

from src.engines.poseEngine import (
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

MIN_LANDMARK_VISIBILITY = 0.30

SIDE_LANDMARKS = {
    "left": (LEFT_SHOULDER, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE),
    "right": (RIGHT_SHOULDER, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE),
}

CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)

ALIGN_BROKEN = 145.0
ALIGN_RESUME = 155.0
ALIGN_IDEAL = 168.0

SCORE_HISTORY = 30
SCORE_SAMPLE_INTERVAL = 1.0


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.35
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


class BridgeHoldAnalyzer:
    def __init__(self, target_seconds: Optional[int] = None):
        self.target_seconds = target_seconds
        self.active_side: Optional[str] = None
        self.hold_active = False
        self.started = False
        self.hold_seconds = 0.0
        self.current_streak_seconds = 0.0
        self.best_streak_seconds = 0.0
        self.break_count = 0
        self.last_timestamp_s: Optional[float] = None
        self.session_start_time: Optional[float] = None
        self._was_complete = False
        self.form_scores: deque[int] = deque(maxlen=SCORE_HISTORY)
        self._last_score_sample_time: Optional[float] = None

    def _is_complete(self) -> bool:
        return (
            self.target_seconds is not None and self.hold_seconds >= self.target_seconds
        )

    def _pick_active_side(self, landmarks) -> Optional[str]:
        vis = {side: _side_visibility(landmarks, side) for side in ("left", "right")}
        if (
            self.active_side
            and vis.get(self.active_side, 0.0) >= MIN_LANDMARK_VISIBILITY
        ):
            return self.active_side
        best = max(vis, key=lambda k: vis[k])
        return best if vis[best] >= MIN_LANDMARK_VISIBILITY else None

    def _register_broken_frame(self):
        if self.hold_active:
            self.break_count += 1
        self.hold_active = False
        self.current_streak_seconds = 0.0

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
            "alignment_angle": None,
            "knee_angle": None,
            "hold_state": (
                "holding"
                if self.started and self.hold_active
                else ("broken" if self.started else "not_started")
            ),
            "is_holding": False,
            "hold_seconds": round(self.hold_seconds, 2),
            "current_streak_seconds": round(self.current_streak_seconds, 2),
            "best_streak_seconds": round(self.best_streak_seconds, 2),
            "break_count": self.break_count,
            "target_seconds": self.target_seconds,
            "session_complete": self._is_complete(),
            "target_reached": False,
            "hold_quality": None,
            "posture_ok": True,
            "posture_issues": [],
            "posture_messages": [],
            "framing_ok": True,
            "framing_message": None,
            "form_score": None,
            "avg_form_score": None,
            "feedback": None,
            "debug": {},
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            self._register_broken_frame()
            response["feedback"] = "No person detected."
            response.update(self._progress_fields())
            return response

        self.active_side = self._pick_active_side(landmarks)
        if self.active_side is None:
            self._register_broken_frame()
            response["feedback"] = "Low visibility on both sides."
            response.update(self._progress_fields())
            return response

        s_idx, h_idx, k_idx, a_idx = SIDE_LANDMARKS[self.active_side]
        shoulder = landmarks[s_idx]
        hip = landmarks[h_idx]
        knee = landmarks[k_idx]
        ankle = landmarks[a_idx]

        alignment_angle = _angle_deg(shoulder, hip, knee)
        knee_angle = _angle_deg(hip, knee, ankle)

        align_broken = alignment_angle < (
            ALIGN_BROKEN if self.hold_active else ALIGN_RESUME
        )

        holding_now = not align_broken

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

            hold_quality = (
                "good" if alignment_angle >= ALIGN_IDEAL else "needs_improvement"
            )
            form_score = max(0, int(100 - max(0, ALIGN_IDEAL - alignment_angle)))
        else:
            self._register_broken_frame()
            hold_quality = None
            form_score = None

        is_complete = self._is_complete()
        target_reached = is_complete and not self._was_complete
        self._was_complete = is_complete

        if holding_now:
            if (
                self._last_score_sample_time is None
                or t - self._last_score_sample_time >= SCORE_SAMPLE_INTERVAL
            ):
                self.form_scores.append(form_score)
                self._last_score_sample_time = t

        feedback = (
            "Holding bridge."
            if holding_now
            else "Bridge broken — adjust shoulder to hip to knee alignment."
        )

        response.update(
            {
                "pose_detected": True,
                "active_side": self.active_side,
                "alignment_angle": round(alignment_angle, 1),
                "knee_angle": round(knee_angle, 1),
                "hold_state": "holding" if holding_now else "broken",
                "is_holding": holding_now,
                "target_reached": target_reached,
                "hold_quality": hold_quality,
                "form_score": form_score,
                "avg_form_score": self._avg(self.form_scores),
                "feedback": feedback,
                "debug": {
                    "align_broken": align_broken,
                    "side": self.active_side,
                },
            }
        )
        response.update(self._progress_fields())
        return response

    def _progress_fields(self) -> dict[str, Any]:
        return {
            "hold_seconds": round(self.hold_seconds, 2),
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


class BridgeHoldSession:
    def __init__(
        self,
        target_seconds: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = BridgeHoldAnalyzer(target_seconds)
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
