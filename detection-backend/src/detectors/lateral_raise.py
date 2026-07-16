"""
Lateral (side) raise rep counting + full-body form correction.

Design
------
`LateralRaiseAnalyzer` is a pure, stateful, whole-body analyzer, structured
the same way as the other detectors in this package (`shoulder_press.py`,
`high_knees.py`) — it knows nothing about the camera or the MediaPipe
model; `LateralRaiseSession` owns a single shared `PoseEngine` and feeds it
landmarks every frame.

Rep counting
------------
Driven by the average shoulder-abduction angle across both arms (the angle
at the shoulder between the torso line, shoulder->hip, and the upper arm,
shoulder->elbow — falling back to whichever single arm is visible). Arms
hanging at the sides is the rest position (`REST_ANGLE`, upper arm roughly
parallel to the torso); a rep is raising both arms out to the sides up to
shoulder height (`RAISE_ANGLE`, upper arm roughly perpendicular to the
torso) and back down. Same "start grounded, drive up, return completes the
rep" state machine as `high_knees.py`/`shoulder_press.py`.

Form tracking — this is the point of the exercise, so it's checked hard
------------------------------------------------------------------------
Four independent issues are tracked every single frame, each with its own
plain-language correction, and each contributes to a per-rep `form_score`:

  1. **`poor_posture`** — leaning or swinging the torso to sling the
     weights up with momentum instead of raising them under control.
     Measured the same way as `high_knees.py`/`shoulder_press.py`: the
     shoulder-hip line's angle off vertical, compared against a personal
     baseline captured at rest, so it adapts to each person's stance and
     camera angle.
  2. **`shrugging`** — hiking the shoulders up toward the ears to help
     lift the weight (letting the traps do the work instead of the
     deltoids), instead of keeping the shoulders down and raising purely
     from the arms. Measured as the nose-to-shoulder vertical gap
     shrinking below a personal baseline captured at rest.
  3. **`elbows_too_bent`** — the elbows should stay soft but essentially
     straight throughout; bending them a lot turns the movement into an
     upright row and shifts the work off the target muscle. Measured as
     the shoulder-elbow-wrist angle dropping too far from straight at the
     top of the rep.
  4. **`asymmetric_raise`** — both arms should rise together. Measured as
     the max gap between the left and right abduction angle during the
     "up" phase of a rep; one arm lagging/leading the other means the
     weights are tilting or one side is compensating for the other.

A rep still counts the moment it meets range-of-motion and tempo
requirements even with a form issue flagged (a flawed rep still counts —
"perfect or nothing" is discouraging), tagged `rep_form_quality:
"needs_improvement"`, with `posture_issues`/`posture_messages` telling the
user exactly what to fix on the next rep. A raise that never reaches
shoulder height is tracked as a "half rep" (same bounce-detection
heuristic as `high_knees.py`/`shoulder_press.py`) instead of being
silently dropped.
"""

import math
from collections import deque
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


# Shoulder-abduction angle (hip-shoulder-elbow), degrees. Arms hanging at
# the sides => upper arm roughly parallel to the torso => angle near 0-20.
# Arms raised out to shoulder height => upper arm roughly perpendicular to
# the torso => angle near 80-90.
REST_ANGLE = 20.0
RAISE_ANGLE = 80.0

LIFT_RAISED_THRESH = 99.5  # lift score at/above this = genuinely at shoulder height
LIFT_GROUNDED_THRESH = 15.0
MIN_ANGLE_DELTA = 30.0  # total travel required for a rep to "count"
MIN_REP_DURATION = 0.25  # seconds — faster than this = uncontrolled/momentum
MAX_REP_DURATION = 6.0  # seconds — slower than this = probably a pause

CALIBRATION_FRAMES = 15

# "Half rep" partial-rep heuristic (same family as high_knees.py).
PARTIAL_REP_MARGIN = 10.0
PARTIAL_REP_MIN_RISE = 18.0
PARTIAL_REP_BOUNCE = 7.0

# ---- form-correction thresholds ----
TORSO_LEAN_DELTA_DEG = 14.0  # leaning/swinging off your calibrated baseline
SHRUG_DELTA_RATIO = 0.10  # (baseline nose-shoulder gap - current gap) / torso_length
ELBOW_STRAIGHT_MIN_DEG = 150.0  # shoulder-elbow-wrist angle at the top of the rep
ASYMMETRY_DEG = 18.0  # max allowed gap between left/right abduction angle mid-raise

PACE_SLOW_RPM = 15.0
PACE_FAST_RPM = 55.0

MISTAKE_PENALTY = {
    "poor_posture": 15,
    "shrugging": 15,
    "elbows_too_bent": 10,
    "asymmetric_raise": 15,
}

SCORE_HISTORY = 10
RPM_WINDOW = 6

# -------------------------------------------------------------------------
# Camera framing thresholds
# -------------------------------------------------------------------------
FRAME_EDGE_MARGIN = 0.03
TORSO_SPAN_TOO_CLOSE = 0.60
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


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _clip(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _lift_score(angle: float) -> float:
    """Map an abduction angle to a 0-100 'how close to shoulder height' score."""
    return 100.0 * _clip((angle - REST_ANGLE) / (RAISE_ANGLE - REST_ANGLE))


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
        return "You're too close to the camera — step back so your arms fit fully out to the sides in frame."
    if torso_span < TORSO_SPAN_TOO_FAR:
        return "You're too far from the camera — move a bit closer for accurate tracking."

    if abs(mid_hip.x - 0.5) > CENTER_X_TOLERANCE:
        side = "left" if mid_hip.x < 0.5 else "right"
        return f"Move to the center of frame — you're too far to the {side}."

    return None


class LateralRaiseAnalyzer:
    """Stateful lateral-raise rep counter + posture/shrug/elbow/symmetry checker."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.stage = "down"  # "down" = arms at sides, "up" = raised to shoulder height
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.partial_rep_count = 0

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

        # Personal baselines, captured at rest (arms at sides).
        self._calib_lean_samples: list[float] = []
        self._calib_shrug_samples: list[float] = []
        self.calibrated = False
        self._baseline_torso_lean = 0.0
        self._baseline_shrug_gap = 0.0

        self._current_rep_issues: set[str] = set()
        self._rep_max_torso_lean_delta = 0.0
        self._rep_max_shrug_delta = 0.0
        self._rep_min_elbow_angle = 180.0
        self._rep_max_asymmetry = 0.0

        self.form_scores: deque = deque(maxlen=SCORE_HISTORY)
        self._rep_complete_times: deque = deque(maxlen=RPM_WINDOW)

    # ---------------------------------------------------------------
    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _finish_calibration(self):
        n = len(self._calib_lean_samples)
        self._baseline_torso_lean = sum(self._calib_lean_samples) / n
        self._baseline_shrug_gap = sum(self._calib_shrug_samples) / len(
            self._calib_shrug_samples
        )
        self.calibrated = True

    @staticmethod
    def _avg(d: deque) -> Optional[float]:
        return round(sum(d) / len(d), 1) if d else None

    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration < 0.5:
            return "fast"
        if duration < 1.3:
            return "good"
        if duration < 2.5:
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

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "left_abduction_angle": None,
            "right_abduction_angle": None,
            "angle": None,
            "lift": None,
            "smoothed_lift": None,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "partial_rep_count": self.partial_rep_count,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
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
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = "No person detected — step into frame."
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        nose = landmarks[NOSE]

        left_arm_ok = _visible((l_shoulder, l_elbow, l_wrist, l_hip))
        right_arm_ok = _visible((r_shoulder, r_elbow, r_wrist, r_hip))
        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))

        if not left_arm_ok and not right_arm_ok:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your arms clearly — adjust the camera so your "
                "shoulders, elbows, and wrists are all in frame."
            )
            return response

        if not torso_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your torso — make sure your shoulders and hips "
                "are both in frame."
            )
            return response

        response["pose_detected"] = True

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)

        # ---- camera framing (every frame) ----
        framing_message = _framing_feedback(l_shoulder, r_shoulder, l_hip, r_hip)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        # ---- shoulder-abduction angle per arm (drives rep counting) ----
        left_angle = (
            _angle_deg(l_hip, l_shoulder, l_elbow) if left_arm_ok else None
        )
        right_angle = (
            _angle_deg(r_hip, r_shoulder, r_elbow) if right_arm_ok else None
        )
        response["left_abduction_angle"] = (
            round(left_angle, 1) if left_angle is not None else None
        )
        response["right_abduction_angle"] = (
            round(right_angle, 1) if right_angle is not None else None
        )

        angles = [a for a in (left_angle, right_angle) if a is not None]
        raw_angle = sum(angles) / len(angles)
        response["angle"] = round(raw_angle, 1)

        arm_gap = (
            abs(left_angle - right_angle)
            if left_angle is not None and right_angle is not None
            else 0.0
        )

        raw_lift = _lift_score(raw_angle)
        if self.smoothed_lift is None:
            self.smoothed_lift = raw_lift
        else:
            self.smoothed_lift = (
                self.lift_smooth_alpha * raw_lift
                + (1 - self.lift_smooth_alpha) * self.smoothed_lift
            )

        # ---- elbow straightness (every frame) ----
        elbow_angles = []
        if left_arm_ok:
            elbow_angles.append(_angle_deg(l_shoulder, l_elbow, l_wrist))
        if right_arm_ok:
            elbow_angles.append(_angle_deg(r_shoulder, r_elbow, r_wrist))
        min_elbow_angle = min(elbow_angles) if elbow_angles else 180.0

        # ---- torso lean/swing + calibration (captured at rest) ----
        vertical_ref = _Point(mid_hip.x, mid_hip.y - 1.0)
        torso_lean = _angle_deg(vertical_ref, mid_hip, mid_shoulder)

        # ---- shrug metric: nose-to-shoulder vertical gap, normalized ----
        nose_ok = _visible((nose,))
        shrug_gap = (
            (mid_shoulder.y - nose.y) / torso_length if nose_ok else None
        )

        if self.stage == "down" and not self.calibrated:
            self._calib_lean_samples.append(torso_lean)
            if shrug_gap is not None:
                self._calib_shrug_samples.append(shrug_gap)
            if len(self._calib_lean_samples) >= CALIBRATION_FRAMES and len(
                self._calib_shrug_samples
            ) >= min(CALIBRATION_FRAMES, 5):
                self._finish_calibration()

        lean_delta = (
            abs(torso_lean - self._baseline_torso_lean) if self.calibrated else 0.0
        )
        shrug_delta = (
            (self._baseline_shrug_gap - shrug_gap) / torso_length
            if self.calibrated and shrug_gap is not None
            else 0.0
        )

        rep_completed = False

        if self.stage == "down":
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
                response["feedback"] = (
                    f"Half rep — only got to {self._attempt_peak_lift:.0f}/100 of "
                    "shoulder height, raise all the way up."
                )

            if self.smoothed_lift < LIFT_GROUNDED_THRESH - 3:
                self._attempt_peak_lift = None
                self._attempt_flagged = False

            if self.smoothed_lift >= LIFT_RAISED_THRESH:
                self.stage = "up"
                self.rep_start_time = t
                self._lift_acc = 0.0
                self._current_rep_issues = set()
                self._rep_max_torso_lean_delta = lean_delta
                self._rep_max_shrug_delta = shrug_delta
                self._rep_min_elbow_angle = min_elbow_angle
                self._rep_max_asymmetry = arm_gap

        else:  # self.stage == "up"
            self._rep_max_torso_lean_delta = max(
                self._rep_max_torso_lean_delta, lean_delta
            )
            self._rep_max_shrug_delta = max(self._rep_max_shrug_delta, shrug_delta)
            self._rep_min_elbow_angle = min(self._rep_min_elbow_angle, min_elbow_angle)
            self._rep_max_asymmetry = max(self._rep_max_asymmetry, arm_gap)

            if self.last_lift is not None:
                self._lift_acc += abs(self.smoothed_lift - self.last_lift)

            if self.smoothed_lift <= LIFT_GROUNDED_THRESH:
                self.stage = "down"
                rep_completed = True

        response["lift"] = round(raw_lift, 1)
        response["smoothed_lift"] = round(self.smoothed_lift, 1)

        rep_duration = rep_class = rep_form_quality = None
        form_score = None
        feedback = response.get("feedback") or framing_message

        if rep_completed:
            rep_duration = (
                (t - self.rep_start_time) if self.rep_start_time is not None else None
            )
            valid = (
                rep_duration is not None
                and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                and self._lift_acc >= MIN_ANGLE_DELTA
            )

            if valid:
                self.rep_count += 1
                rep_class = self._classify_tempo(rep_duration)

                if self._rep_max_torso_lean_delta > TORSO_LEAN_DELTA_DEG:
                    self._current_rep_issues.add("poor_posture")
                if self._rep_max_shrug_delta > SHRUG_DELTA_RATIO:
                    self._current_rep_issues.add("shrugging")
                if self._rep_min_elbow_angle < ELBOW_STRAIGHT_MIN_DEG:
                    self._current_rep_issues.add("elbows_too_bent")
                if self._rep_max_asymmetry > ASYMMETRY_DEG:
                    self._current_rep_issues.add("asymmetric_raise")

                form_score = 100
                for issue in self._current_rep_issues:
                    form_score -= MISTAKE_PENALTY.get(issue, 10)
                form_score = max(0, form_score)
                self.form_scores.append(form_score)
                self._rep_complete_times.append(t)

                issue_messages = {
                    "poor_posture": "Keep your torso still — don't lean or swing to sling the weight up.",
                    "shrugging": "Keep your shoulders down — you're hiking them up toward your ears.",
                    "elbows_too_bent": "Keep your elbows softer but straighter — you're bending them too much.",
                    "asymmetric_raise": "Raise both arms together evenly — one side is leading the other.",
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
                    feedback = f"Clean lateral raise — {rep_class} tempo, full range."

                response["posture_ok"] = len(self._current_rep_issues) == 0
                response["posture_issues"] = sorted(self._current_rep_issues)
                response["posture_messages"] = messages
            else:
                rep_completed = False
                if rep_duration is not None and rep_duration < MIN_REP_DURATION:
                    feedback = "Too fast — that one wasn't counted, control the movement."
                elif rep_duration is not None and rep_duration > MAX_REP_DURATION:
                    feedback = "That rep took too long — not counted. Keep moving."
                else:
                    feedback = "Not enough range — not counted."

            self.rep_start_time = None
            self._lift_acc = 0.0
            self._current_rep_issues = set()
            self._rep_max_torso_lean_delta = 0.0
            self._rep_max_shrug_delta = 0.0
            self._rep_min_elbow_angle = 180.0
            self._rep_max_asymmetry = 0.0
        else:
            # Live, every-frame posture feedback even mid-rep, so the user
            # gets corrected in real time instead of only after the fact.
            live_issues = []
            live_messages = []
            if lean_delta > TORSO_LEAN_DELTA_DEG:
                live_issues.append("poor_posture")
                live_messages.append(
                    "Keep your torso still — don't lean or swing to sling the weight up."
                )
            if shrug_delta > SHRUG_DELTA_RATIO:
                live_issues.append("shrugging")
                live_messages.append(
                    "Keep your shoulders down — you're hiking them up toward your ears."
                )
            if self.stage == "up" and min_elbow_angle < ELBOW_STRAIGHT_MIN_DEG:
                live_issues.append("elbows_too_bent")
                live_messages.append(
                    "Keep your elbows softer but straighter as you raise."
                )
            response["posture_ok"] = len(live_issues) == 0
            response["posture_issues"] = live_issues
            response["posture_messages"] = live_messages
            if feedback is None and live_messages:
                feedback = live_messages[0]

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
                "Stand tall with your arms relaxed at your sides for a "
                "second — calibrating your posture."
            )
        if feedback is None:
            feedback = "Good position — raise both arms out to shoulder height."

        response.update(
            {
                "rep_completed": rep_completed,
                "rep_duration": round(rep_duration, 2) if rep_duration is not None else None,
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "form_score": form_score,
                "avg_form_score": self._avg(self.form_scores),
                "reps_per_minute": reps_per_minute,
                "pace_classification": pace_classification,
                "session_complete": self._is_complete(),
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
    """Full lateral-raise session: one shared pose model + one analyzer.

    `target_reps` / `target_sets` / `set_number` are the coach-assigned plan
    for this user, supplied by the caller (the websocket route, from query
    params) — same convention as the other exercises. The frontend does not
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
