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
    RIGHT_ANKLE,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
    PoseEngine,
)

MIN_LANDMARK_VISIBILITY = 0.4
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)

FRAME_EDGE_MARGIN = 0.03
TORSO_SPAN_TOO_CLOSE = 0.45
TORSO_SPAN_TOO_FAR = 0.10
CENTER_X_TOLERANCE = 0.25

DRIVE_THRESHOLD = 0.16
RETURN_THRESHOLD = 0.23
MIN_REP_DURATION = 0.20
MAX_REP_DURATION = 4.0
CALIBRATION_FRAMES = 12

PLANK_READY_FRAMES = 5
PLANK_BAD_FRAMES = 8

MISTAKE_PENALTY = {
    "both_knees_drive": 20,
    "poor_posture": 20,
    "not_alternating": 15,
    "not_plank": 15,
    "too_short": 15,
    "too_fast": 10,
    "too_slow": 10,
}

SCORE_HISTORY = 10
RPM_WINDOW = 6


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


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 3


class MountainClimberAnalyzer:
    """Stateful mountain-climber rep counter + posture checker."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.stage = "ready"
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.partial_rep_count = 0

        self.active_leg: Optional[str] = None
        self.last_leg: Optional[str] = None

        self.session_start_time: Optional[float] = None
        self.rep_start_time: Optional[float] = None
        self._rep_motion_acc = 0.0
        self._rep_issues: set[str] = set()

        self.form_scores: deque = deque(maxlen=SCORE_HISTORY)
        self._rep_complete_times: deque = deque(maxlen=RPM_WINDOW)

        self._calib_samples: list[float] = []
        self.calibrated = False
        self._baseline_alignment = 180.0

        self._plank_streak = 0
        self._bad_streak = 0
        self.ready = False

        self._attempt_min_drive: Optional[float] = None
        self._attempt_flagged = False

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    @staticmethod
    def _avg(d: deque) -> Optional[float]:
        return round(sum(d) / len(d), 1) if d else None

    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 2.0:
            return "too_slow"
        if duration >= 1.0:
            return "slow"
        if duration >= 0.45:
            return "good"
        return "fast"

    def _finish_calibration(self):
        if self._calib_samples:
            self._baseline_alignment = sum(self._calib_samples) / len(
                self._calib_samples
            )
            self.calibrated = True

    def _framing_feedback(self, points: list[_Point]) -> Optional[str]:
        for p in points:
            if (
                p.x < FRAME_EDGE_MARGIN
                or p.x > 1 - FRAME_EDGE_MARGIN
                or p.y < FRAME_EDGE_MARGIN
                or p.y > 1 - FRAME_EDGE_MARGIN
            ):
                return "Step back so your whole body stays visible in frame."

        if len(points) < 4:
            return None

        xs = [p.x for p in points]
        ys = [p.y for p in points]
        width = max(xs) - min(xs)
        height = max(ys) - min(ys)

        if width > 0.95 or height > 0.95:
            return "You are too close to the camera — step back."
        if width < 0.15 and height < 0.15:
            return "Move a bit closer so the camera can track you clearly."

        mid_x = (min(xs) + max(xs)) / 2.0
        if abs(mid_x - 0.5) > CENTER_X_TOLERANCE:
            side = "left" if mid_x < 0.5 else "right"
            return f"Center yourself in frame — you are too far to the {side}."

        return None

    def _body_alignment(
        self, l_shoulder, r_shoulder, l_hip, r_hip, l_ankle, r_ankle
    ) -> Optional[float]:
        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        mid_ankle = _midpoint(l_ankle, r_ankle)
        return _angle_deg(mid_shoulder, mid_hip, mid_ankle)

    def _plank_quality(self, alignment: float) -> tuple[bool, list[str]]:
        issues = []
        if alignment < 140:
            issues.append("not_plank")
        if self.calibrated and abs(alignment - self._baseline_alignment) > 12:
            issues.append("poor_posture")
        return (len(issues) == 0), issues

    def _knee_drive_value(self, hip, knee, shoulder_width: float) -> float:
        return (hip.y - knee.y) / max(shoulder_width, 1e-6)

    def _tempo_feedback(self, rep_duration: float) -> Optional[str]:
        if rep_duration < MIN_REP_DURATION:
            return "Too fast — control the movement."
        if rep_duration > MAX_REP_DURATION:
            return "That rep took too long — keep the rhythm."
        return None

    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "active_leg": self.active_leg,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_leg": None,
            "rep_duration": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "form_score": None,
            "avg_form_score": self._avg(self.form_scores),
            "reps_per_minute": None,
            "pace_classification": None,
            "posture_ok": True,
            "posture_issues": [],
            "posture_messages": [],
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "calibrated": self.calibrated,
            "low_visibility": False,
            "left_knee_drive": None,
            "right_knee_drive": None,
            "body_alignment": None,
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

        body_visible = _visible(
            (l_shoulder, r_shoulder, l_hip, r_hip, l_knee, r_knee, l_ankle, r_ankle)
        )
        arm_visible = _visible((l_elbow, r_elbow, l_wrist, r_wrist))
        if not body_visible or not arm_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Keep your shoulders, arms, hips, knees, and ankles visible."
            )
            return response

        response["pose_detected"] = True

        points = [
            l_shoulder,
            r_shoulder,
            l_hip,
            r_hip,
            l_wrist,
            r_wrist,
            l_knee,
            r_knee,
            l_ankle,
            r_ankle,
        ]
        framing_message = self._framing_feedback(points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        alignment = self._body_alignment(
            l_shoulder, r_shoulder, l_hip, r_hip, l_ankle, r_ankle
        )
        if alignment is None:
            response["feedback"] = "Unable to read body alignment clearly."
            return response

        response["body_alignment"] = round(alignment, 1)

        shoulder_width = max(_dist(l_shoulder, r_shoulder), 1e-6)
        left_drive = self._knee_drive_value(l_hip, l_knee, shoulder_width)
        right_drive = self._knee_drive_value(r_hip, r_knee, shoulder_width)
        response["left_knee_drive"] = round(left_drive, 3)
        response["right_knee_drive"] = round(right_drive, 3)

        left_driven = left_drive >= DRIVE_THRESHOLD
        right_driven = right_drive >= DRIVE_THRESHOLD
        left_returned = left_drive <= RETURN_THRESHOLD
        right_returned = right_drive <= RETURN_THRESHOLD

        posture_ok, posture_issues = self._plank_quality(alignment)
        issues: set[str] = set(posture_issues)
        posture_messages: list[str] = []

        if "not_plank" in issues:
            posture_messages.append(
                "Return to a straight high plank — keep your body rigid."
            )
        if "poor_posture" in issues:
            posture_messages.append("Keep your hips level and avoid sagging or piking.")

        if left_driven and right_driven:
            issues.add("both_knees_drive")
            posture_messages.append(
                "Drive one knee at a time — do not pull both knees in together."
            )

        if self.stage == "ready":
            if posture_ok and not left_driven and not right_driven:
                if not self.calibrated:
                    self._calib_samples.append(alignment)
                    if len(self._calib_samples) >= CALIBRATION_FRAMES:
                        self._finish_calibration()

                self._plank_streak += 1
                self._bad_streak = 0
                if self._plank_streak >= PLANK_READY_FRAMES:
                    self.ready = True
            else:
                self._plank_streak = 0
                self._bad_streak += 1
                if self._bad_streak >= PLANK_BAD_FRAMES:
                    self.ready = False

            if self.ready:
                if left_driven and not right_driven:
                    self.stage = "drive"
                    self.active_leg = "left"
                    self.rep_start_time = t
                    self._rep_motion_acc = 0.0
                    self._rep_issues = set(issues)
                elif right_driven and not left_driven:
                    self.stage = "drive"
                    self.active_leg = "right"
                    self.rep_start_time = t
                    self._rep_motion_acc = 0.0
                    self._rep_issues = set(issues)

        elif self.stage == "drive":
            if self.active_leg == "left":
                if right_driven and not left_driven:
                    self._rep_issues.add("both_knees_drive")
                if left_returned:
                    rep_completed = True
                    rep_leg = "left"
                else:
                    rep_completed = False
            else:
                if left_driven and not right_driven:
                    self._rep_issues.add("both_knees_drive")
                if right_returned:
                    rep_completed = True
                    rep_leg = "right"
                else:
                    rep_completed = False

            if self.rep_start_time is not None:
                self._rep_motion_acc += abs(left_drive - right_drive)

            if rep_completed:
                rep_duration = (
                    t - self.rep_start_time if self.rep_start_time is not None else None
                )
                valid = (
                    rep_duration is not None
                    and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                    and self._rep_motion_acc >= 0.05
                )

                self.rep_start_time = None
                self.stage = "ready"
                self.active_leg = None

                if valid:
                    self.rep_count += 1
                    if self.last_leg == rep_leg:
                        self._rep_issues.add("not_alternating")
                    self.last_leg = rep_leg
                    self._rep_complete_times.append(t)

                    rep_class = self._classify_tempo(rep_duration)
                    if self._rep_issues:
                        self.flawed_reps += 1
                        rep_form_quality = "needs_improvement"
                        form_score = max(
                            0,
                            100
                            - sum(MISTAKE_PENALTY.get(i, 10) for i in self._rep_issues),
                        )
                        feedback = f"Rep counted, but your form needs work ({', '.join(sorted(self._rep_issues))})."
                    else:
                        self.good_reps += 1
                        rep_form_quality = "good"
                        form_score = 100
                        if rep_class in ("good", "fast"):
                            feedback = f"Clean {rep_leg} knee drive."
                        elif rep_class in ("slow", "too_slow"):
                            feedback = f"Good depth, nice and controlled ({rep_duration:.2f}s)."
                        else:
                            feedback = f"Clean rep, but control the tempo ({rep_duration:.2f}s)."

                    response["rep_completed"] = True
                    response["rep_leg"] = rep_leg
                    response["rep_duration"] = round(rep_duration, 2)
                    response["rep_classification"] = rep_class
                    response["rep_form_quality"] = rep_form_quality
                    response["form_score"] = form_score
                    self.form_scores.append(form_score)
                    response["feedback"] = feedback
                    self._rep_issues = set()
                else:
                    if rep_duration is not None and rep_duration < MIN_REP_DURATION:
                        response["feedback"] = (
                            "Too fast — that one wasn't counted, control the movement."
                        )
                    elif rep_duration is not None and rep_duration > MAX_REP_DURATION:
                        response["feedback"] = (
                            "That rep took too long — not counted. Keep moving."
                        )
                    else:
                        response["feedback"] = (
                            "Not enough range of motion — not counted."
                        )
                    self._rep_issues = set()

        if self.stage == "ready" and not response["rep_completed"]:
            if not self.calibrated:
                response["feedback"] = (
                    "Hold your plank and keep still for a moment while I calibrate."
                )
            elif issues:
                response["feedback"] = (
                    "Keep your hips straight and move one knee at a time."
                )
            elif response["feedback"] is None:
                response["feedback"] = (
                    "Good plank — drive one knee in and return cleanly."
                )

        if response["feedback"] is None and posture_messages:
            response["feedback"] = posture_messages[0]

        reps_per_minute = None
        if len(self._rep_complete_times) >= 2:
            span = self._rep_complete_times[-1] - self._rep_complete_times[0]
            if span > 0:
                reps_per_minute = round(
                    (len(self._rep_complete_times) - 1) / span * 60.0, 1
                )

        response["reps_per_minute"] = reps_per_minute
        response["pace_classification"] = self._classify_tempo(
            None if reps_per_minute is None else 60.0 / reps_per_minute
        )
        response["rep_count"] = self.rep_count
        response["good_reps"] = self.good_reps
        response["flawed_reps"] = self.flawed_reps
        response["session_complete"] = self._is_complete()
        response["posture_ok"] = len(issues) == 0
        response["posture_issues"] = sorted(issues)
        response["posture_messages"] = posture_messages

        return response


class MountainClimberSession:
    """Mountain climber session: one shared pose model + one analyzer."""

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
