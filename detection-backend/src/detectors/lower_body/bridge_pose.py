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

ALIGN_BROKEN = 110.0
ALIGN_RESUME = 120.0
ALIGN_IDEAL = 140.0

# A standing person also has a near-straight shoulder-hip-knee line, so
# alignment_angle alone can't tell "bridge" apart from "standing in frame".
# These extra checks confirm the person is actually lying down with hips
# raised and knees bent, not just standing upright doing nothing.
KNEE_ANGLE_MIN = 55.0
KNEE_ANGLE_MAX = 120.0
LYING_ASPECT_RATIO = (
    1.15  # torso must be wider (horizontal) than tall to count as lying down
)
HIP_ELEVATION_MARGIN = 0.02  # normalized-coord margin; hip.y must be this much smaller (higher) than shoulder.y/ankle.y

POSTURE_ISSUE_MESSAGES = {
    "not_lying_down": "Lie down on your back, side-on to the camera.",
    "hips_not_raised": "Lift your hips higher off the floor.",
    "knees_not_bent": "Bend your knees to roughly a right angle, feet flat on the floor.",
}

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


def _is_lying_down(shoulder, ankle) -> bool:
    """True if the body is spread out horizontally (side-on to camera),
    as opposed to stacked vertically like someone standing up."""
    horizontal_span = abs(ankle.x - shoulder.x)
    vertical_span = abs(ankle.y - shoulder.y)
    return horizontal_span > vertical_span * LYING_ASPECT_RATIO


def _hip_is_elevated(shoulder, hip, ankle) -> bool:
    """True if the hip sits meaningfully higher (smaller y) than both the
    shoulder and the ankle, i.e. actually lifted off the ground."""
    return (
        hip.y < shoulder.y - HIP_ELEVATION_MARGIN
        and hip.y < ankle.y - HIP_ELEVATION_MARGIN
    )


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
        self.good_seconds = 0.0
        self.flawed_seconds = 0.0
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
            "good_seconds": round(self.good_seconds, 2),
            "flawed_seconds": round(self.flawed_seconds, 2),
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

        lying_down = _is_lying_down(shoulder, ankle)
        hip_elevated = _hip_is_elevated(shoulder, hip, ankle)
        knee_bent_ok = KNEE_ANGLE_MIN <= knee_angle <= KNEE_ANGLE_MAX

        posture_issues = []
        if not lying_down:
            posture_issues.append("not_lying_down")
        if not hip_elevated:
            posture_issues.append("hips_not_raised")
        if not knee_bent_ok:
            posture_issues.append("knees_not_bent")

        align_broken = alignment_angle < (
            ALIGN_BROKEN if self.hold_active else ALIGN_RESUME
        )

        holding_now = not align_broken and lying_down and hip_elevated and knee_bent_ok

        if holding_now:
            if not self.hold_active:
                self.current_streak_seconds = 0.0
            self.hold_active = True
            self.started = True
            self.current_streak_seconds += dt
            self.best_streak_seconds = max(
                self.best_streak_seconds, self.current_streak_seconds
            )

            hold_quality = (
                "good" if alignment_angle >= ALIGN_IDEAL else "needs_improvement"
            )
            form_score = max(0, int(100 - max(0, ALIGN_IDEAL - alignment_angle)))

            # Only genuinely ideal-form frames count toward completing the
            # exercise. A frame that's merely "not broken" but below the
            # ideal threshold is real, detected holding — just not the
            # correct position — so it's tracked separately and doesn't
            # advance the target timer.
            if hold_quality == "good":
                self.hold_seconds += dt
                self.good_seconds += dt
            else:
                self.flawed_seconds += dt
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

        posture_messages = [POSTURE_ISSUE_MESSAGES[i] for i in posture_issues]

        if holding_now:
            feedback = "Holding bridge."
        elif posture_messages:
            feedback = posture_messages[0]
        else:
            feedback = "Bridge broken — adjust shoulder to hip to knee alignment."

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
                "posture_ok": not posture_issues,
                "posture_issues": posture_issues,
                "posture_messages": posture_messages,
                "form_score": form_score,
                "avg_form_score": self._avg(self.form_scores),
                "feedback": feedback,
                "debug": {
                    "align_broken": align_broken,
                    "lying_down": lying_down,
                    "hip_elevated": hip_elevated,
                    "knee_bent_ok": knee_bent_ok,
                    "side": self.active_side,
                },
            }
        )
        response.update(self._progress_fields())
        return response

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
