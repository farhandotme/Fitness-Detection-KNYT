"""
Mountain Climber Analyzer — High-Velocity & Fast-Turnover Optimized Version.

Fixes for fast movement:
  - Dynamic inflection-point detection (counts reps even with low camera FPS).
  - High-tempo stance tolerance (prevents hip bouncing from dropping stance readiness).
  - Low-latency 0.90/0.10 EMA angle processing with single-frame peak memory.
  - Complete schema compatibility with standard frontend UI.
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

# -------------------------------------------------------------------------
# Calibrated Constants for Fast Motion
# -------------------------------------------------------------------------

MIN_LANDMARK_VISIBILITY = 0.18  # Tolerates motion blur on fast legs
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)

# Knee drive triggers (Shoulder-Hip-Knee angle)
DRIVEN_ANGLE_TRIGGER = 145.0  # Knee initiates tuck toward chest
RETURN_ANGLE_TRIGGER = 142.0  # Leg extends back toward plank
MIN_ANGLE_TRAVEL = 8.0  # Minimum hip flexion travel required (degrees)

# Fast drive timing limits
MIN_DRIVE_DURATION = 0.05  # 50ms floor for rapid turnover
MAX_DRIVE_DURATION = 2.5  # Upper ceiling for slow tucks

MAX_CLOSE_RATIO = 2.0  # Knee-to-shoulder ratio limit during fast drive

# Plank stance tolerances during high-velocity movement
TORSO_INCLINE_PLANK_MAX_DEG = 68.0  # Allows dynamic hip bouncing during fast run
ELBOW_LOCK_MIN_DEG = 95.0  # Allows arm flex for shock absorption
STABLE_STANCE_FRAMES = 1  # Instant stance activation
GRACE_FRAMES = 50  # Extended grace period during rapid reps

FRAME_EDGE_MARGIN = 0.015
BBOX_TOO_CLOSE = 0.98
BBOX_TOO_FAR = 0.10


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


def _angle_deg(a, b, c) -> float:
    """Angle at vertex `b`, between rays b->a and b->c, in degrees."""
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
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.35
    )
    return visible_core >= 2


def _torso_incline_deg(mid_shoulder, mid_hip) -> Optional[float]:
    dx = mid_hip.x - mid_shoulder.x
    dy = mid_hip.y - mid_shoulder.y
    if dx == 0 and dy == 0:
        return None
    return math.degrees(math.atan2(abs(dy), max(abs(dx), 1e-9)))


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

    if len(points) < 4:
        return None

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "You're too close to the camera — back up so your whole body fits."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


def _classify_tempo(duration: Optional[float]) -> tuple[str, str]:
    """Returns (classification_code, UI_display_speed)."""
    if duration is None:
        return "normal", "Normal"
    if duration >= 0.75:
        return "too_slow", "Slow"
    if duration >= 0.40:
        return "slow", "Moderate"
    if duration >= 0.10:
        return "sharp", "Fast"
    return "too_fast", "Very Fast"


class _LegTracker:
    """High-speed leg tracker using peak-inflection direction reversal."""

    def __init__(self, label: str):
        self.label = label
        self.stage = "extended"
        self.count = 0
        self.smoothed_angle: Optional[float] = None
        self.drive_start_time: Optional[float] = None
        self.start_angle: float = 160.0
        self._min_hip_angle: float = 180.0
        self._min_close_ratio = float("inf")

    def update(
        self,
        t: float,
        shoulder,
        hip,
        knee,
        torso_length: float,
        ready: bool,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "drive_completed": False,
            "duration": None,
            "classification": None,
            "speed_label": None,
            "close_ratio": None,
        }

        if not _visible((shoulder, hip, knee)):
            return result

        raw_angle = _angle_deg(shoulder, hip, knee)

        # Fast-response exponential moving average (90% raw frame weight)
        if self.smoothed_angle is None:
            self.smoothed_angle = raw_angle
        else:
            self.smoothed_angle = 0.90 * raw_angle + 0.10 * self.smoothed_angle

        effective_angle = min(raw_angle, self.smoothed_angle)
        close_ratio = _dist(knee, shoulder) / max(torso_length, 1e-6)
        result["close_ratio"] = close_ratio

        if not ready:
            return result

        # State 1: Extended -> Drive Triggered
        if self.stage == "extended":
            if effective_angle <= DRIVEN_ANGLE_TRIGGER:
                self.stage = "driven"
                self.drive_start_time = t
                self.start_angle = max(raw_angle, self.smoothed_angle)
                self._min_hip_angle = effective_angle
                self._min_close_ratio = close_ratio

        # State 2: Driven -> Return / Rep Complete Triggered
        elif self.stage == "driven":
            self._min_hip_angle = min(self._min_hip_angle, effective_angle)
            self._min_close_ratio = min(self._min_close_ratio, close_ratio)

            # Reversal check: angle returned back OR bounced up +10 degrees from min peak
            angle_rebounded = (self.smoothed_angle - self._min_hip_angle) >= 10.0
            angle_extended = (
                self.smoothed_angle >= RETURN_ANGLE_TRIGGER
                or raw_angle >= RETURN_ANGLE_TRIGGER
            )

            if angle_rebounded or angle_extended:
                duration = (
                    (t - self.drive_start_time)
                    if self.drive_start_time is not None
                    else 0.12
                )
                total_travel = self.start_angle - self._min_hip_angle

                valid = (
                    MIN_DRIVE_DURATION <= duration <= MAX_DRIVE_DURATION
                    and self._min_close_ratio <= MAX_CLOSE_RATIO
                    and total_travel >= MIN_ANGLE_TRAVEL
                )

                if valid:
                    self.count += 1
                    classification, speed_label = _classify_tempo(duration)
                    result["drive_completed"] = True
                    result["duration"] = duration
                    result["classification"] = classification
                    result["speed_label"] = speed_label
                    result["close_ratio"] = self._min_close_ratio

                # Reset state machine for next drive
                self.stage = "extended"
                self.drive_start_time = None
                self._min_hip_angle = 180.0
                self._min_close_ratio = float("inf")

        return result


class MountainClimberAnalyzer:
    """High-velocity Mountain Climber rep counter with standard UI schema."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps
        self.left = _LegTracker("left")
        self.right = _LegTracker("right")

        self.good_reps = 0
        self.flawed_reps = 0

        self._plank_streak = 0
        self._bad_streak = 0
        self.ready = False

        self.last_rep_summary: Optional[str] = None
        self.last_rep_duration: Optional[float] = None
        self.last_speed_label: str = "-"
        self.session_start_time: Optional[float] = None

    def _is_complete(self) -> bool:
        total = self.left.count + self.right.count
        return self.target_reps is not None and total >= self.target_reps

    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        total_reps = self.left.count + self.right.count

        response: dict[str, Any] = {
            "pose_detected": False,
            "ready": self.ready,
            "stance_ok": False,
            "stance_message": None,
            "framing_ok": True,
            "framing_message": None,
            # Standardized Angle Parameters
            "left_angle": None,
            "right_angle": None,
            "left_hip_angle": None,
            "right_hip_angle": None,
            "left_stage": self.left.stage,
            "right_stage": self.right.stage,
            "left_count": self.left.count,
            "right_count": self.right.count,
            # Standard Rep Counters
            "rep_count": total_reps,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "target_reps": self.target_reps,
            # Standard UI Metric Parameters
            "rep_completed": False,
            "rep_duration": self.last_rep_duration,
            "rep_form_quality": None,
            "speed": self.last_speed_label,
            "alignment": "Unknown",
            "last_rep": self.last_rep_summary or "-",
            "session_complete": self._is_complete(),
            "drive_completed": False,
            "drive_leg": None,
            "drive_duration": None,
            "drive_classification": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = "No person detected — step into frame."
            response["alignment"] = "Off Screen"
            return response

        response["pose_detected"] = True

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]

        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
        if not torso_visible:
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your torso clearly — make sure your shoulders "
                "and hips are both in frame from a side view."
            )
            response["alignment"] = "Poor Visibility"
            return response

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)

        torso_incline = _torso_incline_deg(mid_shoulder, mid_hip)
        is_horizontal = (
            torso_incline is not None and torso_incline <= TORSO_INCLINE_PLANK_MAX_DEG
        )

        arm_ok = True
        if _visible((l_shoulder, l_elbow, l_wrist)):
            arm_ok = (
                arm_ok
                and _angle_deg(l_shoulder, l_elbow, l_wrist) >= ELBOW_LOCK_MIN_DEG
            )
        if _visible((r_shoulder, r_elbow, r_wrist)):
            arm_ok = (
                arm_ok
                and _angle_deg(r_shoulder, r_elbow, r_wrist) >= ELBOW_LOCK_MIN_DEG
            )

        is_plank = is_horizontal and arm_ok

        bbox_candidates = [
            p
            for p in (
                l_shoulder,
                r_shoulder,
                l_elbow,
                r_elbow,
                l_wrist,
                r_wrist,
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

        # Resilient Plank Readiness Logic
        if is_plank:
            self._plank_streak += 1
            self._bad_streak = 0
            response["alignment"] = "Good Plank"
        else:
            self._plank_streak = 0
            self._bad_streak += 1
            response["alignment"] = "Adjust Stance"

        if self._plank_streak >= STABLE_STANCE_FRAMES:
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES:
            self.ready = False

        response["ready"] = self.ready
        response["stance_ok"] = self.ready

        if not is_horizontal:
            response["stance_message"] = (
                "Get into a plank — hands under shoulders, body straight."
            )
        elif not arm_ok:
            response["stance_message"] = "Support body with arms — keep elbows steady."
        elif not self.ready:
            response["stance_message"] = "Get into plank to start counting..."

        # Run high-speed leg trackers
        left_result = self.left.update(
            t, l_shoulder, l_hip, l_knee, torso_length, self.ready
        )
        right_result = self.right.update(
            t, r_shoulder, r_hip, r_knee, torso_length, self.ready
        )

        # Output rounded angles to UI
        l_ang = (
            round(self.left.smoothed_angle, 1)
            if self.left.smoothed_angle is not None
            else 0.0
        )
        r_ang = (
            round(self.right.smoothed_angle, 1)
            if self.right.smoothed_angle is not None
            else 0.0
        )

        response["left_angle"] = l_ang
        response["right_angle"] = r_ang
        response["left_hip_angle"] = l_ang
        response["right_hip_angle"] = r_ang

        response["left_stage"] = self.left.stage
        response["right_stage"] = self.right.stage
        response["left_count"] = self.left.count
        response["right_count"] = self.right.count

        feedback = framing_message

        # Process rep completions
        for leg, r in (("left", left_result), ("right", right_result)):
            if r["drive_completed"]:
                response["rep_completed"] = True
                response["drive_completed"] = True
                response["drive_leg"] = leg
                response["drive_duration"] = r["duration"]
                response["drive_classification"] = r["classification"]

                self.last_rep_duration = (
                    round(r["duration"], 2) if r["duration"] else 0.15
                )
                self.last_speed_label = r["speed_label"] or "Fast"

                tempo = r["classification"] or "sharp"
                if tempo in ("sharp", "normal", "too_fast"):
                    self.good_reps += 1
                    response["rep_form_quality"] = "good"
                    feedback = f"Fast {leg} knee drive!"
                    self.last_rep_summary = f"Good {leg.capitalize()} Drive"
                else:
                    self.flawed_reps += 1
                    response["rep_form_quality"] = "needs_improvement"
                    feedback = f"{leg.capitalize()} drive counted — increase pace."
                    self.last_rep_summary = f"Slow {leg.capitalize()} Drive"

        # Sync totals
        total_reps = self.left.count + self.right.count
        response["rep_count"] = total_reps
        response["good_reps"] = self.good_reps
        response["flawed_reps"] = self.flawed_reps
        response["session_complete"] = self._is_complete()
        response["rep_duration"] = self.last_rep_duration
        response["speed"] = self.last_speed_label
        response["last_rep"] = self.last_rep_summary or "-"

        if feedback is None and not self.ready:
            feedback = response["stance_message"] or "Get into plank to start."
        if feedback is None:
            feedback = "Good plank base — drive knees forward fast!"

        response["feedback"] = feedback
        return response


class MountainClimberSession:
    """Session wrapper."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = MountainClimberAnalyzer(target_reps)
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
