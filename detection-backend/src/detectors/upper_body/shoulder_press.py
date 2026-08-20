"""
Production-grade Overhead Shoulder Press Rep Counter & Pose Analyzer.

Biomechanical Constraints & Form Validation (Adjusted for 2D Camera Distortion):
--------------------------------------------------------------------------------
1. Bottom Setup (|_0_|): Enforced via Y-coordinates. Wrists must come down near
   shoulder level.
2. Top Lockout (|o|): Arms press overhead, wrist Y-coords must clear shoulders.
3. Movement Rejection (\_0_/): Lateral raises are rejected using generous width
   scaling to allow natural V-path presses while blocking horizontal raises.
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_SHOULDER,
    LEFT_WRIST,
    PoseEngine,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)

# -------------------------------------------------------------------------
# Tunable Constants & Geometric Thresholds
# -------------------------------------------------------------------------

MIN_LANDMARK_VISIBILITY = 0.4
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER)

# Angles adjusted for 2D front-facing camera foreshortening
TOP_ANGLE = 145.0  # Relaxed slightly to ensure lockout registers
BOTTOM_ANGLE = 120.0  # 2D projection of "ear level" often reads as 110-120 degrees
MIN_ANGLE_DELTA = 25.0  # Reduced to accommodate the new bottom angle
MIN_REP_DURATION = 0.4
MAX_REP_DURATION = 8.0

# Geometry multipliers relative to shoulder distance
MAX_LATERAL_WRIST_SPREAD = 2.5  # Generous allowance for natural V-press path
MIN_OVERHEAD_RAISE = 0.15  # Wrists must clear shoulder line vertically
MAX_BOTTOM_HAND_DROP = 0.10  # Wrists dropping significantly below shoulders

# Body alignment & Flaw thresholds
ASYMMETRY_THRESHOLD_DEG = 25.0
MAX_LEAN_FROM_VERTICAL_DEG = 45.0
LEAN_BACK_WARN_DEG = 18.0

STABLE_FRAMES = 5
GRACE_FRAMES = 10

FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.97
BBOX_TOO_FAR = 0.12


class _Point:
    __slots__ = ("x", "y")

    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y


def _midpoint(a, b) -> _Point:
    return _Point((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


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


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 1


def _framing_feedback(points: list[_Point]) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — step back so your arms fit in the shot."
            )

    if len(points) < 3:
        return None

    xs, ys = [p.x for p in points], [p.y for p in points]
    width, height = max(xs) - min(xs), max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "You're too close to the camera — back up a bit."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move a bit closer."
    return None


class ShoulderPressAnalyzer:
    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps
        self.stage = "bottom"
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        self.smoothed_angle: Optional[float] = None
        self.last_angle: Optional[float] = None
        self.rep_start_time: Optional[float] = None
        self._rep_angle_acc = 0.0
        self.angle_smooth_alpha = 0.6
        self.session_start_time: Optional[float] = None

        self._good_streak = 0
        self._bad_streak = 0
        self.ready = False
        self._current_rep_issues: set[str] = set()

    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 3.5:
            return "too_slow"
        if duration >= 2.0:
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
            "position_ok": False,
            "position_message": None,
            "ready": self.ready,
            "angle": None,
            "smoothed_angle": None,
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
            "lean_ok": True,
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = "We can't see you yet — step into the camera view."
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]

        left_arm_ok = _visible((l_shoulder, l_elbow, l_wrist))
        right_arm_ok = _visible((r_shoulder, r_elbow, r_wrist))

        if not left_arm_ok or not right_arm_ok:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Make sure both arms, shoulders, and wrists are clearly in view."
            )
            return response

        response["pose_detected"] = True

        bbox_points = [
            _Point(p.x, p.y)
            for p in (l_shoulder, r_shoulder, l_elbow, r_elbow, l_wrist, r_wrist)
        ]
        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        hips_visible = _visible((l_hip, r_hip))
        is_standing = True
        lean_deg = None

        if hips_visible:
            mid_shoulder = _midpoint(l_shoulder, r_shoulder)
            mid_hip = _midpoint(l_hip, r_hip)
            dx, dy = mid_hip.x - mid_shoulder.x, mid_hip.y - mid_shoulder.y
            lean_deg = math.degrees(math.atan2(abs(dx), max(abs(dy), 1e-6)))
            is_standing = lean_deg <= MAX_LEAN_FROM_VERTICAL_DEG

        if is_standing:
            self._good_streak += 1
            self._bad_streak = 0
        else:
            self._good_streak = 0
            self._bad_streak += 1

        if self._good_streak >= STABLE_FRAMES:
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES:
            self.ready = False

        position_ok = self.ready and framing_message is None
        response["position_ok"] = position_ok
        response["ready"] = self.ready

        if not self.ready and not framing_message:
            response["position_message"] = (
                "Stand facing the camera with space to press overhead."
            )

        shoulder_dist = max(_dist(l_shoulder, r_shoulder), 0.01)
        wrist_dist = _dist(l_wrist, r_wrist)

        left_angle = _angle_deg(l_shoulder, l_elbow, l_wrist)
        right_angle = _angle_deg(r_shoulder, r_elbow, r_wrist)
        raw_angle = (left_angle + right_angle) / 2.0

        if self.smoothed_angle is None:
            self.smoothed_angle = raw_angle
        else:
            self.smoothed_angle = (self.angle_smooth_alpha * raw_angle) + (
                (1 - self.angle_smooth_alpha) * self.smoothed_angle
            )

        # ---- Dynamic Rules ----
        is_lateral_raise = (wrist_dist / shoulder_dist) > MAX_LATERAL_WRIST_SPREAD
        wrists_above_shoulders = (
            l_shoulder.y - l_wrist.y
        ) > MIN_OVERHEAD_RAISE * shoulder_dist and (
            r_shoulder.y - r_wrist.y
        ) > MIN_OVERHEAD_RAISE * shoulder_dist

        avg_wrist_y = (l_wrist.y + r_wrist.y) / 2.0
        avg_shoulder_y = (l_shoulder.y + r_shoulder.y) / 2.0
        hands_dropped_too_low = avg_wrist_y > avg_shoulder_y + (
            MAX_BOTTOM_HAND_DROP * shoulder_dist
        )

        arm_asymmetry = abs(left_angle - right_angle) > ASYMMETRY_THRESHOLD_DEG
        excessive_lean = (
            hips_visible and lean_deg is not None and lean_deg > LEAN_BACK_WARN_DEG
        )
        response["lean_ok"] = not excessive_lean

        feedback = framing_message
        rep_completed = False
        rep_duration = rep_class = rep_form_quality = None

        if not position_ok:
            self.rep_start_time = None
            self._rep_angle_acc = 0.0
            self._current_rep_issues.clear()
        else:
            if is_lateral_raise and self.smoothed_angle > 130:
                feedback = "Press dumbbells straight UP overhead, not out to the sides."
            else:
                if excessive_lean:
                    self._current_rep_issues.add("leaning_back")
                if hands_dropped_too_low and self.stage == "bottom":
                    self._current_rep_issues.add("dropped_hands")
                if arm_asymmetry and self.stage == "top":
                    self._current_rep_issues.add("uneven_press")

                # State: Bottom -> Top
                if (
                    self.stage == "bottom"
                    and self.smoothed_angle > TOP_ANGLE
                    and wrists_above_shoulders
                ):
                    self.stage = "top"
                    self.rep_start_time = t
                    self._rep_angle_acc = 0.0

                if self.last_angle is not None and self.rep_start_time is not None:
                    self._rep_angle_acc += abs(self.smoothed_angle - self.last_angle)

                # State: Top -> Bottom (Rep Complete)
                if self.stage == "top" and self.smoothed_angle < BOTTOM_ANGLE:
                    self.stage = "bottom"
                    rep_completed = True

                if rep_completed:
                    rep_duration = (
                        (t - self.rep_start_time) if self.rep_start_time else None
                    )
                    valid = (
                        rep_duration is not None
                        and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                        and self._rep_angle_acc >= MIN_ANGLE_DELTA
                    )

                    if valid:
                        self.rep_count += 1
                        rep_class = self._classify_tempo(rep_duration)

                        if self._current_rep_issues:
                            rep_form_quality = "needs_improvement"
                            self.flawed_reps += 1
                            if "dropped_hands" in self._current_rep_issues:
                                feedback = f"Rep {self.rep_count} counted — stop dumbbells at ear level on the way down."
                            elif "leaning_back" in self._current_rep_issues:
                                feedback = f"Rep {self.rep_count} counted — keep your core tight and avoid leaning back."
                            elif "uneven_press" in self._current_rep_issues:
                                feedback = f"Rep {self.rep_count} counted — press both arms evenly overhead."
                            else:
                                feedback = f"Rep {self.rep_count} counted — work on maintaining strict form."
                        else:
                            rep_form_quality = "good"
                            self.good_reps += 1
                            feedback = f"Perfect form! Rep {self.rep_count} done."
                    else:
                        rep_completed = False
                        if rep_duration is not None and rep_duration < MIN_REP_DURATION:
                            feedback = (
                                "Movement was too fast — press with controlled motion."
                            )

                    self.rep_start_time = None
                    self._rep_angle_acc = 0.0
                    self._current_rep_issues.clear()

        self.last_angle = self.smoothed_angle

        if feedback is None and hands_dropped_too_low:
            feedback = "Keep dumbbells at ear level at the bottom."
        if feedback is None and excessive_lean:
            feedback = "Keep back straight — don't arch backward."
        if feedback is None and not self.ready:
            feedback = "Raise dumbbells to ear level to prepare."
        if feedback is None:
            feedback = "Good position — press overhead."

        response.update(
            {
                "angle": raw_angle,
                "smoothed_angle": self.smoothed_angle,
                "stage": self.stage,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_duration": rep_duration,
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "lean_ok": not excessive_lean,
                "feedback": feedback,
            }
        )
        return response


class ShoulderPressSession:
    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = ShoulderPressAnalyzer(target_reps)
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
