import math
from collections import deque
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_HEEL,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_HEEL,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
)

MIN_LANDMARK_VISIBILITY = 0.35


def _looks_like_a_person(landmarks) -> bool:
    shoulder_ok = any(
        landmarks[i].visibility is not None and landmarks[i].visibility > 0.45
        for i in (LEFT_SHOULDER, RIGHT_SHOULDER)
    )
    hip_ok = any(
        landmarks[i].visibility is not None and landmarks[i].visibility > 0.45
        for i in (LEFT_HIP, RIGHT_HIP)
    )
    return shoulder_ok and hip_ok


CALIBRATION_MIN_FRAMES = 8
CALIBRATION_MAX_FRAMES = 45
POSE_FRACTION = 0.82
RESUME_FRACTION = 0.90
MIN_CHEST_FOLD = 0.03
MISTAKE_PENALTY = {
    "shallow_fold": 10,
    "chest_not_lowered": 10,
}
SCORE_HISTORY = 30
SCORE_SAMPLE_INTERVAL = 1.0
KNEELING_SHIN_VERTICALITY_MAX = 0.78
STANDING_SHIN_VERTICALITY_MIN = 0.90
SIDE_VIEW_RATIO_MAX = 0.72
FRONT_VIEW_RATIO_MIN = 1.18
FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.96
BBOX_TOO_FAR = 0.11


class _Point:
    __slots__ = ("x", "y")

    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y


def _midpoint(a, b) -> _Point:
    return _Point((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)


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


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[idx]


def _avg_point(a, b) -> Optional[_Point]:
    a_ok = _visible((a,))
    b_ok = _visible((b,))
    if a_ok and b_ok:
        return _midpoint(a, b)
    if a_ok:
        return _Point(a.x, a.y)
    if b_ok:
        return _Point(b.x, b.y)
    return None


def _heel_point(l_heel, r_heel, l_ankle, r_ankle) -> Optional[_Point]:
    ankle_pt = _avg_point(l_ankle, r_ankle)
    heel_pt = _avg_point(l_heel, r_heel)
    if ankle_pt is None:
        return heel_pt
    if heel_pt is None:
        return ankle_pt
    if _dist(ankle_pt, heel_pt) <= 0.10:
        return _midpoint(ankle_pt, heel_pt)
    return ankle_pt


def _view_mode(shoulder_width: float, torso_length: float) -> str:
    ratio = shoulder_width / max(torso_length, 1e-6)
    if ratio <= SIDE_VIEW_RATIO_MAX:
        return "side"
    if ratio >= FRONT_VIEW_RATIO_MIN:
        return "front"
    return "angled"


def _assess_floor_stance(
    mid_knee: Optional[_Point],
    mid_ankle: Optional[_Point],
    shin_length: float,
) -> tuple[bool, bool]:
    if mid_knee is None or mid_ankle is None or shin_length <= 1e-6:
        return False, False
    verticality = abs(mid_knee.y - mid_ankle.y) / shin_length
    is_floor = verticality <= KNEELING_SHIN_VERTICALITY_MAX
    is_standing = verticality >= STANDING_SHIN_VERTICALITY_MIN
    return is_floor, is_standing


def _framing_feedback(points: list[_Point]) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — reposition so your whole body is visible."
            )
    if len(points) < 4:
        return None
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return (
            "You're too close to the camera — back up so your whole body fits in frame."
        )
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."
    return None


class ChildsPoseAnalyzer:
    def __init__(self, target_seconds: Optional[int] = None):
        self.target_seconds = target_seconds
        self.hold_active = False
        self.started = False
        self.hold_seconds = 0.0
        self.good_seconds = 0.0
        self.flawed_seconds = 0.0
        self.current_streak_seconds = 0.0
        self.best_streak_seconds = 0.0
        self.break_count = 0
        self.smoothed_fold: Optional[float] = None
        self.fold_smooth_alpha = 0.28
        self.last_timestamp_s: Optional[float] = None
        self.session_start_time: Optional[float] = None
        self._was_complete = False
        self.tabletop_baseline: Optional[float] = None
        self._calibration_frames = 0
        self._calibration_samples: list[float] = []
        self._floor_streak = 0
        self._bad_streak = 0
        self.ready = False
        self._was_ready = False
        self.form_scores: deque[int] = deque(maxlen=SCORE_HISTORY)
        self._last_score_sample_time: Optional[float] = None
        self._pose_entry_grace = 0

    STABLE_FLOOR_FRAMES = 3
    GRACE_FRAMES = 6
    ENTRY_GRACE_FRAMES = 8

    def _is_complete(self) -> bool:
        return (
            self.target_seconds is not None and self.hold_seconds >= self.target_seconds
        )

    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "view_mode": None,
            "ready": self.ready,
            "is_calibrated": self.tabletop_baseline is not None,
            "calibration_progress": min(
                1.0, self._calibration_frames / CALIBRATION_MIN_FRAMES
            ),
            "tabletop_baseline": self.tabletop_baseline,
            "fold_ratio": None,
            "smoothed_fold_ratio": None,
            "chest_fold": None,
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
                "No person detected — get into frame, kneeling on the floor."
            )
            response.update(self._progress_fields())
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]
        l_heel, r_heel = landmarks[LEFT_HEEL], landmarks[RIGHT_HEEL]

        mid_shoulder = _avg_point(l_shoulder, r_shoulder)
        mid_hip = _avg_point(l_hip, r_hip)
        mid_knee = _avg_point(l_knee, r_knee)
        mid_ankle = _avg_point(l_ankle, r_ankle)

        if mid_shoulder is None or mid_hip is None:
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._register_broken_frame()
            response["feedback"] = (
                "Can't see your torso — make sure at least one shoulder and hip are in frame."
            )
            response.update(self._progress_fields())
            return response

        if mid_knee is None or mid_ankle is None:
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._register_broken_frame()
            response["feedback"] = (
                "Can't see your legs clearly — make sure at least one knee and ankle are visible in frame."
            )
            response.update(self._progress_fields())
            return response

        response["pose_detected"] = True

        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)
        shoulder_width = (
            _dist(l_shoulder, r_shoulder)
            if _visible((l_shoulder, r_shoulder))
            else torso_length * 0.6
        )
        shin_length = max(_dist(mid_knee, mid_ankle), 1e-6)
        view_mode = _view_mode(shoulder_width, torso_length)
        response["view_mode"] = view_mode

        mid_heel = _heel_point(l_heel, r_heel, l_ankle, r_ankle)

        bbox_candidates = [
            p
            for p in (
                l_shoulder,
                r_shoulder,
                l_hip,
                r_hip,
                l_knee,
                r_knee,
                l_ankle,
                r_ankle,
            )
            if _visible((p,))
        ]
        bbox_points = [_Point(p.x, p.y) for p in bbox_candidates]
        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        is_floor, is_standing = _assess_floor_stance(mid_knee, mid_ankle, shin_length)

        if is_floor:
            self._floor_streak += 1
            self._bad_streak = 0
        else:
            self._floor_streak = 0
            self._bad_streak += 1

        if self._floor_streak >= self.STABLE_FLOOR_FRAMES:
            self.ready = True
        elif self._bad_streak >= self.GRACE_FRAMES:
            self.ready = False

        if self._was_ready and not self.ready:
            self.tabletop_baseline = None
            self._calibration_frames = 0
            self._calibration_samples = []
        self._was_ready = self.ready

        view_ok = view_mode != "front"
        position_ok = self.ready and view_ok

        if view_mode == "front":
            position_message = "Turn side-on to the camera — Child's Pose needs a side view to track the fold accurately."
        elif is_standing:
            position_message = "Get onto the floor in tabletop position — hands and knees down, back flat."
        elif not self.ready:
            position_message = "Get into tabletop — hands and knees on the floor, back flat — to calibrate."
        else:
            position_message = None

        raw_fold = None
        if mid_heel is not None:
            raw_fold = _dist(mid_hip, mid_heel) / shin_length

        if raw_fold is None:
            response["low_visibility"] = True
            self._register_broken_frame()
            response["feedback"] = (
                "Can't see your heels clearly — make sure your feet are visible in frame."
            )
            response.update(self._progress_fields())
            return response

        if self.smoothed_fold is None:
            self.smoothed_fold = raw_fold
        else:
            self.smoothed_fold = (
                self.fold_smooth_alpha * raw_fold
                + (1 - self.fold_smooth_alpha) * self.smoothed_fold
            )

        chest_fold = (mid_shoulder.y - mid_hip.y) / shin_length

        if (
            position_ok
            and not self.hold_active
            and self._calibration_frames < CALIBRATION_MAX_FRAMES
        ):
            self._calibration_samples.append(self.smoothed_fold)
            self._calibration_frames += 1
            if self._calibration_frames >= CALIBRATION_MIN_FRAMES:
                self.tabletop_baseline = _percentile(self._calibration_samples, 70)

        is_calibrated = self.tabletop_baseline is not None

        pose_threshold = None
        resume_threshold = None
        if is_calibrated:
            pose_threshold = self.tabletop_baseline * POSE_FRACTION
            resume_threshold = self.tabletop_baseline * RESUME_FRACTION

        if self.hold_active:
            fold_broken = False
            if not position_ok:
                fold_broken = True
            elif is_calibrated and self.smoothed_fold > resume_threshold:
                fold_broken = True
            elif not is_floor:
                fold_broken = True
        else:
            if (
                position_ok
                and is_floor
                and self.smoothed_fold <= 1.05
                and chest_fold <= 0.55
            ):
                fold_broken = False
            elif not is_calibrated:
                fold_broken = not (
                    position_ok
                    and is_floor
                    and self.smoothed_fold <= 1.12
                    and chest_fold <= 0.62
                )
            else:
                fold_broken = (
                    self.smoothed_fold > pose_threshold
                    or not is_floor
                    or not position_ok
                )

        holding_now = position_ok and is_floor and not fold_broken

        if holding_now:
            hold_shape_ok = self.smoothed_fold <= 1.12 and chest_fold <= 0.62
            holding_now = holding_now and hold_shape_ok

        issues: list[str] = []
        messages: list[str] = []

        if holding_now:
            if self.smoothed_fold > 0.95:
                issues.append("shallow_fold")
                messages.append(
                    "Sit your hips a little further back toward your heels."
                )
            if chest_fold > 0.70:
                issues.append("chest_not_lowered")
                messages.append("Lower your chest more toward the floor.")

        form_score = None
        hold_quality = None

        if holding_now:
            if not self.hold_active:
                self.current_streak_seconds = 0.0
                self._pose_entry_grace = 0
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
            self._pose_entry_grace = 0

        is_complete = self._is_complete()
        target_reached = is_complete and not self._was_complete
        self._was_complete = is_complete

        feedback = framing_message
        if feedback is None and not position_ok:
            feedback = position_message
        if (
            feedback is None
            and not holding_now
            and not self.started
            and is_floor
            and not is_standing
        ):
            feedback = "Hold the Child's Pose shape a moment — you are close, but I still need a clearer fold and chest drop."
        if feedback is None and not is_calibrated and not holding_now:
            feedback = "Hold a stable kneeling position briefly — calibrating, but do not block a valid pose."
        if feedback is None and fold_broken and not holding_now:
            feedback = "That's not a full Child's Pose yet — sit your hips back onto your heels and lower your chest to the floor."
        if feedback is None and messages:
            feedback = messages[0]
        if feedback is None and target_reached:
            feedback = f"Target reached — {self.target_seconds}s held, nice work!"
        if feedback is None and holding_now:
            feedback = "Great Child's Pose hold — keep breathing and relax into it."
        if feedback is None:
            feedback = "Get back into position to resume the timer."

        response.update(
            {
                "view_mode": view_mode,
                "is_calibrated": is_calibrated,
                "calibration_progress": min(
                    1.0, self._calibration_frames / CALIBRATION_MIN_FRAMES
                ),
                "tabletop_baseline": self.tabletop_baseline,
                "fold_ratio": raw_fold,
                "smoothed_fold_ratio": self.smoothed_fold,
                "chest_fold": chest_fold,
                "hold_state": "holding" if holding_now else "broken",
                "is_holding": holding_now,
                "target_reached": target_reached,
                "hold_quality": hold_quality,
                "posture_ok": len(issues) == 0,
                "posture_issues": issues,
                "posture_messages": messages,
                "form_score": form_score,
                "avg_form_score": self._avg(self.form_scores),
                "feedback": feedback,
            }
        )
        response.update(self._progress_fields())
        return response

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


class ChildsPoseSession:
    def __init__(
        self,
        target_seconds: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = ChildsPoseAnalyzer(target_seconds)
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
