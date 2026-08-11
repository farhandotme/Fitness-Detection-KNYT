"""
Battle Rope Cardio Engine & Motion Analyzer.

Features:
  - Rep Counter Core: Tracks alternating wave switches accurately.
  - Wave Amplitude Classification: Detects "big_wave" vs "small_wave".
  - Speed & Tempo Tracking: Tracks peak stroke velocity ("fastest" movement) and RPS.
  - Dict & Object Compatibility: Handles dicts or class landmark objects seamlessly.
"""

import math
from typing import Any, Optional

try:
    from src.engines.poseEngine import (  # type: ignore
        LEFT_ANKLE,
        LEFT_HIP,
        LEFT_KNEE,
        LEFT_SHOULDER,
        LEFT_WRIST,
        PoseEngine,
        RIGHT_ANKLE,
        RIGHT_HIP,
        RIGHT_KNEE,
        RIGHT_SHOULDER,
        RIGHT_WRIST,
    )
except ImportError:
    LEFT_SHOULDER, RIGHT_SHOULDER = 11, 12
    LEFT_HIP, RIGHT_HIP = 23, 24
    LEFT_KNEE, RIGHT_KNEE = 25, 26
    LEFT_ANKLE, RIGHT_ANKLE = 27, 28
    LEFT_WRIST, RIGHT_WRIST = 15, 16

    class PoseEngine:
        def detect(self, frame, timestamp_ms: int):
            return None

        @staticmethod
        def landmarks_to_json(landmarks):
            return []

        def close(self):
            pass


# Thresholds & Calibrations
MIN_LANDMARK_VISIBILITY = 0.40
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)

MIN_STANDING_INCLINE_DEG = 25.0
KNEE_BENT_MAX_DEG = 168.0
STANCE_MIN_RATIO = 0.85
TORSO_LEAN_FLAW_MAX_DEG = 50.0

WAVE_DIFF_ENTER = 0.35
BIG_WAVE_THRESHOLD = 0.65
CONFIRM_FRAMES = 1

FASTEST_TEMPO_MAX_S = 0.22
FAST_TEMPO_MAX_S = 0.40
MODERATE_TEMPO_MAX_S = 0.75
MIN_REP_DURATION = 0.08
MAX_REP_DURATION = 3.00

FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.97
BBOX_TOO_FAR = 0.10


def _get_val(obj: Any, key: str, default: float = 0.0) -> float:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return float(obj.get(key, default))
    return float(getattr(obj, key, default))


def _get_vis(obj: Any) -> float:
    if obj is None:
        return 0.0
    if isinstance(obj, dict):
        v = obj.get("visibility", 1.0)
        return float(v) if v is not None else 1.0
    v = getattr(obj, "visibility", 1.0)
    return float(v) if v is not None else 1.0


def _looks_like_a_person(landmarks) -> bool:
    if not landmarks or len(landmarks) < 12:
        return False
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if i < len(landmarks) and _get_vis(landmarks[i]) > 0.60
    )
    return visible_core >= 3


def _visible(points) -> bool:
    for p in points:
        if p is None or _get_vis(p) < MIN_LANDMARK_VISIBILITY:
            return False
    return True


class _Point:
    __slots__ = ("x", "y")

    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y


def _midpoint(a, b) -> _Point:
    return _Point(
        (_get_val(a, "x") + _get_val(b, "x")) / 2.0,
        (_get_val(a, "y") + _get_val(b, "y")) / 2.0,
    )


def _dist(a, b) -> float:
    ax, ay = _get_val(a, "x"), _get_val(a, "y")
    bx, by = _get_val(b, "x"), _get_val(b, "y")
    return math.hypot(ax - bx, ay - by)


def _angle_at(a, b, c) -> Optional[float]:
    ax, ay = _get_val(a, "x"), _get_val(a, "y")
    bx, by = _get_val(b, "x"), _get_val(b, "y")
    cx, cy = _get_val(c, "x"), _get_val(c, "y")

    first = (ax - bx, ay - by)
    second = (cx - bx, cy - by)
    first_len = math.hypot(*first)
    second_len = math.hypot(*second)
    if first_len < 1e-7 or second_len < 1e-7:
        return None
    cosine = (first[0] * second[0] + first[1] * second[1]) / (first_len * second_len)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _torso_vertical_incline_deg(
    mid_shoulder: _Point, mid_hip: _Point
) -> Optional[float]:
    dx = mid_hip.x - mid_shoulder.x
    dy = mid_hip.y - mid_shoulder.y
    if dx == 0 and dy == 0:
        return None
    return math.degrees(math.atan2(abs(dy), max(abs(dx), 1e-9)))


def _framing_feedback(points: list) -> Optional[str]:
    for p in points:
        px = _get_val(p, "x")
        py = _get_val(p, "y")
        if (
            px < FRAME_EDGE_MARGIN
            or px > 1.0 - FRAME_EDGE_MARGIN
            or py < FRAME_EDGE_MARGIN
            or py > 1.0 - FRAME_EDGE_MARGIN
        ):
            return "You're partly out of frame — step back so your full body and hands stay visible."

    if len(points) < 4:
        return None

    xs = [_get_val(p, "x") for p in points]
    ys = [_get_val(p, "y") for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if height > BBOX_TOO_CLOSE or width > BBOX_TOO_CLOSE:
        return "You're too close to the camera — step back so your whole body fits."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


def _classify_tempo(duration: float) -> str:
    if duration <= FASTEST_TEMPO_MAX_S:
        return "fastest"
    if duration <= FAST_TEMPO_MAX_S:
        return "fast"
    if duration <= MODERATE_TEMPO_MAX_S:
        return "moderate"
    return "slow"


class BattleRopeCardioAnalyzer:
    """Stateful Rep Counter & Motion Analyzer for Battle Ropes."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.stage = "ready"
        self.ready = False

        self.session_start_time: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None
        self.last_switch_time: Optional[float] = None

        self.fastest_rep_duration: Optional[float] = None
        self.fastest_wave_speed_rps: Optional[float] = None

        self.lead: Optional[str] = None
        self._pending_lead: Optional[str] = None
        self._pending_streak = 0
        self._peak_wave_diff = 0.0

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "position_ok": False,
            "position_message": None,
            "ready": self.ready,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_duration": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "wave_size": None,
            "current_wave_amplitude": None,
            "fastest_rep_duration": (
                round(self.fastest_rep_duration, 3)
                if self.fastest_rep_duration
                else None
            ),
            "fastest_wave_speed_rps": (
                round(self.fastest_wave_speed_rps, 2)
                if self.fastest_wave_speed_rps
                else None
            ),
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
            "lead_arm": self.lead,
            "knee_angle": None,
            "stance_ratio": None,
            "torso_incline": None,
        }

        self.last_timestamp_s = t

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = (
                "No person detected — stand facing the camera with your whole body visible."
            )
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
        arms_visible = _visible((l_wrist, r_wrist))
        legs_visible = _visible((l_knee, r_knee, l_ankle, r_ankle))

        if not torso_visible or not arms_visible or not legs_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your body clearly — step back so hands and feet are in frame."
            )
            return response

        response["pose_detected"] = True

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)
        shoulder_width = max(_dist(l_shoulder, r_shoulder), 1e-6)
        ankle_dist = _dist(l_ankle, r_ankle)
        stance_ratio = ankle_dist / shoulder_width

        ls_y, rs_y = _get_val(l_shoulder, "y"), _get_val(r_shoulder, "y")
        lw_y, rw_y = _get_val(l_wrist, "y"), _get_val(r_wrist, "y")

        left_wave = (ls_y - lw_y) / torso_length
        right_wave = (rs_y - rw_y) / torso_length
        wave_diff = left_wave - right_wave

        left_knee_angle = _angle_at(l_hip, l_knee, l_ankle)
        right_knee_angle = _angle_at(r_hip, r_knee, r_ankle)
        knee_angles = [a for a in (left_knee_angle, right_knee_angle) if a is not None]
        knee_angle = sum(knee_angles) / len(knee_angles) if knee_angles else None

        torso_incline = _torso_vertical_incline_deg(mid_shoulder, mid_hip)

        framing_points = [
            l_shoulder,
            r_shoulder,
            l_hip,
            r_hip,
            l_knee,
            r_knee,
            l_ankle,
            r_ankle,
        ]
        framing_message = _framing_feedback(framing_points)
        framing_ok = framing_message is None

        is_standing = (
            torso_incline is not None and torso_incline >= MIN_STANDING_INCLINE_DEG
        )
        position_ok = framing_ok and is_standing
        self.ready = position_ok

        response.update(
            {
                "position_ok": position_ok,
                "ready": self.ready,
                "framing_ok": framing_ok,
                "framing_message": framing_message,
                "knee_angle": round(knee_angle, 1) if knee_angle is not None else None,
                "stance_ratio": round(stance_ratio, 3),
                "torso_incline": (
                    round(torso_incline, 1) if torso_incline is not None else None
                ),
                "current_wave_amplitude": round(abs(wave_diff), 3),
            }
        )

        if not position_ok:
            response["position_message"] = (
                "Get into an athletic stance facing the camera to start."
            )
            response["feedback"] = (
                framing_message or "Stand tall in frame with feet wide and knees soft."
            )
            return response

        self._peak_wave_diff = max(self._peak_wave_diff, abs(wave_diff))

        if wave_diff >= WAVE_DIFF_ENTER:
            candidate_lead = "left"
        elif wave_diff <= -WAVE_DIFF_ENTER:
            candidate_lead = "right"
        else:
            candidate_lead = None

        if candidate_lead is not None and candidate_lead == self._pending_lead:
            self._pending_streak += 1
        elif candidate_lead is not None:
            self._pending_lead = candidate_lead
            self._pending_streak = 1

        rep_completed = False
        rep_duration = None
        rep_class = None
        rep_quality = None
        wave_size = None
        feedback = framing_message

        if (
            candidate_lead is not None
            and self._pending_streak >= CONFIRM_FRAMES
            and candidate_lead != self.lead
        ):
            if self.lead is not None and self.last_switch_time is not None:
                rep_duration = t - self.last_switch_time

                if MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION:
                    rep_completed = True
                    self.rep_count += 1
                    self.stage = "waving"

                    rep_class = _classify_tempo(rep_duration)
                    wave_speed_rps = 1.0 / rep_duration

                    if (
                        self.fastest_rep_duration is None
                        or rep_duration < self.fastest_rep_duration
                    ):
                        self.fastest_rep_duration = rep_duration
                        self.fastest_wave_speed_rps = wave_speed_rps

                    if self._peak_wave_diff >= BIG_WAVE_THRESHOLD:
                        wave_size = "big_wave"
                    else:
                        wave_size = "small_wave"

                    posture_flaws = []
                    if knee_angle is not None and knee_angle >= KNEE_BENT_MAX_DEG:
                        posture_flaws.append("locked_knees")
                    if stance_ratio < STANCE_MIN_RATIO:
                        posture_flaws.append("narrow_stance")
                    if (
                        torso_incline is not None
                        and torso_incline < TORSO_LEAN_FLAW_MAX_DEG
                    ):
                        posture_flaws.append("hunching")

                    if wave_size == "big_wave" and not posture_flaws:
                        rep_quality = "good"
                        self.good_reps += 1
                        if rep_class == "fastest":
                            feedback = f"🔥 Fastest Wave! Rep {self.rep_count} — Big amplitude & explosive speed!"
                        else:
                            feedback = f"Great Wave! Rep {self.rep_count} — Excellent full extension."
                    else:
                        rep_quality = "needs_improvement"
                        self.flawed_reps += 1
                        if wave_size == "small_wave":
                            feedback = f"Rep {self.rep_count} counted — Drive your hands higher for a bigger wave."
                        elif "locked_knees" in posture_flaws:
                            feedback = f"Rep {self.rep_count} counted — Bend your knees into an athletic stance."
                        else:
                            feedback = f"Rep {self.rep_count} counted — Keep chest tall and stance wide."

            self.lead = candidate_lead
            self.last_switch_time = t
            self._peak_wave_diff = abs(wave_diff)

        if feedback is None:
            if self.rep_count == 0:
                feedback = "Start waving — drive one arm up while the other comes down!"
            else:
                feedback = "Keep the rhythm going — big, fast waves!"

        response.update(
            {
                "stage": self.stage,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_duration": round(rep_duration, 3) if rep_duration else None,
                "rep_classification": rep_class,
                "rep_form_quality": rep_quality,
                "wave_size": wave_size,
                "fastest_rep_duration": (
                    round(self.fastest_rep_duration, 3)
                    if self.fastest_rep_duration
                    else None
                ),
                "fastest_wave_speed_rps": (
                    round(self.fastest_wave_speed_rps, 2)
                    if self.fastest_wave_speed_rps
                    else None
                ),
                "feedback": feedback,
                "lead_arm": self.lead,
            }
        )
        return response


class BattleRopeCardioSession:
    """Full Battle Rope Cardio Session wrapper."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = BattleRopeCardioAnalyzer(target_reps)
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
