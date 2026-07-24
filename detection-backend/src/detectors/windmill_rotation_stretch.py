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

MIN_LANDMARK_VISIBILITY = 0.35
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.5
    )
    return visible_core >= 3


STRAIGHT_LEG_MIN_ANGLE = 150.0
WIDE_STANCE_RATIO_MIN = 1.18
STABLE_STANCE_FRAMES = 4
GRACE_FRAMES = 8

UPRIGHT_ANGLE_MAX = 15.0
BENT_ANGLE_MIN = 24.0
MIN_ANGLE_DELTA = 25.0
MIN_REP_DURATION = 0.35
MAX_REP_DURATION = 7.0
GOOD_DEPTH_DEG = 40.0

ARM_PATTERN_MARGIN = 0.03

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


def _visible(points) -> bool:
    for p in points:
        if p is None:
            return False
        v = getattr(p, "visibility", None)
        if v is not None and v < MIN_LANDMARK_VISIBILITY:
            return False
    return True


def _vis(p) -> float:
    v = getattr(p, "visibility", None)
    return float(v) if v is not None else 1.0


def _safe_y(p) -> float:
    return getattr(p, "y", 1.0)


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


def _lean_angle_deg(mid_shoulder, mid_hip) -> float:
    dx = mid_shoulder.x - mid_hip.x
    dy = mid_shoulder.y - mid_hip.y
    return math.degrees(math.atan2(dx, -dy))


def _bbox_aspect_points(points: list[_Point]) -> Optional[tuple[float, float]]:
    if len(points) < 4:
        return None
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    return (max(xs) - min(xs), max(ys) - min(ys))


def _framing_feedback(points: list[_Point]) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — reposition so your whole body is visible."
            )

    dims = _bbox_aspect_points(points)
    if dims is None:
        return None
    width, height = dims

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return (
            "You're too close to the camera — back up so your whole body fits in frame."
        )
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."
    return None


def _classify_tempo(duration: Optional[float]) -> Optional[str]:
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


def _choose_reach_side(l_wrist, r_wrist, l_elbow, r_elbow):
    left_score = (_safe_y(l_wrist) + 0.5 * _safe_y(l_elbow)) - (
        0.1 * _vis(l_wrist) + 0.1 * _vis(l_elbow)
    )
    right_score = (_safe_y(r_wrist) + 0.5 * _safe_y(r_elbow)) - (
        0.1 * _vis(r_wrist) + 0.1 * _vis(r_elbow)
    )
    return (
        ("left", l_wrist, r_wrist)
        if left_score > right_score
        else ("right", r_wrist, l_wrist)
    )


class WindmillAnalyzer:
    """Stateful Windmill Rotation Stretch rep counter (both sides)."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps
        self.stage = "center"
        self.rep_count = 0
        self.left_reps = 0
        self.right_reps = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.partial_rep_count = 0

        self.smoothed_angle: Optional[float] = None
        self.last_angle: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None
        self.rep_start_time: Optional[float] = None
        self._rep_angle_acc = 0.0
        self.angle_smooth_alpha = 0.55

        self.session_start_time: Optional[float] = None

        self._attempt_peak_abs_angle = 0.0
        self._attempt_side: Optional[str] = None
        self._attempt_side_votes = {"left": 0, "right": 0}
        self._attempt_arm_pattern_ok = False
        self._attempt_overhead_ok = False
        self._attempt_reach_ok = False

        self.last_completed_side: Optional[str] = None
        self._stance_streak = 0
        self._bad_streak = 0
        self.ready = False

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _reset_attempt(self):
        self.rep_start_time = None
        self._rep_angle_acc = 0.0
        self._attempt_peak_abs_angle = 0.0
        self._attempt_side = None
        self._attempt_side_votes = {"left": 0, "right": 0}
        self._attempt_arm_pattern_ok = False
        self._attempt_overhead_ok = False
        self._attempt_reach_ok = False

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
            "lean_angle": None,
            "smoothed_lean_angle": None,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "left_reps": self.left_reps,
            "right_reps": self.right_reps,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_side": None,
            "rep_duration": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "current_side": None,
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = "No person detected — step into frame."
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
        arms_visible = _visible((l_wrist, r_wrist))
        legs_visible = _visible((l_knee, r_knee, l_ankle, r_ankle))

        if not torso_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your torso clearly — make sure your shoulders and hips are both in frame."
            )
            return response

        if not arms_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your arms — step back so both wrists are visible."
            )
            return response

        response["pose_detected"] = True

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        shoulder_width = _dist(l_shoulder, r_shoulder)

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

        is_stance_ok = False
        if legs_visible and shoulder_width > 1e-6:
            l_knee_angle = _angle_deg(l_hip, l_knee, l_ankle)
            r_knee_angle = _angle_deg(r_hip, r_knee, r_ankle)
            legs_straight = (
                l_knee_angle >= STRAIGHT_LEG_MIN_ANGLE
                and r_knee_angle >= STRAIGHT_LEG_MIN_ANGLE
            )
            ankle_dist = _dist(l_ankle, r_ankle)
            wide_enough = (ankle_dist / shoulder_width) >= WIDE_STANCE_RATIO_MIN
            standing_tall = mid_hip.y < min(l_ankle.y, r_ankle.y)
            is_stance_ok = legs_straight and wide_enough and standing_tall

        if is_stance_ok:
            self._stance_streak += 1
            self._bad_streak = 0
        else:
            self._stance_streak = 0
            self._bad_streak += 1

        if self._stance_streak >= STABLE_STANCE_FRAMES:
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES:
            self.ready = False

        position_ok = self.ready
        response["position_ok"] = position_ok
        response["ready"] = self.ready

        if not legs_visible:
            position_message = "Can't see your legs — step back so your whole body, including your feet, is in frame."
        elif not position_ok:
            position_message = "Get into the start position: stand tall, feet planted wide (wider than shoulder width), arms out to the sides at shoulder height."
        else:
            position_message = None
        response["position_message"] = position_message

        raw_angle = _lean_angle_deg(mid_shoulder, mid_hip)

        if self.smoothed_angle is None:
            self.smoothed_angle = raw_angle
        else:
            self.smoothed_angle = (
                self.angle_smooth_alpha * raw_angle
                + (1 - self.angle_smooth_alpha) * self.smoothed_angle
            )

        down_side, down_wrist, up_wrist = _choose_reach_side(
            l_wrist, r_wrist, l_elbow, r_elbow
        )

        reach_ok = down_wrist.y > mid_hip.y - ARM_PATTERN_MARGIN
        overhead_ok = up_wrist.y < mid_shoulder.y + ARM_PATTERN_MARGIN
        arm_pattern_ok = reach_ok and overhead_ok

        feedback = framing_message
        rep_completed = False
        rep_duration = rep_class = rep_form_quality = None
        rep_side = None

        if not position_ok:
            if self.rep_start_time is not None:
                self._reset_attempt()
            if feedback is None:
                feedback = position_message
        else:
            abs_angle = abs(self.smoothed_angle)
            if self.last_angle is not None:
                self._rep_angle_acc += abs(self.smoothed_angle - self.last_angle)

            if self.stage == "center" and abs_angle > BENT_ANGLE_MIN:
                self.stage = "bent"
                self.rep_start_time = t
                self._rep_angle_acc = 0.0
                self._attempt_peak_abs_angle = 0.0
                self._attempt_side_votes = {"left": 0, "right": 0}
                self._attempt_arm_pattern_ok = False
                self._attempt_overhead_ok = False
                self._attempt_reach_ok = False

            if self.stage == "bent":
                self._attempt_peak_abs_angle = max(
                    self._attempt_peak_abs_angle, abs_angle
                )
                vote_weight = 1
                if _vis(down_wrist) > 0.7:
                    vote_weight += 1
                if _vis(up_wrist) > 0.7:
                    vote_weight += 1
                self._attempt_side_votes[down_side] += vote_weight
                self._attempt_reach_ok |= reach_ok
                self._attempt_overhead_ok |= overhead_ok
                self._attempt_arm_pattern_ok |= arm_pattern_ok
                response["current_side"] = down_side

                if abs_angle < UPRIGHT_ANGLE_MAX:
                    self.stage = "center"
                    rep_completed = True

            if feedback is None and self.stage == "bent" and not arm_pattern_ok:
                if not reach_ok:
                    feedback = (
                        "Reach your lower arm further down toward your opposite foot."
                    )
                elif not overhead_ok:
                    feedback = "Extend your top arm straight up overhead."

            if rep_completed:
                rep_duration = (
                    (t - self.rep_start_time)
                    if self.rep_start_time is not None
                    else None
                )
                votes = self._attempt_side_votes
                side = "left" if votes["left"] >= votes["right"] else "right"

                valid = (
                    rep_duration is not None
                    and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                    and self._rep_angle_acc >= MIN_ANGLE_DELTA
                    and self._attempt_peak_abs_angle >= BENT_ANGLE_MIN
                    and self._attempt_arm_pattern_ok
                )

                if valid:
                    self.rep_count += 1
                    if side == "left":
                        self.left_reps += 1
                    else:
                        self.right_reps += 1
                    rep_side = side
                    self.last_completed_side = side
                    rep_class = _classify_tempo(rep_duration)

                    is_good = (
                        self._attempt_peak_abs_angle >= GOOD_DEPTH_DEG
                        and self._attempt_reach_ok
                        and self._attempt_overhead_ok
                    )
                    if is_good:
                        rep_form_quality = "good"
                        self.good_reps += 1
                        feedback = f"Clean {side} windmill — nice depth ({self._attempt_peak_abs_angle:.0f}°)."
                    else:
                        rep_form_quality = "needs_improvement"
                        self.flawed_reps += 1
                        if self._attempt_peak_abs_angle < GOOD_DEPTH_DEG:
                            feedback = (
                                f"Rep {self.rep_count} counted, but deepen the hinge for a better stretch "
                                f"(reached {self._attempt_peak_abs_angle:.0f}°)."
                            )
                        elif not self._attempt_overhead_ok:
                            feedback = f"Rep {self.rep_count} counted, but keep your top arm fully extended overhead."
                        else:
                            feedback = f"Rep {self.rep_count} counted, but reach your lower arm further toward your foot."
                else:
                    rep_completed = False
                    if rep_duration is not None and rep_duration < MIN_REP_DURATION:
                        feedback = (
                            "Too fast — that one wasn't counted, control the movement."
                        )
                    elif rep_duration is not None and rep_duration > MAX_REP_DURATION:
                        feedback = "That rep took too long — not counted. Keep moving."
                    elif not self._attempt_arm_pattern_ok:
                        feedback = "Not counted — reach one arm down toward your foot while the other reaches straight up."
                    else:
                        feedback = (
                            "Not enough range of motion — not counted, hinge further."
                        )

                self._reset_attempt()

        self.last_angle = self.smoothed_angle
        self.last_timestamp_s = t

        if feedback is None and not self.ready:
            feedback = "Stand tall, feet wide, arms out to your sides — hold that T-pose to start counting."
        if feedback is None:
            feedback = "Good form — keep going."

        response.update(
            {
                "lean_angle": raw_angle,
                "smoothed_lean_angle": self.smoothed_angle,
                "stage": self.stage,
                "rep_count": self.rep_count,
                "left_reps": self.left_reps,
                "right_reps": self.right_reps,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_side": rep_side,
                "rep_duration": rep_duration,
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "feedback": feedback,
            }
        )
        return response


class WindmillSession:
    """Full Windmill Rotation Stretch session: one shared pose model + one analyzer."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = WindmillAnalyzer(target_reps)
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
