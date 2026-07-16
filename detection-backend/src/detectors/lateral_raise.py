import math
from collections import deque
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

MIN_LANDMARK_VISIBILITY = 0.4
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)

FRAME_EDGE_MARGIN = 0.03
TORSO_SPAN_TOO_CLOSE = 0.55
TORSO_SPAN_TOO_FAR = 0.10
CENTER_X_TOLERANCE = 0.28

CALIBRATION_FRAMES = 15

# Raise is side-dominant: arms start down and move to roughly shoulder height.
DOWN_SCORE = 12.0
TOP_SCORE = 88.0
MIN_SCORE_DELTA = 25.0
MIN_REP_DURATION = 0.30
MAX_REP_DURATION = 8.0

# Lateral raise form thresholds
TORSO_SWAY_DELTA_DEG = 10.0
SHRUG_DELTA_RATIO = 0.08
ELBOW_SLIGHT_BEND_MIN = 145.0
ELBOW_SLIGHT_BEND_MAX = 178.0
TOP_SHOULDER_HEIGHT_TOL = 0.06
TOP_WRIST_HEIGHT_TOL = 0.08
ASYMMETRY_DEG = 18.0
MOMENTUM_MIN_ACC = 0.12

PACE_SLOW_RPM = 14.0
PACE_FAST_RPM = 38.0

MISTAKE_PENALTY = {
    "poor_posture": 15,
    "shrugging": 10,
    "over_shoot": 10,
    "under_raise": 15,
    "asymmetric_raise": 15,
    "elbows_locked": 10,
    "elbows_too_bent": 10,
    "momentum": 15,
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


def _clip(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _raise_score(angle: float) -> float:
    return 100.0 * _clip((angle - DOWN_SCORE) / (TOP_SCORE - DOWN_SCORE))


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 3


def _framing_feedback(l_shoulder, r_shoulder, l_hip, r_hip) -> Optional[str]:
    mid_shoulder = _midpoint(l_shoulder, r_shoulder)
    mid_hip = _midpoint(l_hip, r_hip)

    for p in (l_shoulder, r_shoulder, l_hip, r_hip):
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
        ):
            return "You're partly out of frame — leave space around both arms."

    torso_span = abs(mid_hip.y - mid_shoulder.y)
    if torso_span > TORSO_SPAN_TOO_CLOSE:
        return "You're too close to the camera — step back so both arms fit in frame."
    if torso_span < TORSO_SPAN_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    if abs(mid_hip.x - 0.5) > CENTER_X_TOLERANCE:
        side = "left" if mid_hip.x < 0.5 else "right"
        return f"Move to the center of frame — you're too far to the {side}."

    return None


class LateralRaiseAnalyzer:
    """Stateful lateral-raise rep counter + posture/form checker."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.stage = "down"
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.partial_rep_count = 0

        self.left_score: Optional[float] = None
        self.right_score: Optional[float] = None
        self.smoothed_raise: Optional[float] = None
        self.last_raise: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None
        self.raise_smooth_alpha = 0.5

        self.rep_start_time: Optional[float] = None
        self._raise_acc = 0.0
        self.session_start_time: Optional[float] = None

        self._attempt_peak_raise: Optional[float] = None
        self._attempt_flagged = False

        self._calib_samples: list[float] = []
        self.calibrated = False
        self._baseline_torso_lean = 0.0

        self._current_rep_issues: set[str] = set()
        self._rep_max_torso_delta = 0.0
        self._rep_max_shrug_delta = 0.0
        self._rep_max_asymmetry = 0.0
        self._rep_max_top_error = 0.0
        self._rep_has_locked_elbows = False
        self._rep_has_over_bent = False

        self.form_scores: deque = deque(maxlen=SCORE_HISTORY)
        self._rep_complete_times: deque = deque(maxlen=RPM_WINDOW)

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _finish_calibration(self):
        n = len(self._calib_samples)
        self._baseline_torso_lean = sum(self._calib_samples) / n
        self.calibrated = True

    @staticmethod
    def _avg(d: deque) -> Optional[float]:
        return round(sum(d) / len(d), 1) if d else None

    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration < 0.5:
            return "fast"
        if duration < 1.4:
            return "good"
        if duration < 2.8:
            return "slow"
        return "too_slow"

    def _classify_pace(self, rpm: Optional[float]) -> Optional[str]:
        if rpm is None:
            return None
        if rpm < PACE_SLOW_RPM:
            return "slow"
        if rpm > PACE_FAST_RPM:
            return "fast"
        return "steady"

    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "left_raise": None,
            "right_raise": None,
            "angle": None,
            "raise_score": None,
            "smoothed_raise": None,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "partial_rep_count": self.partial_rep_count,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_side": None,
            "rep_duration": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "calibrated": self.calibrated,
            "posture_ok": True,
            "posture_issues": [],
            "posture_messages": [],
            "framing_ok": True,
            "framing_message": None,
            "form_score": None,
            "avg_form_score": self._avg(self.form_scores),
            "reps_per_minute": None,
            "pace_classification": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
            "exercise_complete": False,
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = "No person detected — step into frame."
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]

        left_ok = _visible((l_shoulder, l_elbow, l_wrist))
        right_ok = _visible((r_shoulder, r_elbow, r_wrist))
        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))

        if not left_ok and not right_ok:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your arms clearly — keep both shoulders, elbows, and wrists in frame."
            )
            return response

        if not torso_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your torso clearly — keep your shoulders and hips visible."
            )
            return response

        response["pose_detected"] = True

        framing_message = _framing_feedback(l_shoulder, r_shoulder, l_hip, r_hip)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        shoulder_width = max(_dist(l_shoulder, r_shoulder), 1e-6)
        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        vertical_ref = _Point(mid_hip.x, mid_hip.y - 1.0)
        torso_lean = _angle_deg(vertical_ref, mid_hip, mid_shoulder)

        if self.stage == "down" and not self.calibrated:
            self._calib_samples.append(torso_lean)
            if len(self._calib_samples) >= CALIBRATION_FRAMES:
                self._finish_calibration()

        lean_delta = (
            abs(torso_lean - self._baseline_torso_lean) if self.calibrated else 0.0
        )

        def side_score(side_shoulder, side_elbow, side_wrist, side_name: str) -> float:
            arm_len = max(_dist(side_shoulder, side_wrist), 1e-6)
            shoulder_rise = (side_shoulder.y - mid_shoulder.y) / shoulder_width
            elbow_rise = (side_elbow.y - mid_shoulder.y) / shoulder_width
            wrist_rise = (side_wrist.y - mid_shoulder.y) / shoulder_width
            raise_val = max(0.0, (mid_shoulder.y - side_wrist.y) / shoulder_width)
            elbow_angle = _angle_deg(side_shoulder, side_elbow, side_wrist)
            if side_name == "left":
                response["left_raise"] = round(raise_val, 3)
            else:
                response["right_raise"] = round(raise_val, 3)
            if elbow_angle < ELBOW_SLIGHT_BEND_MIN:
                self._rep_has_locked_elbows = True
            if elbow_angle > ELBOW_SLIGHT_BEND_MAX:
                self._rep_has_over_bent = True
            if raise_val > self._rep_max_top_error:
                self._rep_max_top_error = raise_val
            return raise_val

        left_raise = (
            side_score(l_shoulder, l_elbow, l_wrist, "left") if left_ok else None
        )
        right_raise = (
            side_score(r_shoulder, r_elbow, r_wrist, "right") if right_ok else None
        )

        raises = [v for v in (left_raise, right_raise) if v is not None]
        raw_raise = sum(raises) / len(raises)
        response["angle"] = round(raw_raise, 1)

        raw_score = _raise_score(raw_raise)
        if self.smoothed_raise is None:
            self.smoothed_raise = raw_score
        else:
            self.smoothed_raise = (
                self.raise_smooth_alpha * raw_score
                + (1 - self.raise_smooth_alpha) * self.smoothed_raise
            )

        shoulder_height_error = 0.0
        if left_ok and right_ok:
            left_shoulder_to_wrist = abs(l_wrist.y - l_shoulder.y) / shoulder_width
            right_shoulder_to_wrist = abs(r_wrist.y - r_shoulder.y) / shoulder_width
            shoulder_height_error = max(left_shoulder_to_wrist, right_shoulder_to_wrist)

        arm_gap = (
            abs(left_raise - right_raise)
            if left_raise is not None and right_raise is not None
            else 0.0
        )

        if self.stage == "down":
            if (
                self._attempt_peak_raise is None
                or self.smoothed_raise > self._attempt_peak_raise
            ):
                self._attempt_peak_raise = self.smoothed_raise
            elif (
                not self._attempt_flagged
                and self._attempt_peak_raise is not None
                and self._attempt_peak_raise - self.smoothed_raise > 7.0
                and self._attempt_peak_raise < TOP_SCORE - 10.0
                and self._attempt_peak_raise > 20.0
            ):
                self._attempt_flagged = True
                self.partial_rep_count += 1
                response["feedback"] = (
                    f"Half rep — you only raised to about {self._attempt_peak_raise:.0f}/100. "
                    "Lift to shoulder height with control."
                )

            if self.smoothed_raise < DOWN_SCORE + 3:
                self._attempt_peak_raise = None
                self._attempt_flagged = False

            if self.smoothed_raise >= TOP_SCORE:
                self.stage = "up"
                self.rep_start_time = t
                self._raise_acc = 0.0
                self._current_rep_issues = set()
                self._rep_max_torso_delta = lean_delta
                self._rep_max_shrug_delta = 0.0
                self._rep_max_asymmetry = arm_gap
                self._rep_max_top_error = shoulder_height_error

        else:
            self._rep_max_torso_delta = max(self._rep_max_torso_delta, lean_delta)
            self._rep_max_shrug_delta = max(
                self._rep_max_shrug_delta, abs(torso_lean - self._baseline_torso_lean)
            )
            self._rep_max_asymmetry = max(self._rep_max_asymmetry, arm_gap)
            self._rep_max_top_error = max(
                self._rep_max_top_error, shoulder_height_error
            )

            if self.last_raise is not None:
                self._raise_acc += abs(self.smoothed_raise - self.last_raise)

            if self.smoothed_raise <= DOWN_SCORE:
                self.stage = "down"
                rep_completed = True
            else:
                rep_completed = False

        response["raise_score"] = round(raw_score, 1)
        response["smoothed_raise"] = round(self.smoothed_raise, 1)

        rep_completed = response["rep_completed"]
        rep_duration = rep_class = rep_form_quality = None
        form_score = None
        feedback = response.get("feedback") or framing_message

        if self.stage == "up":
            if self._rep_max_torso_delta > TORSO_SWAY_DELTA_DEG:
                self._current_rep_issues.add("poor_posture")
            if self._rep_max_asymmetry > ASYMMETRY_DEG:
                self._current_rep_issues.add("asymmetric_raise")
            if self._rep_has_locked_elbows:
                self._current_rep_issues.add("elbows_locked")
            if self._rep_has_over_bent:
                self._current_rep_issues.add("elbows_too_bent")

        if rep_completed:
            rep_duration = (
                (t - self.rep_start_time) if self.rep_start_time is not None else None
            )
            valid = (
                rep_duration is not None
                and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                and self._raise_acc >= MIN_SCORE_DELTA
            )

            if valid:
                self.rep_count += 1
                rep_class = self._classify_tempo(rep_duration)

                if self._rep_max_torso_delta > TORSO_SWAY_DELTA_DEG:
                    self._current_rep_issues.add("poor_posture")
                if self._rep_max_asymmetry > ASYMMETRY_DEG:
                    self._current_rep_issues.add("asymmetric_raise")
                if self._rep_max_top_error < 0.02:
                    self._current_rep_issues.add("under_raise")
                if self._rep_max_top_error > TOP_SHOULDER_HEIGHT_TOL:
                    self._current_rep_issues.add("over_shoot")
                if self._rep_has_locked_elbows:
                    self._current_rep_issues.add("elbows_locked")
                if self._rep_has_over_bent:
                    self._current_rep_issues.add("elbows_too_bent")

                form_score = 100
                for issue in self._current_rep_issues:
                    form_score -= MISTAKE_PENALTY.get(issue, 10)
                form_score = max(0, form_score)

                self.form_scores.append(form_score)
                self._rep_complete_times.append(t)

                issue_messages = {
                    "poor_posture": "Keep your torso steady — don't swing your body to lift the weights.",
                    "shrugging": "Keep your shoulders down — don't shrug up toward your ears.",
                    "over_shoot": "Stop around shoulder height — don't raise the dumbbells too high.",
                    "under_raise": "Lift to shoulder height before lowering.",
                    "asymmetric_raise": "Raise both sides evenly — one arm is leading too much.",
                    "elbows_locked": "Keep a slight bend in your elbows — don't lock them out.",
                    "elbows_too_bent": "Keep only a slight bend in your elbows — don't curl the weights.",
                    "momentum": "Use control — don't swing the weights with momentum.",
                }
                messages = [issue_messages[i] for i in sorted(self._current_rep_issues)]

                if self._current_rep_issues:
                    rep_form_quality = "needs_improvement"
                    self.flawed_reps += 1
                    feedback = (
                        f"Rep {self.rep_count} counted, but watch your form: "
                        + " ".join(messages)
                    )
                else:
                    rep_form_quality = "good"
                    self.good_reps += 1
                    feedback = "Clean lateral raise — shoulder-height control and good symmetry."

                response["posture_ok"] = len(self._current_rep_issues) == 0
                response["posture_issues"] = sorted(self._current_rep_issues)
                response["posture_messages"] = messages
            else:
                rep_completed = False
                if rep_duration is not None and rep_duration < MIN_REP_DURATION:
                    feedback = (
                        "Too fast — that rep wasn't counted, control the movement."
                    )
                elif rep_duration is not None and rep_duration > MAX_REP_DURATION:
                    feedback = "That rep took too long — not counted. Keep moving."
                else:
                    feedback = "Not enough range of motion — raise to shoulder height."

            self.rep_start_time = None
            self._raise_acc = 0.0
            self._current_rep_issues = set()
            self._rep_max_torso_delta = 0.0
            self._rep_max_shrug_delta = 0.0
            self._rep_max_asymmetry = 0.0
            self._rep_max_top_error = 0.0
            self._rep_has_locked_elbows = False
            self._rep_has_over_bent = False
        else:
            live_issues = []
            live_messages = []

            if lean_delta > TORSO_SWAY_DELTA_DEG:
                live_issues.append("poor_posture")
                live_messages.append("Keep your torso steady — don't swing your body.")

            if self.stage == "up" and arm_gap > ASYMMETRY_DEG:
                live_issues.append("asymmetric_raise")
                live_messages.append(
                    "Raise both sides evenly — one arm is leading too much."
                )

            if shoulder_height_error > TOP_SHOULDER_HEIGHT_TOL and self.stage == "up":
                live_issues.append("under_raise")
                live_messages.append("Lift to shoulder height before lowering.")

            response["posture_ok"] = len(live_issues) == 0
            response["posture_issues"] = live_issues
            response["posture_messages"] = live_messages
            if feedback is None and live_messages:
                feedback = live_messages[0]

        self.last_raise = self.smoothed_raise
        self.last_timestamp_s = t

        reps_per_minute = None
        if len(self._rep_complete_times) >= 2:
            span = self._rep_complete_times[-1] - self._rep_complete_times[0]
            if span > 0:
                reps_per_minute = round(
                    (len(self._rep_complete_times) - 1) / span * 60.0, 1
                )

        pace_classification = self._classify_pace(reps_per_minute)

        if feedback is None and not self.calibrated:
            feedback = (
                "Hold the start position for a moment — calibrating your baseline."
            )
        if feedback is None:
            feedback = "Raise straight out to the side, lead with the elbows, and stop at shoulder height."

        response.update(
            {
                "pose_detected": True,
                "rep_completed": rep_completed,
                "rep_duration": (
                    round(rep_duration, 2) if rep_duration is not None else None
                ),
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "form_score": form_score,
                "avg_form_score": self._avg(self.form_scores),
                "reps_per_minute": reps_per_minute,
                "pace_classification": pace_classification,
                "session_complete": self._is_complete(),
                "exercise_complete": False,
                "stage": self.stage,
                "feedback": feedback,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "partial_rep_count": self.partial_rep_count,
            }
        )
        return response


class LateralRaiseSession:
    """Full lateral raise session: one shared pose model + one analyzer."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = LateralRaiseAnalyzer(target_reps)
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
