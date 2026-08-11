"""
Squat Thrust detector — Fast Motion & High Velocity Optimized Version.

Fixes for fast movements:
  - Peak-memory tracking across motion frames.
  - Motion-blur tolerant landmark visibility.
  - Reduced minimum rep duration (0.18s floor).
  - Hysteresis-based state transitions.
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    LEFT_WRIST,
    NOSE,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)

# -------------------------------------------------------------------------
# Tunable Constants (Fast Motion Calibrated)
# -------------------------------------------------------------------------

# Lower visibility tolerance during explosive motion to handle motion blur
MIN_LANDMARK_VISIBILITY = 0.25

# Hysteresis Thresholds for Torso Angle (from vertical)
TORSO_UPRIGHT_THRESH = 38.0  # Max deviation (deg) to consider "standing upright"
TORSO_PLANK_ENTRY_THRESH = 48.0  # Min deviation (deg) to enter plank transition

# Plank validation
MIN_PEAK_PLANK_EXTENSION = 0.58  # Body extension peak memory check
KNEE_STRAIGHT_MIN_DEG = 145.0  # Knee lockout angle at top of rep

# Timing limits for explosive speed
MIN_REP_DURATION = 0.18
MAX_REP_DURATION = 5.0

# Framing Thresholds
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


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _angle_deg(a, b, c) -> float:
    ang = math.degrees(
        math.atan2(c.y - b.y, c.x - b.x) - math.atan2(a.y - b.y, a.x - b.x)
    )
    ang = abs(ang)
    if ang > 180:
        ang = 360 - ang
    return ang


def _vertical_deviation_deg(top, bottom) -> Optional[float]:
    dx = bottom.x - top.x
    dy = bottom.y - top.y
    if dx == 0 and dy == 0:
        return None
    return math.degrees(math.atan2(abs(dx), max(abs(dy), 1e-9)))


def _framing_feedback(points: list[_Point]) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return "Keep full body visible in frame during fast movement."

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "Too close — step back so sprawling doesn't clip off-screen."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "Too far — move closer for tracking."

    return None


class SquatThrustAnalyzer:
    """High-velocity resilient Squat Thrust rep counter."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.stage: str = "standing"
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        # Memory variables for fast movement capture
        self.rep_start_time: Optional[float] = None
        self.peak_plank_extension: float = 0.0
        self.peak_knee_extension: float = 0.0
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
            "framing_ok": True,
            "framing_message": None,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_form_quality": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None:
            response["feedback"] = "No person detected — step into frame."
            return response

        # Fetch landmarks
        nose = landmarks[NOSE]
        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        # Use blur-tolerant visibility check
        required_ok = _visible(
            (
                nose,
                l_shoulder,
                r_shoulder,
                l_hip,
                r_hip,
                l_knee,
                r_knee,
                l_ankle,
                r_ankle,
            )
        )

        if not required_ok:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = "Keep full body visible. Motion blur detected."
            return response

        response["pose_detected"] = True

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        mid_knee = _midpoint(l_knee, r_knee)
        mid_ankle = _midpoint(l_ankle, r_ankle)

        # Dynamic framing check
        bbox_points = [
            _Point(p.x, p.y)
            for p in (
                nose,
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

        if framing_message is not None:
            response["feedback"] = framing_message
            return response

        # Calculate geometric metrics
        torso_len = _dist(mid_shoulder, mid_hip)
        femur_len = _dist(mid_hip, mid_knee)
        tibia_len = _dist(mid_knee, mid_ankle)
        body_length = max(torso_len + femur_len + tibia_len, 1e-6)

        torso_dev = _vertical_deviation_deg(mid_shoulder, mid_hip)
        current_extension = _dist(mid_shoulder, mid_ankle) / body_length

        left_knee_angle = _angle_deg(l_hip, l_knee, l_ankle)
        right_knee_angle = _angle_deg(r_hip, r_knee, r_ankle)
        avg_knee_angle = (left_knee_angle + right_knee_angle) / 2.0

        rep_completed = False
        quality: Optional[str] = None
        feedback: Optional[str] = None

        # ---- Fast Motion State Machine ----
        if self.stage == "standing":
            # Track standing knee extension
            self.peak_knee_extension = max(self.peak_knee_extension, avg_knee_angle)

            # Trigger transition to Plank on initial torso tilt
            if torso_dev is not None and torso_dev > TORSO_PLANK_ENTRY_THRESH:
                self.stage = "plank"
                self.rep_start_time = t
                self.peak_plank_extension = current_extension
                self.peak_knee_extension = 0.0

        elif self.stage == "plank":
            # Continuously register maximum body extension reached while in plank phase
            self.peak_plank_extension = max(
                self.peak_plank_extension, current_extension
            )
            self.peak_knee_extension = max(self.peak_knee_extension, avg_knee_angle)

            # Trigger return to Standing when torso swings back vertical
            if torso_dev is not None and torso_dev < TORSO_UPRIGHT_THRESH:
                rep_duration = (t - self.rep_start_time) if self.rep_start_time else 0.3

                # Check if peak plank extension was satisfied during the fast sprawl phase
                valid_plank = self.peak_plank_extension >= MIN_PEAK_PLANK_EXTENSION
                valid_lockout = (
                    avg_knee_angle >= KNEE_STRAIGHT_MIN_DEG
                    or self.peak_knee_extension >= KNEE_STRAIGHT_MIN_DEG
                )

                if valid_plank and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION:
                    self.rep_count += 1
                    rep_completed = True

                    if valid_lockout:
                        self.good_reps += 1
                        quality = "good"
                        feedback = f"Rep {self.rep_count} counted! Explosive form."
                    else:
                        self.flawed_reps += 1
                        quality = "needs_improvement"
                        feedback = (
                            f"Rep {self.rep_count} counted — stand up fully at the top!"
                        )
                else:
                    if not valid_plank:
                        feedback = "Kick legs all the way back into a full plank."

                # Reset state for next explosive rep
                self.stage = "standing"
                self.rep_start_time = None
                self.peak_plank_extension = 0.0

        response["stage"] = self.stage

        if feedback is None:
            if self.stage == "plank":
                feedback = "Fast sprawl detected! Drive feet forward and stand up."
            else:
                feedback = "Ready — drop down fast and kick feet back."

        response.update(
            {
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_form_quality": quality,
                "feedback": feedback,
            }
        )
        return response


class SquatThrustSession:
    """Full session manager for Squat Thrusts."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = SquatThrustAnalyzer(target_reps)
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
