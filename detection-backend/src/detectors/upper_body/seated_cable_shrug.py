"""
Seated Cable Row rep counting + posture correction.

Design
------
`SeatedCableRowAnalyzer` tracks the cyclical pulling motion of the elbows
and wrists relative to the torso, using EMA smoothing to eliminate landmark jitter.
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_EAR,
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_SHOULDER,
    LEFT_WRIST,
    NOSE,
    PoseEngine,
    RIGHT_EAR,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)

MIN_LANDMARK_VISIBILITY = 0.4
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 3


UPRIGHT_MIN_DEG = 50.0
STABLE_SEATED_FRAMES = 5
GRACE_FRAMES = 20

HIP_DRIFT_MAX_RATIO = 0.40

CALIBRATION_MIN_FRAMES = 30
CALIBRATION_MAX_FRAMES = 90
CALIBRATION_MIN_SAMPLES = 15

# Row thresholds based on elbow angle or extension ratio
# Extended (arms out) vs Contracted (pulled back)
EXTENDED_ANGLE_THRESHOLD = 150.0
PULLED_ANGLE_THRESHOLD = 110.0

CONFIRM_FRAMES = 3
MIN_REP_DURATION = 0.6
MAX_REP_DURATION = 12.0

TORSO_LEAN_FLAW_DEG = 25.0
ROUND_BACK_THRESHOLD = 0.15

FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.95
BBOX_TOO_FAR = 0.15


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


def _torso_vertical_incline_deg(mid_shoulder, mid_hip) -> Optional[float]:
    dx = mid_hip.x - mid_shoulder.x
    dy = mid_hip.y - mid_shoulder.y
    if dx == 0 and dy == 0:
        return None
    return math.degrees(math.atan2(abs(dy), max(abs(dx), 1e-9)))


def _torso_signed_lean_deg(mid_shoulder, mid_hip) -> float:
    dx = mid_shoulder.x - mid_hip.x
    dy = mid_hip.y - mid_hip.y  # reference alignment
    return math.degrees(math.atan2(dx, max(mid_hip.y - mid_shoulder.y, 1e-9)))


def _framing_feedback(points: list[_Point]) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return "You're partly out of frame — reposition so your upper body and arms are visible."

    if len(points) < 4:
        return None

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "You're too close to the camera — back up so your full upper body fits."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class SeatedCableRowAnalyzer:
    """Stateful seated-cable-row rep counter with EMA smoothing and auto-calibration."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        self.phase = "extended"  # "extended" (arms out) or "pulled" (handle at chest)
        self._pending_phase: Optional[str] = None
        self._pending_streak = 0

        self.rep_start_time: Optional[float] = None
        self.session_start_time: Optional[float] = None
        self.last_t_s: Optional[float] = None

        self._seated_streak = 0
        self._bad_streak = 0
        self._visibility_bad_streak = 0
        self.ready = False
        self.seated_hip_anchor: Optional[_Point] = None
        self.seated_shoulder_width: Optional[float] = None

        self._calibrating = True
        self._calibration_frame_count = 0
        self._calibration_samples: list[float] = []
        self.smoothed_elbow_angle: Optional[float] = None

        self._rep_max_lean_delta: float = 0.0
        self._rep_start_lean_deg: Optional[float] = None
        self._rep_broke_position = False

    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 6.0:
            return "too_slow"
        if duration >= 2.5:
            return "slow"
        if duration >= 1.0:
            return "good"
        if duration >= MIN_REP_DURATION:
            return "fast"
        return "too_fast"

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _reset_calibration(self):
        self._calibrating = True
        self._calibration_frame_count = 0
        self._calibration_samples = []
        self.smoothed_elbow_angle = None

    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        dt_s = (t - self.last_t_s) if self.last_t_s is not None else 0.033
        dt_s = max(0.001, dt_s)
        self.last_t_s = t

        response: dict[str, Any] = {
            "pose_detected": False,
            "position_ok": False,
            "position_message": None,
            "ready": self.ready,
            "calibrating": self._calibrating,
            "calibration_progress": (
                round(
                    min(1.0, len(self._calibration_samples) / CALIBRATION_MIN_SAMPLES),
                    2,
                )
                if self._calibrating
                else 1.0
            ),
            "elbow_angle": None,
            "row_progress": None,
            "phase": self.phase,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_duration": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "rep_flaws": [],
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            self._visibility_bad_streak += 1
            if self._visibility_bad_streak >= GRACE_FRAMES:
                self._invalidate_in_progress_rep()
                self.ready = False
            response["feedback"] = (
                "No person detected — sit facing the cable machine with your upper body visible."
            )
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]

        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
        arms_visible = _visible((l_shoulder, l_elbow, l_wrist)) or _visible(
            (r_shoulder, r_elbow, r_wrist)
        )

        if not torso_visible or not arms_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._visibility_bad_streak += 1
            if self._visibility_bad_streak >= GRACE_FRAMES:
                self._invalidate_in_progress_rep()
                self.ready = False
            response["feedback"] = (
                "Can't see your torso or arms clearly — adjust your camera angle."
            )
            return response

        response["pose_detected"] = True
        self._visibility_bad_streak = 0

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        shoulder_width = max(_dist(l_shoulder, r_shoulder), 1e-6)

        torso_vertical_incline = _torso_vertical_incline_deg(mid_shoulder, mid_hip)
        signed_lean = _torso_signed_lean_deg(mid_shoulder, mid_hip)

        bbox_candidates = [
            p
            for p in (
                l_shoulder,
                r_shoulder,
                l_hip,
                r_hip,
                l_elbow,
                r_elbow,
                l_wrist,
                r_wrist,
            )
            if _visible((p,))
        ]
        bbox_points = [_Point(p.x, p.y) for p in bbox_candidates]
        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        is_upright = (
            torso_vertical_incline is not None
            and torso_vertical_incline >= UPRIGHT_MIN_DEG
        )
        hip_stable = True
        if self.seated_hip_anchor is not None and self.seated_shoulder_width:
            hip_drift = _dist(mid_hip, self.seated_hip_anchor)
            hip_stable = hip_drift <= HIP_DRIFT_MAX_RATIO * self.seated_shoulder_width

        is_seated_ok = is_upright and hip_stable
        if is_seated_ok:
            self._seated_streak += 1
            self._bad_streak = 0
        else:
            self._seated_streak = 0
            self._bad_streak += 1

        if self._seated_streak >= STABLE_SEATED_FRAMES:
            if not self.ready:
                self.seated_hip_anchor = mid_hip
                self.seated_shoulder_width = shoulder_width
                if self._calibrating:
                    self._reset_calibration()
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES:
            if self.ready:
                self._invalidate_in_progress_rep()
            self.ready = False

        response["position_ok"] = self.ready
        response["ready"] = self.ready

        if not self.ready:
            response["position_message"] = (
                "Sit upright on the bench, feet planted, arms extended holding the handle."
            )
            response["feedback"] = response["position_message"]
            return response

        # Compute average elbow angle
        angles = []
        if _visible((l_shoulder, l_elbow, l_wrist)):
            angles.append(_angle_deg(l_shoulder, l_elbow, l_wrist))
        if _visible((r_shoulder, r_elbow, r_wrist)):
            angles.append(_angle_deg(r_shoulder, r_elbow, r_wrist))

        if not angles:
            response["feedback"] = "Keep your arms visible to track the row motion."
            return response

        raw_elbow_angle = sum(angles) / len(angles)

        # EMA smoothing for stable tracking
        alpha_smooth = 1.0 - math.exp(-dt_s / 0.08)
        if self.smoothed_elbow_angle is None:
            self.smoothed_elbow_angle = raw_elbow_angle
        else:
            self.smoothed_elbow_angle += alpha_smooth * (
                raw_elbow_angle - self.smoothed_elbow_angle
            )

        elbow_angle = self.smoothed_elbow_angle
        response["elbow_angle"] = round(elbow_angle, 1)

        # Calibration stage
        if self._calibrating:
            self._calibration_frame_count += 1
            self._calibration_samples.append(elbow_angle)

            done_enough = (
                len(self._calibration_samples) >= CALIBRATION_MIN_SAMPLES
                and self._calibration_frame_count >= CALIBRATION_MIN_FRAMES
            )
            timed_out = self._calibration_frame_count >= CALIBRATION_MAX_FRAMES

            if done_enough or timed_out:
                self._calibrating = False

            response["calibrating"] = self._calibrating
            response["calibration_progress"] = round(
                min(1.0, len(self._calibration_samples) / CALIBRATION_MIN_SAMPLES), 2
            )

            if self._calibrating:
                response["feedback"] = (
                    "Calibrating — hold your arms extended in the starting position."
                )
                return response

        # Progress calculation (0.0 = fully extended, 1.0 = fully pulled)
        max_angle = 165.0
        min_angle = 85.0
        row_progress = max(
            0.0, min(1.0, (max_angle - elbow_angle) / max(1.0, max_angle - min_angle))
        )
        response["row_progress"] = round(row_progress, 2)

        # Track posture/cheating form flaws during pull
        if self.phase == "pulled" or self._pending_phase == "pulled":
            if self._rep_start_lean_deg is not None:
                lean_delta = abs(signed_lean - self._rep_start_lean_deg)
                self._rep_max_lean_delta = max(self._rep_max_lean_delta, lean_delta)

        if not hip_stable:
            self._rep_broke_position = True

        # State machine mapping
        if elbow_angle <= PULLED_ANGLE_THRESHOLD:
            candidate_phase = "pulled"
        elif elbow_angle >= EXTENDED_ANGLE_THRESHOLD:
            candidate_phase = "extended"
        else:
            candidate_phase = None

        feedback = framing_message
        rep_completed = False
        rep_duration = rep_class = rep_form_quality = None
        rep_flaws: list[str] = []

        if candidate_phase is not None and candidate_phase == self._pending_phase:
            self._pending_streak += 1
        elif candidate_phase is not None:
            self._pending_phase = candidate_phase
            self._pending_streak = 1
        else:
            self._pending_phase = None
            self._pending_streak = 0

        if (
            candidate_phase is not None
            and self._pending_streak >= CONFIRM_FRAMES
            and candidate_phase != self.phase
        ):
            if candidate_phase == "pulled":
                self.phase = "pulled"
                if self.rep_start_time is None:
                    self.rep_start_time = t
                self._rep_start_lean_deg = signed_lean
                self._rep_max_lean_delta = 0.0
                self._rep_broke_position = False
                feedback = "Handle pulled to chest — squeeze your back muscles, then extend forward."
            else:
                if self.phase == "pulled":
                    duration = (
                        (t - self.rep_start_time)
                        if self.rep_start_time is not None
                        else None
                    )
                    valid = (
                        duration is not None
                        and MIN_REP_DURATION <= duration <= MAX_REP_DURATION
                    )

                    if valid:
                        self.rep_count += 1
                        rep_completed = True
                        rep_duration = duration
                        rep_class = self._classify_tempo(duration)

                        if self._rep_max_lean_delta > TORSO_LEAN_FLAW_DEG:
                            rep_flaws.append("excessive_leaning")
                        if self._rep_broke_position:
                            rep_flaws.append("shifting_body")

                        if rep_flaws:
                            rep_form_quality = "needs_improvement"
                            self.flawed_reps += 1
                            flaw_text = {
                                "excessive_leaning": "avoid swinging your torso — keep your chest proud and still",
                                "shifting_body": "plant your feet and keep your lower body stable",
                            }
                            feedback = f"Rep {self.rep_count} counted, but {flaw_text[rep_flaws[0]]}."
                        else:
                            rep_form_quality = "good"
                            self.good_reps += 1
                            feedback = (
                                f"Clean row ({duration:.2f}s). Rep {self.rep_count}."
                            )
                    else:
                        feedback = (
                            "Too fast — control the movement."
                            if duration is not None and duration < MIN_REP_DURATION
                            else "Not counted — complete a full extension and pull."
                        )

                    self.rep_start_time = None

                self.phase = "extended"

        if feedback is None:
            if self.phase == "pulled":
                feedback = "Extend your arms fully forward."
            else:
                feedback = (
                    "Pull the handle smoothly back toward your lower chest/abdomen."
                )

        response.update(
            {
                "phase": self.phase,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_duration": rep_duration,
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "rep_flaws": rep_flaws,
                "feedback": feedback,
            }
        )
        return response

    def _invalidate_in_progress_rep(self):
        self._pending_phase = None
        self._pending_streak = 0
        self.rep_start_time = None
        self._rep_start_lean_deg = None
        self._rep_max_lean_delta = 0.0
        self._rep_broke_position = False
        self.phase = "extended"


class SeatedCableRowSession:
    """Session coordinator: shared pose model + row analyzer."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = SeatedCableRowAnalyzer(target_reps)
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
