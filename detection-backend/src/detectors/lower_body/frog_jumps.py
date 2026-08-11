"""
Frog Jumps rep counting + posture correction (Reliable Jump Enforcement).

The movement
------------
A plyometric lower body exercise where the user drops into a deep squat position
(knee flexion <= 105°) and explodes upward in a jump, returning to a standing/landing
position.

Squat Prevention (Multi-Signal Gating):
  1. Tracks knee extension speed (deg/sec).
  2. Tracks vertical hip displacement spike (upward motion in frame).
  3. Prevents slow squats from counting while guaranteeing fast/real jumps are NEVER missed.
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
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

# -------------------------------------------------------------------------
# Tunable constants
# -------------------------------------------------------------------------

MIN_LANDMARK_VISIBILITY = 0.30

# ---- Knee Angle Thresholds (degrees) ----
KNEE_UP_STANDING_ABOVE = 140.0  # Standing / Extension threshold (relocated high)
KNEE_DOWN_SQUAT_BELOW = 108.0  # Bottom frog squat threshold (generous to avoid misses)

KNEE_UP_IDEAL_ABOVE = 155.0  # Ideal top extension / jump extension
KNEE_DOWN_IDEAL_BELOW = 90.0  # Deep frog squat depth

# ---- Jump Detection Signals ----
# Minimum extension speed required (deg/sec) to qualify as a jump
MIN_JUMP_VELOCITY_DEG_SEC = 80.0

# Minimum vertical hip displacement (Y-axis shift) required during push-off
MIN_HIP_UPWARD_SHIFT = 0.035

# ---- Torso Hinge / Posture ----
TORSO_COLLAPSE_BELOW = 65.0  # Chest collapsed excessively downward

FRAME_EDGE_MARGIN = 0.02
BBOX_TOO_CLOSE = 0.97
BBOX_TOO_FAR = 0.12


def _looks_like_a_person(landmarks) -> bool:
    core = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)
    visible = sum(
        1
        for i in core
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.5
    )
    return visible >= 3


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


def _framing_feedback(points) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return "Step back so your full body, from head to feet, fits in frame."

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "You're too close to the camera — step back so your full body fits."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class FrogJumpAnalyzer:
    """Stateful Frog Jump counter strictly gated against slow squats without missing real reps."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.stage: str = "up"  # "up" (standing) | "down" (deep squat)
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        self.down_knee_extreme = 180.0
        self.up_knee_extreme = 0.0

        self.prev_knee_angle: Optional[float] = None
        self.prev_timestamp: Optional[float] = None
        self.bottom_hip_y: Optional[float] = (
            None  # Y-pos of hips at lowest point of squat
        )

        self.max_upward_velocity = 0.0
        self.max_hip_displacement = 0.0

        self._jump_detected = False
        self._awaiting_up_confirmation = False
        self._rep_torso_collapsed = False

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
            "avg_knee_angle": None,
            "avg_torso_angle": None,
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

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = (
                "No person detected — step into frame facing the camera."
            )
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        required_ok = _visible(
            (l_shoulder, r_shoulder, l_hip, r_hip, l_knee, r_knee, l_ankle, r_ankle)
        )
        if not required_ok:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see lower body clearly — ensure hips, knees, and feet are visible."
            )
            return response

        response["pose_detected"] = True

        framing_points = [
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
        framing_message = _framing_feedback(framing_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        if framing_message is not None:
            response["feedback"] = framing_message
            return response

        # Knee Flexion Angle (Hip-Knee-Ankle)
        left_knee_angle = _angle_deg(l_hip, l_knee, l_ankle)
        right_knee_angle = _angle_deg(r_hip, r_knee, r_ankle)
        avg_knee_angle = (left_knee_angle + right_knee_angle) / 2.0
        response["avg_knee_angle"] = round(avg_knee_angle, 1)

        # Torso Angle (Shoulder-Hip-Knee)
        left_torso_angle = _angle_deg(l_shoulder, l_hip, l_knee)
        right_torso_angle = _angle_deg(r_shoulder, r_hip, r_knee)
        avg_torso_angle = (left_torso_angle + right_torso_angle) / 2.0
        response["avg_torso_angle"] = round(avg_torso_angle, 1)

        # Average Hip Y Position
        avg_hip_y = (l_hip.y + r_hip.y) / 2.0

        # Calculate extension velocity (deg/sec)
        velocity = 0.0
        if self.prev_knee_angle is not None and self.prev_timestamp is not None:
            dt = t - self.prev_timestamp
            if dt > 0.001:  # Protect against divide-by-zero
                velocity = (avg_knee_angle - self.prev_knee_angle) / dt

        self.prev_knee_angle = avg_knee_angle
        self.prev_timestamp = t

        # Posture Check
        if avg_torso_angle < TORSO_COLLAPSE_BELOW:
            self._rep_torso_collapsed = True

        # ---- State Machine & Multi-Signal Jump Enforcement ----
        if self.stage == "up":
            self.up_knee_extreme = max(self.up_knee_extreme, avg_knee_angle)
            if avg_knee_angle < KNEE_DOWN_SQUAT_BELOW:
                self.stage = "down"
                self.down_knee_extreme = avg_knee_angle
                self.bottom_hip_y = avg_hip_y
                self.max_upward_velocity = 0.0
                self.max_hip_displacement = 0.0
                self._jump_detected = False
                self._awaiting_up_confirmation = True

        elif self.stage == "down":
            self.down_knee_extreme = min(self.down_knee_extreme, avg_knee_angle)

            # Update lowest hip height reached
            if self.bottom_hip_y is None or avg_hip_y > self.bottom_hip_y:
                self.bottom_hip_y = avg_hip_y

            # Measure upward vertical movement (Y coordinates decrease moving up)
            if self.bottom_hip_y is not None:
                upward_shift = self.bottom_hip_y - avg_hip_y
                self.max_hip_displacement = max(self.max_hip_displacement, upward_shift)

            # Track peak extension speed while coming up
            if velocity > 0:
                self.max_upward_velocity = max(self.max_upward_velocity, velocity)

            # Verify Jump: Either fast velocity OR significant upward hip displacement
            if (
                self.max_upward_velocity >= MIN_JUMP_VELOCITY_DEG_SEC
                or self.max_hip_displacement >= MIN_HIP_UPWARD_SHIFT
            ):
                self._jump_detected = True

            if avg_knee_angle > KNEE_UP_STANDING_ABOVE:
                self.stage = "up"
                self.up_knee_extreme = avg_knee_angle

        response["stage"] = self.stage

        rep_completed = False
        quality: Optional[str] = None
        feedback: Optional[str] = None

        # ---- Rep Completion Check ----
        if self._awaiting_up_confirmation and self.stage == "up":
            # If user did a slow squat with zero vertical hop/velocity, reject and reset
            if not self._jump_detected:
                feedback = (
                    "Squat detected! Explode upward in a JUMP for Frog Jumps to count."
                )
                self._awaiting_up_confirmation = False
                self._rep_torso_collapsed = False
                self.down_knee_extreme = 180.0
                self.up_knee_extreme = 0.0
            else:
                shallow_squat = self.down_knee_extreme > KNEE_DOWN_IDEAL_BELOW
                incomplete_extension = self.up_knee_extreme < KNEE_UP_IDEAL_ABOVE

                flawed = (
                    shallow_squat or incomplete_extension or self._rep_torso_collapsed
                )

                self.rep_count += 1
                if flawed:
                    self.flawed_reps += 1
                    quality = "needs_improvement"
                    if self._rep_torso_collapsed:
                        hint = "keep chest up during the jump"
                    elif shallow_squat:
                        hint = "squat lower before exploding upward"
                    else:
                        hint = "fully extend legs at top of jump"
                    feedback = f"Rep {self.rep_count} counted — {hint}."
                else:
                    self.good_reps += 1
                    quality = "good"
                    feedback = f"Rep {self.rep_count} counted! Explosive jump!"

                rep_completed = True
                self._awaiting_up_confirmation = False
                self._rep_torso_collapsed = False
                self.down_knee_extreme = 180.0
                self.up_knee_extreme = 0.0

        if feedback is None:
            if self.stage == "down":
                feedback = "Deep frog squat reached — now EXPLODE UPWARD into a jump!"
            elif self.stage == "up":
                feedback = "Ready — drop into a deep squat and jump explosively."

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


class FrogJumpSession:
    """Full session manager for Frog Jumps."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = FrogJumpAnalyzer(target_reps)
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
