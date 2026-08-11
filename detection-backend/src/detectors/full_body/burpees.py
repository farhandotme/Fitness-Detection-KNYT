"""
Burpee exercise rep counting + strict form analysis.

The movement
------------
A full-body explosive exercise involving multiple transitions:
  1. Standing upright.
  2. Dropping into a horizontal plank position (legs kicked back).
  3. (Optional but tracked) Performing a push-up.
  4. Returning to a standing position and executing a jump with hands above the head.

Strict Gating Prevention:
  - Squats: Rejected because the body never reaches horizontal extension (plank).
  - Push-ups: Rejected because the body never returns to vertical + jump.
  - Jumping Jacks: Rejected because the body never drops to the floor.
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
# Tunable constants
# -------------------------------------------------------------------------

MIN_LANDMARK_VISIBILITY = 0.40

# ---- State Machine Thresholds ----
TORSO_UPRIGHT_THRESH = 45.0  # Max angle (deg) from vertical to be considered "standing"
TORSO_PLANK_THRESH = 60.0  # Min angle (deg) from vertical to be considered "horizontal"

# Body extension ratio: distance(shoulder, ankle) / total_body_segment_length
# In a plank, the body is straight, so this ratio is high (> 0.70).
# In a squat, the body is folded, so this ratio is low.
MIN_PLANK_EXTENSION_RATIO = 0.70

# Push-up detection: Vertical distance between shoulder and wrist normalized by body length.
# Drops near zero when chest hits the floor.
PUSHUP_DEPTH_RATIO = 0.15

# ---- Framing constants ----
FRAME_EDGE_MARGIN = 0.02
BBOX_TOO_CLOSE = 0.97
BBOX_TOO_FAR = 0.12


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


def _vertical_deviation_deg(top, bottom) -> Optional[float]:
    """Calculates angle deviation from a perfect vertical line (0 degrees = straight up/down)."""
    dx = bottom.x - top.x
    dy = bottom.y - top.y
    if dx == 0 and dy == 0:
        return None
    # Use atan2(dx, dy) to get angle relative to vertical Y axis
    return math.degrees(math.atan2(abs(dx), max(abs(dy), 1e-9)))


def _framing_feedback(points: list[_Point]) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return "You're partly out of frame. Ensure your full body and floor space are visible."

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "You're too close — step back so your entire burpee fits in frame."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for tracking."

    return None


class BurpeeAnalyzer:
    """Stateful Burpee rep counter with strict sequential gating."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        # States: "standing" -> "plank" -> "standing" (pending jump)
        self.stage: str = "standing"
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        self.pending_jump = False
        self.did_pushup = False

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

        # Required Landmarks
        nose = landmarks[NOSE]
        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]

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
                l_wrist,
                r_wrist,
            )
        )

        if not required_ok:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Camera angle issue: For burpees, please stand at a 45-degree angle "
                "so your plank and full body are visible."
            )
            return response

        response["pose_detected"] = True

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        mid_knee = _midpoint(l_knee, r_knee)
        mid_ankle = _midpoint(l_ankle, r_ankle)
        mid_wrist = _midpoint(l_wrist, r_wrist)

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

        # ---- Core Geometric Calculations ----

        # Calculate dynamic body length (sum of segments handles squatted/folded positions)
        torso_len = _dist(mid_shoulder, mid_hip)
        femur_len = _dist(mid_hip, mid_knee)
        tibia_len = _dist(mid_knee, mid_ankle)
        body_length = max(torso_len + femur_len + tibia_len, 1e-6)

        # Body alignment metrics
        torso_dev = _vertical_deviation_deg(mid_shoulder, mid_hip)
        plank_extension = _dist(mid_shoulder, mid_ankle) / body_length
        shoulder_wrist_y_dist = abs(mid_shoulder.y - mid_wrist.y) / body_length

        # Jump Trigger: Wrists raised above the nose
        hands_above_head = (l_wrist.y < nose.y) or (r_wrist.y < nose.y)

        # ---- Strict Gating State Machine ----
        rep_completed = False
        quality: Optional[str] = None
        feedback: Optional[str] = None

        if self.stage == "standing":
            # 1. Look for completion of a pending rep (The Jump Phase)
            if self.pending_jump:
                if hands_above_head:
                    # PERFECT REP: Completed jump
                    self.rep_count += 1
                    rep_completed = True
                    self.pending_jump = False

                    if self.did_pushup:
                        self.good_reps += 1
                        quality = "good"
                        feedback = (
                            f"Rep {self.rep_count} Counted! Excellent full burpee."
                        )
                    else:
                        self.flawed_reps += 1
                        quality = "needs_improvement"
                        feedback = f"Rep {self.rep_count} Counted! Tip: Add a push-up at the bottom for a standard burpee."

                # FLAWED REP: User went back down to a plank WITHOUT jumping
                elif (
                    torso_dev is not None
                    and torso_dev > TORSO_PLANK_THRESH
                    and plank_extension > MIN_PLANK_EXTENSION_RATIO
                ):
                    self.rep_count += 1
                    self.flawed_reps += 1
                    rep_completed = True
                    quality = "needs_improvement"
                    feedback = f"Rep {self.rep_count} FLAWED: You forgot to jump with your hands up!"

                    # Reset immediately into the plank stage for the next rep
                    self.pending_jump = False
                    self.stage = "plank"
                    self.did_pushup = False

            # 2. Look for transition into the Plank Phase
            if (
                not self.pending_jump
                and torso_dev is not None
                and torso_dev > TORSO_PLANK_THRESH
            ):
                # Require legs to be kicked back (prevents squats from triggering plank)
                if plank_extension > MIN_PLANK_EXTENSION_RATIO:
                    self.stage = "plank"
                    self.did_pushup = False

        elif self.stage == "plank":
            # Track push-up depth while in the plank state
            if shoulder_wrist_y_dist < PUSHUP_DEPTH_RATIO:
                self.did_pushup = True

            # 3. Look for transition back to Standing Phase
            if torso_dev is not None and torso_dev < TORSO_UPRIGHT_THRESH:
                self.stage = "standing"
                self.pending_jump = True

        response["stage"] = self.stage

        # Provide live dynamic coaching if no rep just fired
        if feedback is None:
            if self.stage == "plank":
                if self.did_pushup:
                    feedback = "Push-up complete! Now explode up into a jump."
                else:
                    feedback = "Legs kicked back! Add a push-up or jump up."
            elif self.stage == "standing":
                if self.pending_jump:
                    feedback = "Jump! Raise your hands above your head!"
                else:
                    feedback = "Ready. Drop down and kick legs back into a plank."

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


class BurpeeSession:
    """Full session manager for Burpees."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = BurpeeAnalyzer(target_reps)
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
