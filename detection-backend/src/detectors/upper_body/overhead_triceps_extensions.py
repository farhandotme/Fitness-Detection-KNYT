"""
Overhead Triceps Extension tracking module — Refined & Non-Blocking Version.

Fixes:
  - Non-blocking framing checks (reps count even if framing warnings occur).
  - Front, Back, and Side/Profile angle support.
  - Automatic single-arm fallback during occlusion in "both" mode.
  - Hysteresis-based rep triggers for smooth execution.
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_SHOULDER,
    LEFT_WRIST,
    NOSE,
    PoseEngine,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)

# -------------------------------------------------------------------------
# Calibrated Constants
# -------------------------------------------------------------------------

MIN_LANDMARK_VISIBILITY = 0.25  # Lower threshold to handle profile/back views

# Joint angle thresholds (degrees)
EXTENSION_TOP_THRESH = 135.0  # Extended overhead top phase
FLEXION_BOTTOM_THRESH = 100.0  # Lowered behind head bottom phase

PARTIAL_STRETCH_LIMIT = 110.0  # Did not lower weight enough
INCOMPLETE_LOCKOUT_LIMIT = 130.0  # Did not extend overhead enough

MIN_REP_DURATION = 0.4
MAX_REP_DURATION = 6.0

FRAME_EDGE_MARGIN = 0.01
BBOX_TOO_CLOSE = 0.98
BBOX_TOO_FAR = (
    0.05  # Reduced threshold to prevent false "Too far" triggers while seated
)


class _Point:
    __slots__ = ("x", "y", "visibility")

    def __init__(self, x: float, y: float, visibility: float = 1.0):
        self.x = x
        self.y = y
        self.visibility = visibility


def _midpoint(a: _Point, b: _Point) -> _Point:
    return _Point((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)


def _is_visible(p: Optional[Any], min_vis: float = MIN_LANDMARK_VISIBILITY) -> bool:
    if p is None:
        return False
    v = getattr(p, "visibility", None)
    return v is None or v >= min_vis


def _angle_2d_deg(a: _Point, b: _Point, c: _Point) -> float:
    """Calculates 2D joint angle at vertex 'b'."""
    ang = math.degrees(
        math.atan2(c.y - b.y, c.x - b.x) - math.atan2(a.y - b.y, a.x - b.x)
    )
    ang = abs(ang)
    if ang > 180.0:
        ang = 360.0 - ang
    return ang


def _framing_feedback(points: list[_Point]) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return "Upper body or arms near frame edge — keep full upper body visible."

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "Too close — step back slightly so arms extend fully."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "Too far from camera — move closer for accurate tracking."

    return None


class OverheadTricepsExtensionAnalyzer:
    """Refined Overhead Triceps Extension analyzer with front/back/side support."""

    def __init__(self, arm_mode: str = "both", target_reps: Optional[int] = None):
        if arm_mode not in ("left", "right", "both"):
            raise ValueError("arm_mode must be 'left', 'right', or 'both'")

        self.arm_mode = arm_mode
        self.target_reps = target_reps

        self.stage = "up"
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        self.rep_start_time: Optional[float] = None
        self._rep_min_angle: float = 180.0
        self._rep_max_angle: float = 0.0
        self._current_rep_issues: set[str] = set()

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
            "arm_mode": self.arm_mode,
            "left_elbow_angle": None,
            "right_elbow_angle": None,
            "elbow_angle": None,
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

        # Extract Raw Landmarks
        l_sh, r_sh = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_el, r_el = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wr, r_wr = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]

        # Check visibility per arm
        left_visible = _is_visible(l_sh) and _is_visible(l_el) and _is_visible(l_wr)
        right_visible = _is_visible(r_sh) and _is_visible(r_el) and _is_visible(r_wr)

        if not left_visible and not right_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Arms not clearly visible — raise arms overhead facing camera or back."
            )
            return response

        response["pose_detected"] = True

        # Build Points
        p_l_sh = _Point(l_sh.x, l_sh.y, getattr(l_sh, "visibility", 1.0))
        p_r_sh = _Point(r_sh.x, r_sh.y, getattr(r_sh, "visibility", 1.0))
        p_l_el = _Point(l_el.x, l_el.y, getattr(l_el, "visibility", 1.0))
        p_r_el = _Point(r_el.x, r_el.y, getattr(r_el, "visibility", 1.0))
        p_l_wr = _Point(l_wr.x, l_wr.y, getattr(l_wr, "visibility", 1.0))
        p_r_wr = _Point(r_wr.x, r_wr.y, getattr(r_wr, "visibility", 1.0))

        # Calculate angles for visible arms
        left_angle = _angle_2d_deg(p_l_sh, p_l_el, p_l_wr) if left_visible else None
        right_angle = _angle_2d_deg(p_r_sh, p_r_el, p_r_wr) if right_visible else None

        # Resolve primary angle based on mode and occlusion
        if self.arm_mode == "left":
            current_angle = left_angle if left_angle is not None else right_angle
        elif self.arm_mode == "right":
            current_angle = right_angle if right_angle is not None else left_angle
        else:  # "both" mode
            if left_angle is not None and right_angle is not None:
                current_angle = (left_angle + right_angle) / 2.0
            elif left_angle is not None:
                current_angle = left_angle
            else:
                current_angle = right_angle

        if current_angle is None:
            response["low_visibility"] = True
            response["feedback"] = "Keep arms visible overhead."
            return response

        response["left_elbow_angle"] = (
            round(left_angle, 1) if left_angle is not None else None
        )
        response["right_elbow_angle"] = (
            round(right_angle, 1) if right_angle is not None else None
        )
        response["elbow_angle"] = round(current_angle, 1)

        # Informational Framing Check (Non-Blocking)
        active_points = [
            p
            for p in (p_l_sh, p_r_sh, p_l_el, p_r_el, p_l_wr, p_r_wr)
            if p.visibility > 0.2
        ]
        framing_message = _framing_feedback(active_points) if active_points else None
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        # Overhead position check: Elbows should remain higher than shoulders (y_elbow < y_shoulder)
        elbow_dropped = False
        if left_visible and p_l_el.y > p_l_sh.y:
            elbow_dropped = True
        if right_visible and p_r_el.y > p_r_sh.y:
            elbow_dropped = True

        if elbow_dropped:
            self._current_rep_issues.add("elbows_dropped")

        # ---- State Machine ----
        rep_completed = False
        rep_duration = None
        quality = None
        feedback = framing_message  # Default to framing cue if present

        if self.stage == "up":
            self._rep_max_angle = max(self._rep_max_angle, current_angle)

            # Lowering weight behind head
            if current_angle <= FLEXION_BOTTOM_THRESH:
                self.stage = "down"
                self.rep_start_time = t
                self._rep_min_angle = current_angle
                self._rep_max_angle = current_angle
                self._current_rep_issues.clear()

        elif self.stage == "down":
            self._rep_min_angle = min(self._rep_min_angle, current_angle)
            self._rep_max_angle = max(self._rep_max_angle, current_angle)

            # Extending overhead to lock out
            if current_angle >= EXTENSION_TOP_THRESH:
                self.stage = "up"
                rep_completed = True
                rep_duration = (t - self.rep_start_time) if self.rep_start_time else 1.0

        # Form Validation upon rep completion
        if rep_completed:
            if self._rep_min_angle > PARTIAL_STRETCH_LIMIT:
                self._current_rep_issues.add("partial_stretch")
            if self._rep_max_angle < INCOMPLETE_LOCKOUT_LIMIT:
                self._current_rep_issues.add("incomplete_extension")

            valid_timing = MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION

            if valid_timing:
                self.rep_count += 1
                if self._current_rep_issues:
                    self.flawed_reps += 1
                    quality = "needs_improvement"
                    issues_str = ", ".join(
                        i.replace("_", " ") for i in sorted(self._current_rep_issues)
                    )
                    feedback = (
                        f"Rep {self.rep_count} counted! Watch form: {issues_str}."
                    )
                else:
                    self.good_reps += 1
                    quality = "good"
                    feedback = f"Rep {self.rep_count} counted! Excellent full lockout."
            else:
                rep_completed = False
                feedback = "Rep too fast — lower and extend with controlled motion."

            self.rep_start_time = None
            self._rep_min_angle = 180.0
            self._rep_max_angle = 0.0
            self._current_rep_issues.clear()

        # Real-time state guidance
        if feedback is None:
            if self.stage == "down":
                feedback = "Press weight up until arms fully extend overhead."
            else:
                feedback = "Lower weight behind head for full triceps extension."

        response.update(
            {
                "stage": self.stage,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_duration": rep_duration,
                "rep_form_quality": quality,
                "feedback": feedback,
            }
        )
        return response


class OverheadTricepsExtensionSession:
    """Session wrapper managing PoseEngine and Analyzer for Overhead Triceps Extensions."""

    def __init__(
        self,
        arm_mode: str = "both",
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = OverheadTricepsExtensionAnalyzer(
            arm_mode=arm_mode, target_reps=target_reps
        )
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
