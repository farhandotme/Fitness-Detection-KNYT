import math
from collections import deque
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

MIN_LANDMARK_VISIBILITY = 0.4
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)

STANCE_RATIO_RESUME = 1.25
STANCE_RATIO_BROKEN = 1.12

FRONT_KNEE_HARD_MIN_RESUME = 60.0
FRONT_KNEE_HARD_MAX_RESUME = 155.0
FRONT_KNEE_HARD_MIN_BROKEN = 55.0
FRONT_KNEE_HARD_MAX_BROKEN = 158.0

BACK_KNEE_RESUME = 130.0
BACK_KNEE_BROKEN = 124.0

ARM_STRAIGHT_RESUME = 75.0
ARM_STRAIGHT_BROKEN = 70.0

ARM_TILT_RESUME = 36.0
ARM_TILT_BROKEN = 42.0

WINGSPAN_RATIO_RESUME = 1.38
WINGSPAN_RATIO_BROKEN = 1.25

FRONT_KNEE_GOOD_MIN = 65.0
FRONT_KNEE_GOOD_MAX = 150.0

BACK_KNEE_GOOD = 160.0
ARM_STRAIGHT_GOOD = 125.0
ARM_TILT_GOOD = 32.0
WINGSPAN_RATIO_GOOD = 1.65

ARM_REACH_RATIO_FLAW = 0.30
KNEE_TRACKING_FLAW = 0.40
TORSO_LEAN_FLAW = 35.0

MISTAKE_PENALTY = {
    "front_knee_depth": 10,
    "back_leg_bend": 8,
    "arms_uneven": 8,
    "elbows_soft": 6,
    "arm_tucked": 6,
    "knee_tracking": 10,
    "torso_lean": 6,
}

SCORE_HISTORY = 30
SCORE_SAMPLE_INTERVAL = 1.0

FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.97
BBOX_TOO_FAR = 0.18

BROKEN_FRAME_BUFFER = 3
RECOVER_FRAME_BUFFER = 2


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


def _looks_like_a_person(landmarks) -> bool:
    if landmarks is None:
        return False
    visible_core = 0
    for i in CORE_LANDMARKS:
        p = landmarks[i]
        if p is not None and getattr(p, "visibility", 0.0) > 0.6:
            visible_core += 1
    return visible_core >= 3


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


def _tilt_from_horizontal_deg(a, b) -> float:
    dx = abs(b.x - a.x)
    dy = abs(b.y - a.y)
    if dx < 1e-6 and dy < 1e-6:
        return 90.0
    return math.degrees(math.atan2(dy, max(dx, 1e-9)))


def _lateral_deviation(top, mid, bottom) -> float:
    span = max(_dist(top, bottom), 1e-6)
    dy = bottom.y - top.y
    if abs(dy) < 1e-6:
        return 0.0
    frac = (mid.y - top.y) / dy
    line_x_at_mid = top.x + frac * (bottom.x - top.x)
    return (mid.x - line_x_at_mid) / span


def _framing_feedback(points: list[_Point]) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return "You're partly out of frame — step back so your whole stance and both arms fit in the shot."

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return (
            "You're too close to the camera — back up so your whole pose fits in frame."
        )
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class WarriorIIAnalyzer:
    def __init__(self, target_seconds: Optional[int] = None):
        self.target_seconds = target_seconds
        self.front_leg: Optional[str] = None
        self.hold_active = False
        self.started = False
        self.hold_seconds = 0.0
        self.good_seconds = 0.0
        self.flawed_seconds = 0.0
        self.current_streak_seconds = 0.0
        self.best_streak_seconds = 0.0
        self.break_count = 0
        self.last_timestamp_s: Optional[float] = None
        self.session_start_time: Optional[float] = None
        self._was_complete = False
        self.form_scores: deque[int] = deque(maxlen=SCORE_HISTORY)
        self._last_score_sample_time: Optional[float] = None
        self._broken_frame_streak = 0
        self._good_frame_streak = 0

    def _is_complete(self) -> bool:
        return (
            self.target_seconds is not None and self.hold_seconds >= self.target_seconds
        )

    def _pick_front_leg(self, l_knee_angle: float, r_knee_angle: float) -> str:
        if self.front_leg is None:
            return "left" if l_knee_angle <= r_knee_angle else "right"
        current_angle = l_knee_angle if self.front_leg == "left" else r_knee_angle
        other_side = "right" if self.front_leg == "left" else "left"
        other_angle = r_knee_angle if self.front_leg == "left" else l_knee_angle
        if other_angle + 12.0 < current_angle:
            return other_side
        return self.front_leg

    def _score_gate(
        self,
        stance_ratio: float,
        front_knee_angle: float,
        back_knee_angle: float,
        left_elbow_angle: float,
        right_elbow_angle: float,
        left_arm_tilt: float,
        right_arm_tilt: float,
        wingspan_ratio: float,
        torso_lean: float,
        frame_holding: bool,
    ) -> tuple[bool, dict[str, bool]]:
        if frame_holding:
            stance_ok = stance_ratio >= STANCE_RATIO_BROKEN
            front_knee_ok = (
                FRONT_KNEE_HARD_MIN_BROKEN
                <= front_knee_angle
                <= FRONT_KNEE_HARD_MAX_BROKEN
            )
            back_knee_ok = back_knee_angle >= BACK_KNEE_BROKEN
            arms_straight_ok = (
                left_elbow_angle >= ARM_STRAIGHT_BROKEN
                and right_elbow_angle >= ARM_STRAIGHT_BROKEN
            )
            arms_level_ok = (
                left_arm_tilt <= ARM_TILT_BROKEN and right_arm_tilt <= ARM_TILT_BROKEN
            )
            wingspan_ok = wingspan_ratio >= WINGSPAN_RATIO_BROKEN
        else:
            stance_ok = stance_ratio >= STANCE_RATIO_RESUME
            front_knee_ok = (
                FRONT_KNEE_HARD_MIN_RESUME
                <= front_knee_angle
                <= FRONT_KNEE_HARD_MAX_RESUME
            )
            back_knee_ok = back_knee_angle >= BACK_KNEE_RESUME
            arms_straight_ok = (
                left_elbow_angle >= ARM_STRAIGHT_RESUME
                and right_elbow_angle >= ARM_STRAIGHT_RESUME
            )
            arms_level_ok = (
                left_arm_tilt <= ARM_TILT_RESUME and right_arm_tilt <= ARM_TILT_RESUME
            )
            wingspan_ok = wingspan_ratio >= WINGSPAN_RATIO_RESUME

        score = sum(
            [
                stance_ok,
                front_knee_ok,
                back_knee_ok,
                arms_straight_ok,
                arms_level_ok,
                wingspan_ok,
            ]
        )
        hard_ok = score >= 4

        if torso_lean > 38.0:
            hard_ok = False

        return hard_ok, {
            "stance_ok": stance_ok,
            "front_knee_ok": front_knee_ok,
            "back_knee_ok": back_knee_ok,
            "arms_straight_ok": arms_straight_ok,
            "arms_level_ok": arms_level_ok,
            "wingspan_ok": wingspan_ok,
        }

    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "front_leg": self.front_leg,
            "front_knee_angle": None,
            "back_knee_angle": None,
            "left_elbow_angle": None,
            "right_elbow_angle": None,
            "left_arm_tilt": None,
            "right_arm_tilt": None,
            "wingspan_ratio": None,
            "stance_ratio": None,
            "torso_lean": None,
            "hold_state": (
                "holding"
                if self.started and self.hold_active
                else ("broken" if self.started else "not_started")
            ),
            "is_holding": False,
            "hold_seconds": round(self.hold_seconds, 2),
            "good_seconds": round(self.good_seconds, 2),
            "flawed_seconds": round(self.flawed_seconds, 2),
            "current_streak_seconds": round(self.current_streak_seconds, 2),
            "best_streak_seconds": round(self.best_streak_seconds, 2),
            "break_count": self.break_count,
            "target_seconds": self.target_seconds,
            "session_complete": self._is_complete(),
            "target_reached": False,
            "hold_quality": None,
            "posture_ok": True,
            "posture_issues": [],
            "posture_messages": [],
            "framing_ok": True,
            "framing_message": None,
            "form_score": None,
            "avg_form_score": self._avg(self.form_scores),
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        dt = 0.0
        if self.last_timestamp_s is not None:
            dt = max(0.0, min(t - self.last_timestamp_s, 0.5))
        self.last_timestamp_s = t

        if landmarks is None or not _looks_like_a_person(landmarks):
            self._register_broken_frame()
            response["feedback"] = (
                "No person detected — step into frame, facing the camera in a wide lunge stance with both arms out."
            )
            response.update(self._progress_fields())
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        required_ok = _visible(
            (
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
        )

        if not required_ok:
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._register_broken_frame()
            response["feedback"] = (
                "Can't see your full body clearly — make sure both arms, both legs, and your feet are all visible in frame."
            )
            response.update(self._progress_fields())
            return response

        response["pose_detected"] = True

        bbox_points = [
            _Point(p.x, p.y)
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
        ]
        framing_message = _framing_feedback(bbox_points)

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        hip_width = max(_dist(l_hip, r_hip), 1e-6)
        ankle_dist = _dist(l_ankle, r_ankle)
        stance_ratio = ankle_dist / hip_width
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)

        l_knee_angle = _angle_deg(l_hip, l_knee, l_ankle)
        r_knee_angle = _angle_deg(r_hip, r_knee, r_ankle)
        self.front_leg = self._pick_front_leg(l_knee_angle, r_knee_angle)
        front_knee_angle = l_knee_angle if self.front_leg == "left" else r_knee_angle
        back_knee_angle = r_knee_angle if self.front_leg == "left" else l_knee_angle

        left_elbow_angle = _angle_deg(l_shoulder, l_elbow, l_wrist)
        right_elbow_angle = _angle_deg(r_shoulder, r_elbow, r_wrist)
        left_arm_tilt = _tilt_from_horizontal_deg(l_shoulder, l_wrist)
        right_arm_tilt = _tilt_from_horizontal_deg(r_shoulder, r_wrist)
        left_reach_ratio = _dist(l_shoulder, l_wrist) / torso_length
        right_reach_ratio = _dist(r_shoulder, r_wrist) / torso_length
        wingspan_ratio = _dist(l_wrist, r_wrist) / torso_length

        torso_lean = _tilt_from_horizontal_deg(mid_hip, mid_shoulder)
        torso_lean = abs(90.0 - torso_lean)

        hard_ok, gate_flags = self._score_gate(
            stance_ratio,
            front_knee_angle,
            back_knee_angle,
            left_elbow_angle,
            right_elbow_angle,
            left_arm_tilt,
            right_arm_tilt,
            wingspan_ratio,
            torso_lean,
            self.hold_active,
        )

        holding_now = framing_message is None and hard_ok

        if holding_now:
            self._good_frame_streak += 1
            self._broken_frame_streak = 0
        else:
            self._broken_frame_streak += 1
            self._good_frame_streak = 0

        if (
            self.hold_active
            and not holding_now
            and self._broken_frame_streak < BROKEN_FRAME_BUFFER
        ):
            holding_now = True
        if (
            not self.hold_active
            and not holding_now
            and self._good_frame_streak >= RECOVER_FRAME_BUFFER
        ):
            holding_now = True

        issues: list[str] = []
        messages: list[str] = []

        if holding_now:
            if (
                front_knee_angle < FRONT_KNEE_GOOD_MIN
                or front_knee_angle > FRONT_KNEE_GOOD_MAX
            ):
                issues.append("front_knee_depth")
                if front_knee_angle > FRONT_KNEE_GOOD_MAX:
                    messages.append("Bend your front knee a bit more.")
                else:
                    messages.append("Ease the bend slightly.")

            if back_knee_angle < BACK_KNEE_GOOD:
                issues.append("back_leg_bend")
                messages.append("Straighten your back leg fully.")

            if left_arm_tilt > ARM_TILT_GOOD or right_arm_tilt > ARM_TILT_GOOD:
                issues.append("arms_uneven")
                messages.append("Level your arms at shoulder height.")

            if (
                left_elbow_angle < ARM_STRAIGHT_GOOD
                or right_elbow_angle < ARM_STRAIGHT_GOOD
            ):
                issues.append("elbows_soft")
                messages.append("Straighten your elbows more.")

            if (
                left_reach_ratio < ARM_REACH_RATIO_FLAW
                or right_reach_ratio < ARM_REACH_RATIO_FLAW
            ):
                issues.append("arm_tucked")
                messages.append("Reach both arms farther outward.")

            front_hip = l_hip if self.front_leg == "left" else r_hip
            front_knee = l_knee if self.front_leg == "left" else r_knee
            front_ankle = l_ankle if self.front_leg == "left" else r_ankle
            knee_dev = _lateral_deviation(front_hip, front_knee, front_ankle)
            if abs(knee_dev) > KNEE_TRACKING_FLAW:
                issues.append("knee_tracking")
                messages.append("Keep the front knee tracking over the toes and ankle.")

            if torso_lean > TORSO_LEAN_FLAW:
                issues.append("torso_lean")
                messages.append("Keep your torso upright.")

        form_score = None
        hold_quality = None

        if holding_now:
            if not self.hold_active:
                self.current_streak_seconds = 0.0
            self.hold_active = True
            self.started = True

            self.hold_seconds += dt
            self.current_streak_seconds += dt
            if self.current_streak_seconds > self.best_streak_seconds:
                self.best_streak_seconds = self.current_streak_seconds

            if issues:
                self.flawed_seconds += dt
                hold_quality = "needs_improvement"
            else:
                self.good_seconds += dt
                hold_quality = "good"

            form_score = 100
            for issue in issues:
                form_score -= MISTAKE_PENALTY.get(issue, 6)
            form_score = max(0, form_score)

            if (
                self._last_score_sample_time is None
                or t - self._last_score_sample_time >= SCORE_SAMPLE_INTERVAL
            ):
                self.form_scores.append(form_score)
                self._last_score_sample_time = t
        else:
            self._register_broken_frame()

        is_complete = self._is_complete()
        target_reached = is_complete and not self._was_complete
        self._was_complete = is_complete

        feedback = framing_message
        if feedback is None and not gate_flags["stance_ok"]:
            feedback = "Widen your stance a little more."
        if feedback is None and not gate_flags["front_knee_ok"]:
            feedback = "Bend the front knee more."
        if feedback is None and not gate_flags["back_knee_ok"]:
            feedback = "Straighten the back leg."
        if feedback is None and not gate_flags["wingspan_ok"]:
            feedback = "Extend both arms fully."
        if feedback is None and not gate_flags["arms_straight_ok"]:
            feedback = "Straighten your elbows."
        if feedback is None and not gate_flags["arms_level_ok"]:
            feedback = "Keep both arms level with your shoulders."
        if feedback is None and messages:
            feedback = messages[0]
        if feedback is None and target_reached:
            feedback = f"Target reached — {self.target_seconds}s held, nice work!"
        if feedback is None and holding_now:
            feedback = "Strong Warrior II — keep holding!"
        if feedback is None:
            feedback = "Get back into Warrior II to resume the timer."

        response.update(
            {
                "pose_detected": True,
                "front_leg": self.front_leg,
                "front_knee_angle": round(front_knee_angle, 1),
                "back_knee_angle": round(back_knee_angle, 1),
                "left_elbow_angle": round(left_elbow_angle, 1),
                "right_elbow_angle": round(right_elbow_angle, 1),
                "left_arm_tilt": round(left_arm_tilt, 1),
                "right_arm_tilt": round(right_arm_tilt, 1),
                "wingspan_ratio": round(wingspan_ratio, 2),
                "stance_ratio": round(stance_ratio, 2),
                "torso_lean": round(torso_lean, 1),
                "hold_state": "holding" if holding_now else "broken",
                "is_holding": holding_now,
                "target_reached": target_reached,
                "hold_quality": hold_quality,
                "posture_ok": len(issues) == 0,
                "posture_issues": issues,
                "posture_messages": messages,
                "framing_ok": framing_message is None,
                "framing_message": framing_message,
                "form_score": form_score,
                "avg_form_score": self._avg(self.form_scores),
                "feedback": feedback,
            }
        )
        response.update(self._progress_fields())
        return response

    def _register_broken_frame(self):
        if self.hold_active:
            self.break_count += 1
        self.hold_active = False
        self.current_streak_seconds = 0.0

    def _progress_fields(self) -> dict[str, Any]:
        return {
            "hold_seconds": round(self.hold_seconds, 2),
            "good_seconds": round(self.good_seconds, 2),
            "flawed_seconds": round(self.flawed_seconds, 2),
            "current_streak_seconds": round(self.current_streak_seconds, 2),
            "best_streak_seconds": round(self.best_streak_seconds, 2),
            "break_count": self.break_count,
            "session_complete": self._is_complete(),
        }

    @staticmethod
    def _avg(values: "deque[int]") -> Optional[int]:
        if not values:
            return None
        return round(sum(values) / len(values))


class WarriorIISession:
    def __init__(
        self,
        target_seconds: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = WarriorIIAnalyzer(target_seconds)
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
