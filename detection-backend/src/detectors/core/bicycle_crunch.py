"""
Bicycle Crunch Analyzer — Direct Left-to-Right High-Velocity Version.

Optimizations for fast execution:
  - Direct Left <-> Right state switching (no neutral 'center' phase required).
  - Low-latency signal smoothing (0.88 raw signal weight).
  - Dynamic adaptive envelope tolerance for fast, shallow reps.
  - Complete Schema compliance with standard frontend UI.
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_EAR,
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    LEFT_WRIST,
    NOSE,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_EAR,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)

# -------------------------------------------------------------------------
# Calibrated Constants for High-Speed Motion
# -------------------------------------------------------------------------

MIN_LANDMARK_VISIBILITY = 0.20  # Tolerates severe motion blur on fast limbs
REQUIRED_LANDMARKS = (
    LEFT_SHOULDER,
    RIGHT_SHOULDER,
    LEFT_HIP,
    RIGHT_HIP,
)
CORE_VISIBILITY_MIN = 0.20

# Low-Latency Signal Filtering
ANGLE_SMOOTH_ALPHA = 0.88  # 88% raw frame weight prevents lag at high speeds

# Dynamic Envelope & Crossover Thresholds
ENVELOPE_DECAY = 0.950  # Rapid envelope decay adjusts quickly to shallow reps
ENVELOPE_MIN = 0.10  # Lower floor accepts smaller crossovers
ENVELOPE_MAX = 1.20

ENTER_FRACTION = 0.28  # Lower fraction triggers phase earlier in the stroke
EXIT_FRACTION = 0.10
PARTIAL_FRACTION = 0.08

ENTER_FLOOR = 0.05
EXIT_FLOOR = 0.02
PARTIAL_FLOOR = 0.015

# Coaching Advisories
HANDS_NEAR_HEAD_MAX = 0.90
KNEES_RAISED_MARGIN = 0.30
LEG_ALT_MIN_DIFF = 0.06  # Tolerates reduced leg extension during fast pedaling

# Camera Framing Parameters
FRAME_EDGE_MARGIN = 0.02
BBOX_TOO_CLOSE = 0.98
BBOX_TOO_FAR = 0.08


class _Point:
    __slots__ = ("x", "y")

    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y


def _midpoint(a, b) -> _Point:
    return _Point((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)


def _visible(points, min_vis: float = MIN_LANDMARK_VISIBILITY) -> bool:
    for p in points:
        if p is None:
            return False
        v = getattr(p, "visibility", None)
        if v is not None and v < min_vis:
            return False
    return True


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _bbox_points(points: list[_Point]) -> Optional[tuple[float, float, float, float]]:
    if not points:
        return None
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    return min(xs), max(xs), min(ys), max(ys)


def _framing_feedback(points: list[_Point]) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — step back so your full body is visible."
            )

    box = _bbox_points(points)
    if box is None:
        return None
    min_x, max_x, min_y, max_y = box
    width, height = max_x - min_x, max_y - min_y

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "You're too close to the camera — back up so your whole body fits."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."
    return None


def _classify_speed(duration: Optional[float]) -> str:
    """Classifies movement speed based on stroke duration."""
    if duration is None or duration <= 0.30:
        return "Very Fast"
    if duration <= 0.50:
        return "Fast"
    if duration <= 0.85:
        return "Moderate"
    return "Slow"


class BicycleCrunchAnalyzer:
    """High-velocity Bicycle Crunch analyzer with direct left/right switching."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        # Phase tracking ("center" | "left" | "right")
        self.phase = "center"
        self._last_counted_side: Optional[str] = None
        self._touch_count = 0

        self.smoothed_signal: Optional[float] = None
        self._envelope = ENVELOPE_MIN

        # Standard Rep Counters
        self.left_count = 0
        self.right_count = 0
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        # Timing and Metrics
        self.last_phase_time: Optional[float] = None
        self.ready = True
        self.last_rep_summary: Optional[str] = None
        self.last_rep_duration: Optional[float] = None
        self.last_speed_label: str = "-"
        self.session_start_time: Optional[float] = None

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "ready": True,
            "stance_ok": True,
            "base_ok": True,
            "base_message": None,
            "framing_ok": True,
            "framing_message": None,
            "alignment": "Good Setup",
            # Crunch Signals
            "crunch_signal": None,
            "raw_crunch_signal": None,
            "signal_envelope": None,
            "phase": self.phase,
            # Standard Rep Counts
            "left_count": self.left_count,
            "right_count": self.right_count,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "target_reps": self.target_reps,
            # Standard UI Metric Parameters
            "rep_completed": False,
            "side_completed": False,
            "side_completed_which": None,
            "rep_duration": self.last_rep_duration,
            "rep_form_quality": None,
            "speed": self.last_speed_label,
            "last_rep": self.last_rep_summary or "-",
            "legs_alternating": True,
            "legs_visible": False,
            "leg_message": None,
            "low_visibility": False,
            "feedback": None,
            "session_complete": self._is_complete(),
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None:
            response["feedback"] = "No person detected — step into frame."
            response["alignment"] = "Off Screen"
            return response

        required_ok = all(
            landmarks[i].visibility is not None
            and landmarks[i].visibility > CORE_VISIBILITY_MIN
            for i in REQUIRED_LANDMARKS
        )
        if not required_ok:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your torso clearly — adjust camera so "
                "shoulders and hips are visible."
            )
            response["alignment"] = "Poor Visibility"
            return response

        response["pose_detected"] = True

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]
        l_ear, r_ear = landmarks[LEFT_EAR], landmarks[RIGHT_EAR]
        nose = landmarks[NOSE]

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)

        bbox_candidates = [
            _Point(p.x, p.y)
            for p in (
                l_shoulder,
                r_shoulder,
                l_hip,
                r_hip,
                l_elbow,
                r_elbow,
                l_knee,
                r_knee,
                l_ankle,
                r_ankle,
            )
            if _visible((p,))
        ]
        framing_message = _framing_feedback(bbox_candidates)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        # Coaching Advisories
        head_ref = (
            nose
            if _visible((nose,))
            else (_midpoint(l_ear, r_ear) if _visible((l_ear, r_ear)) else None)
        )
        hands_near_head = True
        if head_ref is not None and _visible((l_wrist, r_wrist)):
            l_hand_dist = _dist(l_wrist, head_ref) / torso_length
            r_hand_dist = _dist(r_wrist, head_ref) / torso_length
            hands_near_head = min(l_hand_dist, r_hand_dist) <= HANDS_NEAR_HEAD_MAX

        knees_raised = (
            mid_hip.y - _midpoint(l_knee, r_knee).y
        ) > -KNEES_RAISED_MARGIN * torso_length

        if not knees_raised:
            base_advisory_message = "Lift knees higher toward chest."
        elif not hands_near_head:
            base_advisory_message = "Keep hands up near your head."
        else:
            base_advisory_message = None

        response["base_message"] = base_advisory_message

        # Calculate Crossover Signal (d_L2R - d_R2L)
        d_r2l = _dist(r_elbow, l_knee) / torso_length
        d_l2r = _dist(l_elbow, r_knee) / torso_length
        raw_signal = (
            d_l2r - d_r2l
        )  # Positive = Left side touch (Right elbow -> Left knee)

        if self.smoothed_signal is None:
            self.smoothed_signal = raw_signal
        else:
            self.smoothed_signal = (
                ANGLE_SMOOTH_ALPHA * raw_signal
                + (1.0 - ANGLE_SMOOTH_ALPHA) * self.smoothed_signal
            )

        response["raw_crunch_signal"] = round(raw_signal, 3)
        response["crunch_signal"] = round(self.smoothed_signal, 3)

        # Dynamic Envelope Calculation
        self._envelope = max(abs(self.smoothed_signal), self._envelope * ENVELOPE_DECAY)
        self._envelope = max(ENVELOPE_MIN, min(ENVELOPE_MAX, self._envelope))
        response["signal_envelope"] = round(self._envelope, 3)

        enter = max(ENTER_FLOOR, ENTER_FRACTION * self._envelope)
        exit_ = max(EXIT_FLOOR, EXIT_FRACTION * self._envelope)

        # Safe Leg Extension Evaluation
        legs_visible = _visible((l_ankle, r_ankle))
        l_leg_ext = _dist(l_hip, l_ankle) / torso_length if legs_visible else None
        r_leg_ext = _dist(r_hip, r_ankle) / torso_length if legs_visible else None
        response["legs_visible"] = legs_visible

        feedback = framing_message
        sig = self.smoothed_signal

        # -----------------------------------------------------------------
        # DIRECT LEFT <-> RIGHT STATE MACHINE (No Center Pause Required)
        # -----------------------------------------------------------------
        side_detected = None

        if sig >= enter and self._last_counted_side != "left":
            side_detected = "left"
        elif sig <= -enter and self._last_counted_side != "right":
            side_detected = "right"

        if side_detected is not None:
            self.phase = side_detected
            self._last_counted_side = side_detected

            side_duration = (t - self.last_phase_time) if self.last_phase_time else 0.20
            self.last_phase_time = t

            legs_alternating = True
            if legs_visible and l_leg_ext is not None and r_leg_ext is not None:
                extending_leg, crunching_leg = (
                    (r_leg_ext, l_leg_ext)
                    if side_detected == "left"
                    else (l_leg_ext, r_leg_ext)
                )
                legs_alternating = (extending_leg - crunching_leg) >= LEG_ALT_MIN_DIFF

            response["legs_alternating"] = legs_alternating
            response["side_completed"] = True
            response["side_completed_which"] = side_detected

            if side_detected == "left":
                self.left_count += 1
            else:
                self.right_count += 1

            self._touch_count += 1
            self.last_rep_duration = round(side_duration, 2)
            self.last_speed_label = _classify_speed(side_duration)

            # Every 2 touches = 1 Full Pair Rep
            if self._touch_count % 2 == 0:
                self.rep_count += 1
                response["rep_completed"] = True

                if legs_alternating:
                    self.good_reps += 1
                    response["rep_form_quality"] = "good"
                    feedback = f"Rep {self.rep_count} — great fast pace!"
                    self.last_rep_summary = f"Good Rep {self.rep_count}"
                else:
                    self.flawed_reps += 1
                    response["rep_form_quality"] = "needs_improvement"
                    feedback = f"Rep {self.rep_count} counted — extend non-crunching leg further."
                    self.last_rep_summary = f"Shallow Rep {self.rep_count}"
            else:
                feedback = f"{side_detected.capitalize()} side — now switch sides!"

        # Visual indicator update when resting in neutral
        elif abs(sig) < exit_:
            self.phase = "center"

        # Final Response Data Sync
        response["phase"] = self.phase
        response["left_count"] = self.left_count
        response["right_count"] = self.right_count
        response["rep_count"] = self.rep_count
        response["good_reps"] = self.good_reps
        response["flawed_reps"] = self.flawed_reps
        response["rep_duration"] = self.last_rep_duration
        response["speed"] = self.last_speed_label
        response["last_rep"] = self.last_rep_summary or "-"

        if feedback is None:
            feedback = "Keep pedaling — drive opposite elbow to knee."

        response["feedback"] = feedback
        response["session_complete"] = self._is_complete()
        return response


class BicycleCrunchSession:
    """Session wrapper for Bicycle Crunch Analysis."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = BicycleCrunchAnalyzer(target_reps)
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
