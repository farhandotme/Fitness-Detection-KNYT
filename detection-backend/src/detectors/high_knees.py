import math
from collections import deque
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

MIN_LANDMARK_VISIBILITY = 0.4
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 3


# Hip-flexion angle (shoulder-hip-knee), degrees. Standing tall => leg hangs
# roughly in line with the torso => angle near 180. Knee driven up to hip
# height => angle collapses toward ~90-100.
DOWN_ANGLE = 160.0  # standing / leg down
UP_ANGLE = 100.0  # knee driven up to (near) hip height — counts as "up"

# 0-100 "lift" score derived from the angle above, with its own hysteresis
# band driving the rep state machine (mirrors squat/lunge's depth pattern).
LIFT_RAISED_THRESH = 99.5  # only the leg that actually clears UP_ANGLE
LIFT_GROUNDED_THRESH = 15.0
MIN_LIFT_DELTA = 25.0  # total travel required for a rep to "count"
MIN_REP_DURATION = 0.15  # seconds — faster than this = uncontrolled/noise
MAX_REP_DURATION = 6.0  # seconds — slower than this = probably a pause

CALIBRATION_FRAMES = 15

# Posture: high knees wants a tall, upright torso — leaning to drive the
# knee up is a common cheat.
TORSO_LEAN_DELTA_DEG = 18.0
TORSO_LEAN_HARD_MAX_DEG = 40.0

# "Half rep" partial-rep heuristic (mirrors squat/lunge's PARTIAL_REP_* family).
PARTIAL_REP_MARGIN = 10.0
PARTIAL_REP_MIN_RISE = 18.0
PARTIAL_REP_BOUNCE = 7.0

# Cadence: high knees is usually done fast; classify pace off reps/minute.
PACE_SLOW_RPM = 40.0
PACE_FAST_RPM = 140.0

# Per-mistake form_score penalty.
MISTAKE_PENALTY = {
    "not_alternating": 15,
    "poor_posture": 15,
    "low_knee_raise": 10,
}

SCORE_HISTORY = 10  # reps kept for rolling-average form score
RPM_WINDOW = 6  # completed reps kept for reps-per-minute smoothing

# -------------------------------------------------------------------------
# Camera framing thresholds
# -------------------------------------------------------------------------
FRAME_EDGE_MARGIN = 0.03
TORSO_SPAN_TOO_CLOSE = 0.45
TORSO_SPAN_TOO_FAR = 0.10
CENTER_X_TOLERANCE = 0.28


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
    """Angle at vertex `b`, between rays b->a and b->c, in degrees."""
    ang = math.degrees(
        math.atan2(c.y - b.y, c.x - b.x) - math.atan2(a.y - b.y, a.x - b.x)
    )
    ang = abs(ang)
    if ang > 180:
        ang = 360 - ang
    return ang


def _clip(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _lift_score(angle: float) -> float:
    """Map a hip-flexion angle to a 0-100 'how high is the knee' score."""
    return 100.0 * _clip((DOWN_ANGLE - angle) / (DOWN_ANGLE - UP_ANGLE))


def _framing_feedback(l_shoulder, r_shoulder, l_hip, r_hip) -> Optional[str]:
    mid_shoulder = _midpoint(l_shoulder, r_shoulder)
    mid_hip = _midpoint(l_hip, r_hip)

    for p in (l_shoulder, r_shoulder, l_hip, r_hip):
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
        ):
            return "You're partly out of frame — center yourself with space on both sides."

    torso_span = abs(mid_hip.y - mid_shoulder.y)
    if torso_span > TORSO_SPAN_TOO_CLOSE:
        return "You're too close to the camera — step back until your whole body fits in frame."
    if torso_span < TORSO_SPAN_TOO_FAR:
        return "You're too far from the camera — move a bit closer for accurate tracking."

    if abs(mid_hip.x - 0.5) > CENTER_X_TOLERANCE:
        side = "left" if mid_hip.x < 0.5 else "right"
        return f"Move to the center of frame — you're too far to the {side}."

    return None


class HighKneeAnalyzer:
    """Stateful high-knees rep counter + leg-alternation + posture checker.

    Only one leg is considered "active" (driving a rep) at a time — the
    leg whose hip-flexion angle first crosses into the raised band. A rep
    is a single knee-up-and-back-down cycle on one leg; each knee drive is
    its own rep (this mirrors how high knees are coached and counted).
    """

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.stage = "down"  # "down" (both legs grounded) or "up" (one leg raised)
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.partial_rep_count = 0
        self.left_reps = 0
        self.right_reps = 0

        self.smoothed_lift: Optional[float] = None
        self.last_lift: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None
        self.lift_smooth_alpha = 0.5

        self.rep_start_time: Optional[float] = None
        self._lift_acc = 0.0

        self.session_start_time: Optional[float] = None

        # "Half rep" partial-rep detection (tracked while stage == "down")
        self._attempt_peak_lift: Optional[float] = None
        self._attempt_flagged = False

        # Personal posture baseline, captured at rest (standing).
        self._calib_samples: list[float] = []
        self.calibrated = False
        self._baseline_torso_lean = 0.0

        self._current_rep_issues: set[str] = set()
        self._rep_max_torso_lean_delta = 0.0
        self._rep_min_active_angle = 180.0

        self.active_leg: Optional[str] = None
        self._last_rep_leg: Optional[str] = None

        self.form_scores: deque = deque(maxlen=SCORE_HISTORY)
        self._rep_complete_times: deque = deque(maxlen=RPM_WINDOW)

    # ---------------------------------------------------------------
    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _finish_calibration(self):
        n = len(self._calib_samples)
        self._baseline_torso_lean = sum(self._calib_samples) / n
        self.calibrated = True

    @staticmethod
    def _avg(d: deque) -> Optional[float]:
        return round(sum(d) / len(d), 1) if d else None

    def _classify_pace(self, rpm: Optional[float]) -> Optional[str]:
        if rpm is None:
            return None
        if rpm < PACE_SLOW_RPM:
            return "slow"
        if rpm > PACE_FAST_RPM:
            return "fast"
        return "steady"

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "left_angle": None,
            "right_angle": None,
            "active_leg": self.active_leg,
            "lift": None,
            "smoothed_lift": None,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "partial_rep_count": self.partial_rep_count,
            "left_reps": self.left_reps,
            "right_reps": self.right_reps,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_leg": None,
            "rep_duration": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "alternation_ok": True,
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
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = "No person detected — step into frame."
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        legs_visible = _visible((l_hip, l_knee, l_ankle, r_hip, r_knee, r_ankle))
        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))

        if not legs_visible or not torso_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your full body clearly — step back so your torso "
                "and both legs are in frame."
            )
            return response

        response["pose_detected"] = True

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)

        # ---- camera framing (every frame) ----
        framing_message = _framing_feedback(l_shoulder, r_shoulder, l_hip, r_hip)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        # ---- hip-flexion angle per leg ----
        left_angle = _angle_deg(l_shoulder, l_hip, l_knee)
        right_angle = _angle_deg(r_shoulder, r_hip, r_knee)
        response["left_angle"] = round(left_angle, 1)
        response["right_angle"] = round(right_angle, 1)

        left_lift = _lift_score(left_angle)
        right_lift = _lift_score(right_angle)

        # ---- torso lean + calibration (captured while grounded) ----
        vertical_ref = _Point(mid_hip.x, mid_hip.y - 1.0)
        torso_lean = _angle_deg(vertical_ref, mid_hip, mid_shoulder)

        if self.stage == "down" and not self.calibrated:
            self._calib_samples.append(torso_lean)
            if len(self._calib_samples) >= CALIBRATION_FRAMES:
                self._finish_calibration()

        lean_delta = (
            abs(torso_lean - self._baseline_torso_lean) if self.calibrated else 0.0
        )

        rep_completed = False
        rep_leg = None

        if self.stage == "down":
            candidate_leg = None
            if left_lift >= LIFT_RAISED_THRESH and left_lift >= right_lift:
                candidate_leg = "left"
            elif right_lift >= LIFT_RAISED_THRESH:
                candidate_leg = "right"

            raw_lift = max(left_lift, right_lift)
            if self.smoothed_lift is None:
                self.smoothed_lift = raw_lift
            else:
                self.smoothed_lift = (
                    self.lift_smooth_alpha * raw_lift
                    + (1 - self.lift_smooth_alpha) * self.smoothed_lift
                )

            # ---- "half rep" partial coaching while grounded ----
            partial_feedback = None
            if (
                self._attempt_peak_lift is None
                or self.smoothed_lift > self._attempt_peak_lift
            ):
                self._attempt_peak_lift = self.smoothed_lift
            elif (
                not self._attempt_flagged
                and self._attempt_peak_lift is not None
                and self._attempt_peak_lift - self.smoothed_lift > PARTIAL_REP_BOUNCE
                and self._attempt_peak_lift < LIFT_RAISED_THRESH - PARTIAL_REP_MARGIN
                and self._attempt_peak_lift - LIFT_GROUNDED_THRESH
                > PARTIAL_REP_MIN_RISE
            ):
                self._attempt_flagged = True
                self.partial_rep_count += 1
                partial_feedback = (
                    f"Half rep — only got to {self._attempt_peak_lift:.0f}/100 knee "
                    "height, drive it higher."
                )

            if self.smoothed_lift < LIFT_GROUNDED_THRESH - 3:
                self._attempt_peak_lift = None
                self._attempt_flagged = False

            if candidate_leg is not None:
                self.stage = "up"
                self.active_leg = candidate_leg
                self.rep_start_time = t
                self._lift_acc = 0.0
                self._current_rep_issues = set()
                self._rep_max_torso_lean_delta = lean_delta
                self._rep_min_active_angle = (
                    left_angle if candidate_leg == "left" else right_angle
                )

            response["lift"] = round(raw_lift, 1)
            response["smoothed_lift"] = round(self.smoothed_lift, 1)
            if partial_feedback:
                response["feedback"] = partial_feedback

        else:  # self.stage == "up"
            active_angle = left_angle if self.active_leg == "left" else right_angle
            raw_lift = _lift_score(active_angle)
            self.smoothed_lift = (
                self.lift_smooth_alpha * raw_lift
                + (1 - self.lift_smooth_alpha) * self.smoothed_lift
                if self.smoothed_lift is not None
                else raw_lift
            )
            self._rep_min_active_angle = min(self._rep_min_active_angle, active_angle)
            self._rep_max_torso_lean_delta = max(
                self._rep_max_torso_lean_delta, lean_delta
            )

            if self.last_lift is not None:
                self._lift_acc += abs(self.smoothed_lift - self.last_lift)

            response["lift"] = round(raw_lift, 1)
            response["smoothed_lift"] = round(self.smoothed_lift, 1)

            if active_angle >= DOWN_ANGLE:
                self.stage = "down"
                rep_completed = True
                rep_leg = self.active_leg

        if self.calibrated and lean_delta > TORSO_LEAN_DELTA_DEG:
            issues = ["poor_posture"]
            messages = ["Stand tall — don't lean to drive the knee up."]
        else:
            issues, messages = [], []
        response["posture_ok"] = len(issues) == 0
        response["posture_issues"] = issues
        response["posture_messages"] = messages

        rep_duration = rep_class = rep_form_quality = None
        form_score = None
        alternation_ok = True
        feedback = framing_message

        if rep_completed:
            rep_duration = (
                (t - self.rep_start_time) if self.rep_start_time is not None else None
            )
            valid = (
                rep_duration is not None
                and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                and self._lift_acc >= MIN_LIFT_DELTA
                and rep_leg is not None
            )

            if valid:
                self.rep_count += 1
                if rep_leg == "left":
                    self.left_reps += 1
                else:
                    self.right_reps += 1

                if rep_duration < 0.35:
                    rep_class = "fast"
                elif rep_duration < 0.8:
                    rep_class = "good"
                elif rep_duration < 1.5:
                    rep_class = "slow"
                else:
                    rep_class = "too_slow"

                if self._last_rep_leg is not None and self._last_rep_leg == rep_leg:
                    self._current_rep_issues.add("not_alternating")
                alternation_ok = "not_alternating" not in self._current_rep_issues
                self._last_rep_leg = rep_leg

                if self._rep_max_torso_lean_delta > TORSO_LEAN_DELTA_DEG:
                    self._current_rep_issues.add("poor_posture")
                if self._rep_min_active_angle > UP_ANGLE + PARTIAL_REP_MARGIN:
                    self._current_rep_issues.add("low_knee_raise")

                form_score = 100
                for issue in self._current_rep_issues:
                    form_score -= MISTAKE_PENALTY.get(issue, 10)
                form_score = max(0, form_score)
                self.form_scores.append(form_score)

                self._rep_complete_times.append(t)

                if self._current_rep_issues:
                    rep_form_quality = "needs_improvement"
                    self.flawed_reps += 1
                    issue_text = ", ".join(
                        i.replace("_", " ") for i in sorted(self._current_rep_issues)
                    )
                    feedback = (
                        f"Rep {self.rep_count} ({rep_leg} leg) counted, "
                        f"but watch your form ({issue_text})."
                    )
                else:
                    rep_form_quality = "good"
                    self.good_reps += 1
                    feedback = f"Clean {rep_leg}-knee rep — {rep_class} tempo."
            else:
                rep_completed = False
                if rep_duration is not None and rep_duration < MIN_REP_DURATION:
                    feedback = "Too fast — that one wasn't counted, control the movement."
                elif rep_duration is not None and rep_duration > MAX_REP_DURATION:
                    feedback = "That rep took too long — not counted. Keep moving."
                else:
                    feedback = "Not enough knee drive — not counted."

            self.rep_start_time = None
            self._lift_acc = 0.0
            self._current_rep_issues = set()
            self.active_leg = None

        self.last_lift = self.smoothed_lift
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
                "Stand tall facing the camera and hold still for a second — "
                "calibrating your posture."
            )
        if feedback is None:
            feedback = "Good position — drive those knees up."

        response.update(
            {
                "rep_completed": rep_completed,
                "rep_leg": rep_leg,
                "rep_duration": round(rep_duration, 2) if rep_duration is not None else None,
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "alternation_ok": alternation_ok,
                "form_score": form_score,
                "avg_form_score": self._avg(self.form_scores),
                "reps_per_minute": reps_per_minute,
                "pace_classification": pace_classification,
                "session_complete": self._is_complete(),
                "feedback": feedback,
            }
        )
        return response


class HighKneeSession:
    """Full high-knees session: one shared pose model + one analyzer.

    `target_reps` / `target_sets` / `set_number` are the coach-assigned plan
    for this user, supplied by the caller (the websocket route, from query
    params) — same convention as squat/push-up/lunge. The frontend does not
    decide on its own whether a set/exercise is done; `session_complete`
    (this set's reps are done) and `exercise_complete` (the whole assigned
    plan — all sets — is done) are computed here.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = HighKneeAnalyzer(target_reps)
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
