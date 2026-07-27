import math
from collections import deque
from typing import Any, Optional

from src.engines.poseEngine import (
    LEFT_ANKLE,
    LEFT_FOOT_INDEX,
    LEFT_HEEL,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_FOOT_INDEX,
    RIGHT_HEEL,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
)

MIN_LANDMARK_VISIBILITY = 0.30
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)

VALID_SIDES = ("left", "right")
VALID_MODES = ("assisted", "standard", "deep")
DEFAULT_MODE = "standard"

TOP_ANGLE = 170.0
ENTER_DESCENT_ANGLE = {
    "assisted": 160.0,
    "standard": 155.0,
    "deep": 150.0,
}
BOTTOM_ANGLE = {
    "assisted": 120.0,
    "standard": 110.0,
    "deep": 100.0,
}
RETURN_MARGIN = 12.0

MIN_REP_DURATION = 0.20
MAX_REP_DURATION = 15.0
BOTTOM_HOLD_FRAMES = 1

KNEE_TRACK_TOLERANCE = 0.35
PELVIS_LEVEL_TOLERANCE = 0.25
FREE_LEG_FLOOR_TOLERANCE = 0.18

HOP_DISPLACEMENT_THRESHOLD = 0.22
WOBBLE_HISTORY_FRAMES = 15

FRAME_EDGE_MARGIN = 0.02
BBOX_TOO_CLOSE = 0.98
BBOX_TOO_FAR = 0.10


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


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1 for i in CORE_LANDMARKS if getattr(landmarks[i], "visibility", 0.0) > 0.45
    )
    return visible_core >= 2


def _torso_upright_ok(mid_shoulder, mid_hip) -> bool:
    dx = mid_hip.x - mid_shoulder.x
    dy = mid_hip.y - mid_shoulder.y
    angle_from_horizontal = math.degrees(math.atan2(abs(dy), max(abs(dx), 1e-9)))
    return angle_from_horizontal >= 20.0


def _framing_feedback(points: list[_Point]) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — step back so your whole body is visible."
            )

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    w = max(xs) - min(xs)
    h = max(ys) - min(ys)

    if w > BBOX_TOO_CLOSE or h > BBOX_TOO_CLOSE:
        return "You're too close to the camera — step back a little."
    if w < BBOX_TOO_FAR and h < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer."
    return None


class SingleLegSquatAnalyzer:
    def __init__(
        self,
        target_reps: Optional[int] = None,
        side: str = "left",
        mode: str = DEFAULT_MODE,
    ):
        self.target_reps = target_reps
        self.side = side if side in VALID_SIDES else "left"
        self.mode = mode if mode in VALID_MODES else DEFAULT_MODE

        self.stage = "standing"
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        self.smoothed_angle: Optional[float] = None
        self.last_angle: Optional[float] = None
        self.angle_smooth_alpha = 0.40

        self.rep_start_time: Optional[float] = None
        self._current_rep_issues: set[str] = set()
        self._bottom_streak = 0
        self._free_leg_down_streak = 0
        self._rep_had_free_leg_down = False
        self._rep_had_hop = False

        self.session_start_time: Optional[float] = None
        self.ready = True

        self._stance_ankle_history: deque[float] = deque(maxlen=WOBBLE_HISTORY_FRAMES)
        self._last_stance_ankle: Optional[_Point] = None
        self._standing_baseline: Optional[float] = None

    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 6.0:
            return "too_slow"
        if duration >= 3.0:
            return "slow"
        if duration >= 0.8:
            return "good"
        if duration >= 0.35:
            return "fast"
        return "too_fast"

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "ready": self.ready,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "left_reps": self.rep_count if self.side == "left" else 0,
            "right_reps": self.rep_count if self.side == "right" else 0,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "rep_completed": False,
            "rep_classification": None,
            "rep_form_quality": None,
            "current_side": self.side,
            "position_ok": False,
            "position_message": None,
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
            "stance_knee_angle": None,
            "knee_depth_ratio": None,
            "torso_angle": None,
            "knee_tracking_ok": True,
            "pelvis_level": True,
            "balance_confidence": None,
            "support_mode": self.mode,
            "bottom_lock": False,
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = "No person detected — step into frame."
            return response

        response["pose_detected"] = True

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]
        l_heel, r_heel = landmarks[LEFT_HEEL], landmarks[RIGHT_HEEL]
        l_foot, r_foot = landmarks[LEFT_FOOT_INDEX], landmarks[RIGHT_FOOT_INDEX]

        if not _visible((l_shoulder, r_shoulder, l_hip, r_hip)):
            response["low_visibility"] = True
            response["feedback"] = "Can't see your torso clearly — adjust the camera."
            return response

        stance_hip = l_hip if self.side == "left" else r_hip
        stance_knee = l_knee if self.side == "left" else r_knee
        stance_ankle = l_ankle if self.side == "left" else r_ankle
        stance_heel = l_heel if self.side == "left" else r_heel
        stance_foot = l_foot if self.side == "left" else r_foot
        free_ankle = r_ankle if self.side == "left" else l_ankle

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)

        torso_ok = _torso_upright_ok(mid_shoulder, mid_hip)
        bbox_points = [
            _Point(p.x, p.y)
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
        ]
        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        stance_ok = _visible((stance_hip, stance_knee, stance_ankle))
        if not stance_ok and self.smoothed_angle is None:
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see the working leg clearly — adjust the camera."
            )
            return response

        if stance_ok:
            raw_angle = _angle_deg(stance_hip, stance_knee, stance_ankle)
            self.smoothed_angle = (
                raw_angle
                if self.smoothed_angle is None
                else self.angle_smooth_alpha * raw_angle
                + (1 - self.angle_smooth_alpha) * self.smoothed_angle
            )

        if self.smoothed_angle is None:
            response["feedback"] = "Waiting for a clear leg angle."
            return response

        if self._standing_baseline is None and self.smoothed_angle > 155.0:
            self._standing_baseline = self.smoothed_angle

        response["stance_knee_angle"] = round(self.smoothed_angle, 1)

        leg_len = max(_dist(stance_hip, stance_ankle), 1e-6)
        pelvis_level = (
            abs(l_hip.y - r_hip.y) / max(_dist(l_shoulder, r_shoulder), 1e-6)
            <= PELVIS_LEVEL_TOLERANCE
        )
        response["pelvis_level"] = pelvis_level
        response["torso_angle"] = round(90.0, 1) if torso_ok else round(20.0, 1)

        base_angle = self._standing_baseline or TOP_ANGLE
        raw_depth = max(0.0, base_angle - self.smoothed_angle)
        response["knee_depth_ratio"] = round(max(0.0, min(1.0, raw_depth / 80.0)), 2)

        bottom_angle = BOTTOM_ANGLE[self.mode]
        enter_angle = ENTER_DESCENT_ANGLE[self.mode]
        top_angle = TOP_ANGLE

        if self.smoothed_angle <= bottom_angle:
            self._bottom_streak += 1
        else:
            self._bottom_streak = 0
        response["bottom_lock"] = self._bottom_streak >= BOTTOM_HOLD_FRAMES

        knee_tracking_ok = True
        foot_ref = stance_foot if _visible((stance_foot,)) else stance_heel
        if _visible((foot_ref,)):
            drift = abs(stance_knee.x - foot_ref.x) / leg_len
            if drift > KNEE_TRACK_TOLERANCE:
                knee_tracking_ok = False
        response["knee_tracking_ok"] = knee_tracking_ok

        free_leg_down = False
        if _visible((free_ankle, stance_ankle)):
            free_leg_down = (
                abs(free_ankle.y - stance_ankle.y) / leg_len <= FREE_LEG_FLOOR_TOLERANCE
            )
        if free_leg_down:
            self._free_leg_down_streak += 1
        else:
            self._free_leg_down_streak = 0

        hop_detected = False
        if _visible((stance_ankle,)):
            current_pt = _Point(stance_ankle.x, stance_ankle.y)
            if self._last_stance_ankle is not None:
                displacement = _dist(current_pt, self._last_stance_ankle) / leg_len
                if displacement > HOP_DISPLACEMENT_THRESHOLD:
                    hop_detected = True
                self._stance_ankle_history.append(displacement)
            self._last_stance_ankle = current_pt

        recent_wobble = (
            sum(self._stance_ankle_history) / len(self._stance_ankle_history)
            if self._stance_ankle_history
            else 0.0
        )
        response["balance_confidence"] = round(
            max(0.0, min(1.0, 1.0 - recent_wobble / HOP_DISPLACEMENT_THRESHOLD)), 2
        )

        response["position_ok"] = response["framing_ok"]

        rep_completed = False
        rep_duration = None
        rep_class = None
        rep_form_quality = None
        feedback = framing_message

        if not response["position_ok"]:
            self.stage = "standing"
            self.rep_start_time = None
            self._current_rep_issues = set()
            self._rep_had_free_leg_down = False
            self._rep_had_hop = False
            if feedback is None:
                feedback = "Get into a clear standing position before starting."
        else:
            if self.stage == "standing" and self.smoothed_angle < enter_angle:
                self.stage = "descending"
                self.rep_start_time = t
                self._current_rep_issues = set()
                self._rep_had_free_leg_down = False
                self._rep_had_hop = False

            if self.stage in ("descending", "bottom", "rising"):
                if hop_detected:
                    self._rep_had_hop = True
                if self._free_leg_down_streak >= 2 and self.mode != "assisted":
                    self._rep_had_free_leg_down = True
                if not knee_tracking_ok:
                    self._current_rep_issues.add("knee_collapsing")
                if not pelvis_level:
                    self._current_rep_issues.add("hip_dropping")

            if self.stage == "descending" and self.smoothed_angle <= bottom_angle:
                self.stage = "bottom"
            elif (
                self.stage in ("descending", "bottom")
                and self.smoothed_angle > bottom_angle
            ):
                self.stage = "rising"
            elif self.stage == "rising" and self.smoothed_angle >= (
                top_angle - RETURN_MARGIN
            ):
                self.stage = "standing"
                rep_completed = True

            if feedback is None and not knee_tracking_ok:
                feedback = "Keep the knee tracking over your foot."
            if feedback is None and not pelvis_level:
                feedback = "Keep the pelvis level."

            if rep_completed:
                rep_duration = (
                    t - self.rep_start_time if self.rep_start_time is not None else None
                )
                depth_reached = self._bottom_streak >= BOTTOM_HOLD_FRAMES

                valid = (
                    rep_duration is not None
                    and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                    and depth_reached
                )

                if valid:
                    self.rep_count += 1
                    rep_class = self._classify_tempo(rep_duration)
                    if (
                        self._rep_had_hop
                        or self._rep_had_free_leg_down
                        or self._current_rep_issues
                    ):
                        self.flawed_reps += 1
                        rep_form_quality = "needs_improvement"
                        feedback = f"Rep {self.rep_count} counted, but watch your form."
                    else:
                        self.good_reps += 1
                        rep_form_quality = "good"
                        feedback = f"Good rep ({rep_duration:.2f}s)."
                else:
                    feedback = "Rep not counted."

                self.rep_start_time = None
                self._current_rep_issues = set()
                self._rep_had_free_leg_down = False
                self._rep_had_hop = False

        self.last_angle = self.smoothed_angle

        if feedback is None:
            feedback = "Good form — keep going."

        response.update(
            {
                "stage": self.stage,
                "rep_count": self.rep_count,
                "left_reps": self.rep_count if self.side == "left" else 0,
                "right_reps": self.rep_count if self.side == "right" else 0,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "feedback": feedback,
            }
        )
        return response


class SingleLegSquatSession:
    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
        side: str = "left",
        mode: str = DEFAULT_MODE,
    ):
        self.engine = PoseEngine()
        self.analyzer = SingleLegSquatAnalyzer(target_reps, side=side, mode=mode)
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
