"""
Sit Up detector.

Movement contract
-----------------
The reference movement is a controlled floor sit-up with bent knees:

    back down / knees bent -> curl torso upright -> lower back down

The detector prefers a side or three-quarter view because the torso angle is
the most reliable signal for this exercise. A partial crunch, a straight-leg
movement, or a session that starts at the top cannot count as a rep.
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

MIN_VISIBILITY = 0.30
PERSON_VISIBILITY = 0.50
LEG_VISIBILITY = 0.28
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)

# The torso angle is measured from the image horizontal:
# 0° = lying back, 90° = upright.
BACK_DOWN_MAX_DEG = 34.0
UPRIGHT_ENTER_DEG = 58.0
MIN_TRAVEL_DEG = 28.0
MAX_KNEE_BEND_DEG = 145.0
MIN_KNEE_BEND_DEG = 38.0
ANKLE_BELOW_KNEE_TOLERANCE = 0.10
ANGLE_SMOOTH_ALPHA = 0.58

POSITION_CONFIRM_FRAMES = 4
POSITION_GRACE_FRAMES = 5
START_CONFIRM_FRAMES = 2
TOP_CONFIRM_FRAMES = 2
MIN_REP_DURATION = 0.45
MAX_REP_DURATION = 8.0
FRAME_EDGE_MARGIN = 0.035


def _visible(points: tuple[Any, ...], threshold: float = MIN_VISIBILITY) -> bool:
    return all(
        point is not None
        and (
            getattr(point, "visibility", None) is None
            or getattr(point, "visibility", 0.0) >= threshold
        )
        for point in points
    )


def _looks_like_person(landmarks: list[Any]) -> bool:
    if len(landmarks) < 33:
        return False
    visible_core = sum(
        1
        for index in CORE_LANDMARKS
        if getattr(landmarks[index], "visibility", 0.0) >= PERSON_VISIBILITY
    )
    return visible_core >= 3


def _distance(a: Any, b: Any) -> float:
    return math.hypot(float(a.x) - float(b.x), float(a.y) - float(b.y))


def _midpoint(a: Any, b: Any) -> tuple[float, float]:
    return ((float(a.x) + float(b.x)) / 2.0, (float(a.y) + float(b.y)) / 2.0)


def _angle_at(a: Any, b: Any, c: Any) -> Optional[float]:
    first = (float(a.x) - float(b.x), float(a.y) - float(b.y))
    second = (float(c.x) - float(b.x), float(c.y) - float(b.y))
    first_len = math.hypot(*first)
    second_len = math.hypot(*second)
    if first_len < 1e-7 or second_len < 1e-7:
        return None
    cosine = (first[0] * second[0] + first[1] * second[1]) / (first_len * second_len)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _torso_angle(shoulder: Any, hip: Any) -> float:
    dx = float(hip.x) - float(shoulder.x)
    dy = float(hip.y) - float(shoulder.y)
    return math.degrees(math.atan2(abs(dy), max(abs(dx), 1e-7)))


def _view_mode(shoulder_width: float, torso_length: float) -> str:
    ratio = shoulder_width / max(torso_length, 1e-7)
    if ratio >= 1.02:
        return "front"
    if ratio <= 0.58:
        return "side"
    return "angled"


def _framing_feedback(points: list[Any]) -> Optional[str]:
    for point in points:
        if point.x < FRAME_EDGE_MARGIN or point.x > 1.0 - FRAME_EDGE_MARGIN:
            return "Move back so your shoulders, hips, knees, and feet stay inside the frame."
        if point.y < FRAME_EDGE_MARGIN or point.y > 1.0 - FRAME_EDGE_MARGIN:
            return "Keep your full body inside the frame, including your feet."
    return None


def _tempo(duration: Optional[float]) -> Optional[str]:
    if duration is None:
        return None
    if duration < 0.45:
        return "too_fast"
    if duration < 0.85:
        return "fast"
    if duration < 2.60:
        return "good"
    if duration < 4.50:
        return "slow"
    return "too_slow"


class SitUpAnalyzer:
    """Stateful side-view sit-up counter with setup and full-range gates."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.stage = "setup"
        self.ready = False

        self._position_good_streak = 0
        self._position_bad_streak = 0
        self._start_streak = 0
        self._top_streak = 0
        self._seen_start = False
        self._rep_start_time: Optional[float] = None
        self._rep_start_angle: Optional[float] = None
        self._rep_peak_angle: Optional[float] = None
        self._smoothed_angle: Optional[float] = None
        self._last_angle: Optional[float] = None
        self._last_timestamp_s: Optional[float] = None
        self._angle_acc = 0.0
        self._issues: set[str] = set()
        self._session_start_time: Optional[float] = None
        self._active_side: Optional[str] = None

    def _complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _base_response(self, elapsed: float) -> dict[str, Any]:
        return {
            "pose_detected": False,
            "view_mode": None,
            "position_ok": False,
            "position_message": None,
            "ready": self.ready,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": self._complete(),
            "rep_completed": False,
            "rep_duration": None,
            "rep_avg_speed": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "angle": None,
            "smoothed_angle": None,
            "left_elbow_angle": None,
            "right_elbow_angle": None,
            "angle_velocity": None,
            "alignment_ok": False,
            "alignment_issue": None,
            "framing_ok": True,
            "framing_message": None,
            "torso_angle": None,
            "knee_angle": None,
            "knees_bent": False,
            "feet_planted": False,
            "start_position": False,
            "top_position": False,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

    def _reset_rep(self) -> None:
        self._rep_start_time = None
        self._rep_start_angle = None
        self._rep_peak_angle = None
        self._angle_acc = 0.0
        self._issues = set()

    def _finish_rep(
        self,
        response: dict[str, Any],
        timestamp_s: float,
        current_angle: float,
    ) -> None:
        duration = (
            max(0.0, timestamp_s - self._rep_start_time)
            if self._rep_start_time is not None
            else None
        )
        travel = (
            (self._rep_peak_angle or current_angle)
            - (self._rep_start_angle or current_angle)
            if self._rep_start_angle is not None
            else 0.0
        )
        if (
            duration is None
            or duration < MIN_REP_DURATION
            or duration > MAX_REP_DURATION
            or travel < MIN_TRAVEL_DEG
        ):
            response["feedback"] = (
                "Lower your back fully, then sit up with control through the whole range."
            )
            self._reset_rep()
            return

        self.rep_count += 1
        response["rep_completed"] = True
        response["rep_duration"] = round(duration, 3)
        response["rep_avg_speed"] = (
            round(self._angle_acc / duration, 2) if duration else None
        )
        response["rep_classification"] = _tempo(duration)
        if duration > 4.5:
            self._issues.add("slow_rep")

        response["rep_form_quality"] = (
            "good" if not self._issues else "needs_improvement"
        )
        if response["rep_form_quality"] == "good":
            self.good_reps += 1
        else:
            self.flawed_reps += 1
        self._reset_rep()

    def _choose_side(self, landmarks: list[Any]) -> Optional[str]:
        candidates = []
        for side, indexes in (
            (
                "left",
                (LEFT_SHOULDER, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE),
            ),
            (
                "right",
                (RIGHT_SHOULDER, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE),
            ),
        ):
            points = tuple(landmarks[index] for index in indexes)
            if _visible(points, LEG_VISIBILITY):
                length = _distance(points[0], points[1]) + _distance(
                    points[1], points[2]
                )
                candidates.append((length, side))
        if not candidates:
            return None
        if self._active_side and any(
            side == self._active_side for _, side in candidates
        ):
            return self._active_side
        return max(candidates)[1]

    def update(
        self, landmarks: Optional[list[Any]], timestamp_ms: int
    ) -> dict[str, Any]:
        timestamp_s = timestamp_ms / 1000.0
        if self._session_start_time is None:
            self._session_start_time = timestamp_s
        elapsed = max(0.0, timestamp_s - self._session_start_time)
        response = self._base_response(elapsed)

        if landmarks is None or not _looks_like_person(landmarks):
            response["feedback"] = (
                "No person detected — lie on your side with your full body visible."
            )
            self._position_good_streak = 0
            self._position_bad_streak += 1
            if self._position_bad_streak >= POSITION_GRACE_FRAMES:
                self.ready = False
            return response

        side = self._choose_side(landmarks)
        if side is None:
            response.update(
                {
                    "pose_detected": True,
                    "feedback": "Turn to a side or three-quarter view so one shoulder, hip, knee, and ankle are clear.",
                }
            )
            self._position_good_streak = 0
            self._position_bad_streak += 1
            return response
        self._active_side = side

        indexes = (
            (LEFT_SHOULDER, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE)
            if side == "left"
            else (RIGHT_SHOULDER, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE)
        )
        shoulder, hip, knee, ankle = (landmarks[index] for index in indexes)
        other_shoulder = landmarks[RIGHT_SHOULDER if side == "left" else LEFT_SHOULDER]
        other_hip = landmarks[RIGHT_HIP if side == "left" else LEFT_HIP]

        mid_shoulder = _midpoint(landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER])
        mid_hip = _midpoint(landmarks[LEFT_HIP], landmarks[RIGHT_HIP])
        torso_length = max(
            _distance(shoulder, hip), _distance(other_shoulder, other_hip)
        )
        shoulder_width = _distance(landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER])
        view_mode = _view_mode(shoulder_width, torso_length)
        torso_angle = _torso_angle(shoulder, hip)
        knee_angle = _angle_at(hip, knee, ankle)
        if self._smoothed_angle is None:
            self._smoothed_angle = torso_angle
        else:
            self._smoothed_angle = (
                ANGLE_SMOOTH_ALPHA * torso_angle
                + (1.0 - ANGLE_SMOOTH_ALPHA) * self._smoothed_angle
            )
        current_angle = self._smoothed_angle

        angle_velocity = None
        if self._last_angle is not None and self._last_timestamp_s is not None:
            dt = max(timestamp_s - self._last_timestamp_s, 1e-6)
            angle_velocity = (current_angle - self._last_angle) / dt

        knees_bent = (
            knee_angle is not None
            and MIN_KNEE_BEND_DEG <= knee_angle <= MAX_KNEE_BEND_DEG
        )
        feet_planted = float(ankle.y) >= float(knee.y) - ANKLE_BELOW_KNEE_TOLERANCE
        framing_message = _framing_feedback([shoulder, hip, knee, ankle])
        framing_ok = framing_message is None
        core_visible = _visible((shoulder, hip), MIN_VISIBILITY)
        side_view_ok = view_mode in ("side", "angled")

        start_now = bool(
            current_angle <= BACK_DOWN_MAX_DEG and knees_bent and feet_planted
        )
        top_now = bool(current_angle >= UPRIGHT_ENTER_DEG and knees_bent)
        self._start_streak = self._start_streak + 1 if start_now else 0
        self._top_streak = self._top_streak + 1 if top_now else 0
        start_confirmed = self._start_streak >= START_CONFIRM_FRAMES
        top_confirmed = self._top_streak >= TOP_CONFIRM_FRAMES

        position_now_ok = (
            core_visible and side_view_ok and knees_bent and feet_planted and framing_ok
        )
        if position_now_ok:
            self._position_good_streak += 1
            self._position_bad_streak = 0
        else:
            self._position_good_streak = 0
            self._position_bad_streak += 1
        if self._position_good_streak >= POSITION_CONFIRM_FRAMES:
            self.ready = True
        elif self._position_bad_streak >= POSITION_GRACE_FRAMES:
            self.ready = False

        position_message: Optional[str] = None
        if not side_view_ok:
            position_message = (
                "Turn to a side or three-quarter view so I can read your torso angle."
            )
        elif not core_visible:
            position_message = "Keep one shoulder and hip clearly visible."
        elif not knees_bent:
            position_message = (
                "Bend your knees and keep your feet planted on the floor."
            )
        elif not feet_planted:
            position_message = "Keep your feet planted and knees comfortably bent."
        elif not framing_ok:
            position_message = framing_message
        elif not self.ready:
            position_message = (
                "Lie back with your shoulders down to start, then curl your torso up."
                if torso_angle > BACK_DOWN_MAX_DEG
                else "Hold the bent-knee floor position while I confirm your setup."
            )

        position_ok = self.ready and position_now_ok
        response.update(
            {
                "pose_detected": True,
                "view_mode": view_mode,
                "position_ok": position_ok,
                "position_message": position_message,
                "ready": self.ready,
                "angle": round(torso_angle, 1),
                "smoothed_angle": round(current_angle, 1),
                "angle_velocity": (
                    round(angle_velocity, 2) if angle_velocity is not None else None
                ),
                "alignment_ok": position_ok,
                "alignment_issue": position_message,
                "framing_ok": framing_ok,
                "framing_message": framing_message,
                "torso_angle": round(current_angle, 1),
                "knee_angle": round(knee_angle, 1) if knee_angle is not None else None,
                "knees_bent": knees_bent,
                "feet_planted": feet_planted,
                "start_position": start_confirmed,
                "top_position": top_confirmed,
                "low_visibility": not _visible((shoulder, hip, knee, ankle), 0.55),
            }
        )

        if position_ok and knee_angle is not None:
            if start_confirmed:
                self._seen_start = True
                if self.stage == "up":
                    self._finish_rep(response, timestamp_s, current_angle)
                    self.stage = "down"
                    self._rep_start_time = timestamp_s
                    self._rep_start_angle = current_angle
                    self._rep_peak_angle = current_angle
                    self._angle_acc = 0.0
                    self._issues = set()
                elif self.stage == "setup":
                    self.stage = "down"
                    self._rep_start_time = timestamp_s
                    self._rep_start_angle = current_angle
                    self._rep_peak_angle = current_angle
                    self._angle_acc = 0.0
                    self._issues = set()
            elif top_confirmed and self._seen_start and self.stage == "down":
                self.stage = "up"
                if self._rep_peak_angle is None or current_angle > self._rep_peak_angle:
                    self._rep_peak_angle = current_angle

            if self._last_angle is not None:
                self._angle_acc += abs(current_angle - self._last_angle)
            if self.stage == "up" and (
                self._rep_peak_angle is None or current_angle > self._rep_peak_angle
            ):
                self._rep_peak_angle = current_angle

        if response["rep_completed"]:
            response["feedback"] = (
                f"Rep {self.rep_count} counted — lower your back fully before the next sit-up."
            )
        elif position_message:
            response["feedback"] = position_message
        elif not self._seen_start:
            response["feedback"] = (
                "Setup confirmed — lie back with your shoulders down, then curl up."
            )
        elif self.stage == "down":
            response["feedback"] = "Now curl your chest up until your torso is upright."
        elif self.stage == "up":
            response["feedback"] = (
                "Good sit-up — lower slowly until your shoulders return to the floor."
            )
        elif self._complete():
            response["feedback"] = (
                f"Target reached — {self.target_reps} sit-ups completed."
            )
        else:
            response["feedback"] = "Keep your feet planted and move with control."

        response.update(
            {
                "stage": self.stage,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._complete(),
            }
        )
        self._last_angle = current_angle
        self._last_timestamp_s = timestamp_s
        return response


class SitUpSession:
    """Standalone detector session using one shared PoseEngine."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = SitUpAnalyzer(target_reps)
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
