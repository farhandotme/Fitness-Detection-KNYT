import math
from collections import deque
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_FOOT_INDEX,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_FOOT_INDEX,
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


# Front-knee angle (hip-knee-ankle), degrees.
FRONT_KNEE_DOWN_ANGLE = 165.0  # standing, leg straight
FRONT_KNEE_UP_ANGLE = 100.0  # bottom of a good lunge, thigh ~horizontal

# Knee-height gap (|l_knee.y - r_knee.y|) normalized by torso length — the
# primary "how staggered/dropped is the stance" signal.
KNEE_HEIGHT_DIFF_TARGET = 0.32
KNEE_HEIGHT_DIFF_NEUTRAL = 0.05  # below this, legs are considered "even" (standing)

# Combined 0-100 "depth" hysteresis band driving the rep state machine.
DEPTH_CLOSED_THRESH = 20.0
DEPTH_OPEN_THRESH = 68.0
MIN_DEPTH_DELTA = 30.0  # total travel required for a rep to "count"
MIN_REP_DURATION = 0.4  # seconds — faster than this = uncontrolled/momentum
MAX_REP_DURATION = 10.0  # seconds — slower than this = probably a pause, not a rep

CALIBRATION_FRAMES = 15

# Posture: a lunge wants a tall, upright torso — less forgiving of forward
# lean than a squat.
TORSO_LEAN_DELTA_DEG = 20.0
TORSO_LEAN_HARD_MAX_DEG = 45.0

# Back knee must visibly lower too, not just the front leg.
BACK_KNEE_BEND_MAX_ANGLE = 140.0

# Front knee travelling past the front toes (or ankle, as a fallback),
# normalized by torso length, in the direction of the step.
KNEE_PAST_TOE_RATIO = 0.07

# Front knee's sideways drift off the hip-ankle line ("thigh line"),
# normalized by torso length.
KNEE_TRACKING_MAX_DEVIATION = 0.13

# "Half rep" partial-rep heuristic (mirrors squat's PARTIAL_REP_* family).
PARTIAL_REP_MARGIN = 10.0
PARTIAL_REP_MIN_RISE = 18.0
PARTIAL_REP_BOUNCE = 7.0

LEG_BALANCE_WARN_DIFF = 2  # reps difference before nudging to switch legs

# Per-mistake form_score penalty.
MISTAKE_PENALTY = {
    "shallow_lunge": 25,
    "knee_past_toes": 20,
    "knee_tracking": 18,
    "back_knee_not_lowered": 15,
    "poor_posture": 15,
}

SCORE_HISTORY = 10  # reps kept for rolling-average form score

# -------------------------------------------------------------------------
# Camera framing / stance-position thresholds
# -------------------------------------------------------------------------
FRAME_EDGE_MARGIN = 0.03
TORSO_SPAN_TOO_CLOSE = 0.42
TORSO_SPAN_TOO_FAR = 0.09
CENTER_X_TOLERANCE = 0.25


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


def _line_deviation(p0, p1, point, normalize_by: float) -> float:
    """Signed perpendicular distance from `point` to the line through
    `p0`->`p1`, normalized by `normalize_by`. Used for the front knee's
    sideways drift off the hip-ankle ("thigh") line."""
    dx, dy = p1.x - p0.x, p1.y - p0.y
    line_len = math.hypot(dx, dy)
    if line_len < 1e-9:
        return 0.0
    cross = dx * (point.y - p0.y) - dy * (point.x - p0.x)
    return (cross / line_len) / max(normalize_by, 1e-6)


def _framing_feedback(
    l_shoulder, r_shoulder, l_hip, r_hip, legs_visible: bool
) -> Optional[str]:
    """Coaches the user into a good spot for the camera to track a lunge —
    checked every frame, independent of exercise form.

    Checks, in order of how badly they break tracking:
      1. Part of the body clipped at a frame edge.
      2. Legs/feet not visible (can't tell front leg from back leg
         without both knees and ankles).
      3. Too close / too far from the camera.
      4. Standing off to one side instead of centered.
    """
    mid_shoulder = _midpoint(l_shoulder, r_shoulder)
    mid_hip = _midpoint(l_hip, r_hip)

    for p in (l_shoulder, r_shoulder, l_hip, r_hip):
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — center yourself with space on both sides."
            )

    if not legs_visible:
        return (
            "Step back so both legs and feet are visible — a lunge needs your "
            "full body, front foot to back foot, in frame."
        )

    torso_span = abs(mid_hip.y - mid_shoulder.y)
    if torso_span > TORSO_SPAN_TOO_CLOSE:
        return "You're too close to the camera — step back until your whole body fits in frame."
    if torso_span < TORSO_SPAN_TOO_FAR:
        return (
            "You're too far from the camera — move a bit closer for accurate tracking."
        )

    if abs(mid_hip.x - 0.5) > CENTER_X_TOLERANCE:
        side = "left" if mid_hip.x < 0.5 else "right"
        return f"Move to the center of frame — you're too far to the {side}."

    return None


class LungeAnalyzer:
    """Stateful lunge rep counter + front/back leg detector + form checker."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        # Rep state machine
        self.stage = "standing"  # "standing" (rest) or "down" (lunging)
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.partial_rep_count = 0
        self.left_reps = 0
        self.right_reps = 0

        self.smoothed_depth: Optional[float] = None
        self.last_depth: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None
        self.rep_start_time: Optional[float] = None
        self._depth_acc = 0.0
        self.depth_smooth_alpha = 0.5

        self.session_start_time: Optional[float] = None

        # "Half rep" partial-rep detection
        self._attempt_peak_depth: Optional[float] = None
        self._attempt_flagged = False

        # Personal posture baseline, captured at rest (standing).
        self._calib_samples: list[float] = []
        self.calibrated = False
        self._baseline_torso_lean = 0.0

        self._current_rep_issues: set[str] = set()

        # Which leg is front for the rep currently in progress.
        self.active_leg: Optional[str] = None

        # Per-rep peak/extremum trackers, reset when a rep starts.
        self._rep_min_front_knee_angle = 180.0
        self._rep_min_back_knee_angle = 180.0
        self._rep_max_knee_past_toe = 0.0
        self._rep_max_knee_tracking_dev = 0.0

        self.form_scores: deque = deque(maxlen=SCORE_HISTORY)

    # ---------------------------------------------------------------
    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 3.5:
            return "too_slow"
        if duration >= 2.2:
            return "slow"
        if duration >= 1.0:
            return "good"
        if duration >= 0.55:
            return "fast"
        return "too_fast"

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _finish_calibration(self):
        n = len(self._calib_samples)
        self._baseline_torso_lean = sum(self._calib_samples) / n
        self.calibrated = True

    def _reset_rep_trackers(self, front_knee_angle, back_knee_angle):
        self._rep_min_front_knee_angle = (
            front_knee_angle if front_knee_angle is not None else 180.0
        )
        self._rep_min_back_knee_angle = (
            back_knee_angle if back_knee_angle is not None else 180.0
        )
        self._rep_max_knee_past_toe = 0.0
        self._rep_max_knee_tracking_dev = 0.0

    @staticmethod
    def _avg(d: deque) -> Optional[float]:
        return round(sum(d) / len(d), 1) if d else None

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "depth": None,
            "smoothed_depth": None,
            "front_knee_angle": None,
            "back_knee_angle": None,
            "active_leg": self.active_leg,
            "depth_velocity": None,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "partial_rep_count": self.partial_rep_count,
            "left_reps": self.left_reps,
            "right_reps": self.right_reps,
            "leg_balance_ok": True,
            "leg_balance_message": None,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_duration": None,
            "rep_avg_speed": None,
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
        l_toe, r_toe = landmarks[LEFT_FOOT_INDEX], landmarks[RIGHT_FOOT_INDEX]

        left_leg_ok = _visible((l_hip, l_knee, l_ankle))
        right_leg_ok = _visible((r_hip, r_knee, r_ankle))
        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
        legs_visible = left_leg_ok and right_leg_ok

        if not legs_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see both legs clearly — step back so your full body, "
                "both legs, is in frame. A lunge can't be tracked with only "
                "one leg visible."
            )
            return response

        if not torso_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your torso — make sure your shoulders and hips are both in frame."
            )
            return response

        response["pose_detected"] = True

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)

        # ---- camera framing (every frame) ----
        framing_message = _framing_feedback(
            l_shoulder, r_shoulder, l_hip, r_hip, legs_visible
        )
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        # ---- knee angles (both legs, always) ----
        left_knee_angle = _angle_deg(l_hip, l_knee, l_ankle)
        right_knee_angle = _angle_deg(r_hip, r_knee, r_ankle)

        # ---- front/back leg detection — see module docstring ----
        knee_height_diff = abs(l_knee.y - r_knee.y) / torso_length
        if knee_height_diff >= KNEE_HEIGHT_DIFF_NEUTRAL:
            frame_front_leg = "left" if l_knee.y < r_knee.y else "right"
        else:
            frame_front_leg = None  # legs roughly even — standing

        # ---- combined "depth" score (drives the rep state machine) ----
        height_frac = _clip(knee_height_diff / KNEE_HEIGHT_DIFF_TARGET)
        if frame_front_leg == "left":
            raw_front_angle = left_knee_angle
        elif frame_front_leg == "right":
            raw_front_angle = right_knee_angle
        else:
            raw_front_angle = min(left_knee_angle, right_knee_angle)
        knee_frac = _clip(
            (FRONT_KNEE_DOWN_ANGLE - raw_front_angle)
            / (FRONT_KNEE_DOWN_ANGLE - FRONT_KNEE_UP_ANGLE)
        )
        raw_depth = 100.0 * ((height_frac + knee_frac) / 2.0)

        if self.smoothed_depth is None:
            self.smoothed_depth = raw_depth
        else:
            self.smoothed_depth = (
                self.depth_smooth_alpha * raw_depth
                + (1 - self.depth_smooth_alpha) * self.smoothed_depth
            )

        depth_velocity = None
        if self.last_depth is not None and self.last_timestamp_s is not None:
            dt = t - self.last_timestamp_s
            if dt > 0:
                depth_velocity = (self.smoothed_depth - self.last_depth) / dt

        # ---- torso lean + calibration ----
        vertical_ref = _Point(mid_hip.x, mid_hip.y - 1.0)
        torso_lean = _angle_deg(vertical_ref, mid_hip, mid_shoulder)

        if self.stage == "standing" and not self.calibrated:
            self._calib_samples.append(torso_lean)
            if len(self._calib_samples) >= CALIBRATION_FRAMES:
                self._finish_calibration()

        issues: list[str] = []
        messages: list[str] = []
        if self.calibrated and (
            torso_lean - self._baseline_torso_lean > TORSO_LEAN_DELTA_DEG
            or torso_lean > TORSO_LEAN_HARD_MAX_DEG
        ):
            issues.append("poor_posture")
            messages.append("Stand taller — keep your torso upright through the lunge.")

        # ---- lock in active_leg the moment we enter "down" ----
        rep_completed = False
        if (
            self.stage == "standing"
            and self.smoothed_depth > DEPTH_OPEN_THRESH
            and frame_front_leg is not None
        ):
            self.stage = "down"
            self.active_leg = frame_front_leg
            self.rep_start_time = t
            self._depth_acc = 0.0
            self._current_rep_issues = set()
            front_a = left_knee_angle if frame_front_leg == "left" else right_knee_angle
            back_a = right_knee_angle if frame_front_leg == "left" else left_knee_angle
            self._reset_rep_trackers(front_a, back_a)

        # ---- per-rep extremum tracking (only while locked into a rep) ----
        front_knee_angle = back_knee_angle = None
        if self.stage == "down" and self.active_leg is not None:
            if self.active_leg == "left":
                front_knee_angle, back_knee_angle = left_knee_angle, right_knee_angle
                front_knee, front_hip, front_ankle = l_knee, l_hip, l_ankle
                front_toe = l_toe if _visible((l_toe,)) else l_ankle
            else:
                front_knee_angle, back_knee_angle = right_knee_angle, left_knee_angle
                front_knee, front_hip, front_ankle = r_knee, r_hip, r_ankle
                front_toe = r_toe if _visible((r_toe,)) else r_ankle

            self._rep_min_front_knee_angle = min(
                self._rep_min_front_knee_angle, front_knee_angle
            )
            self._rep_min_back_knee_angle = min(
                self._rep_min_back_knee_angle, back_knee_angle
            )

            # Knee-past-toes: how far the knee has moved beyond the toe, in
            # the direction the foot stepped (hip -> ankle direction).
            step_dir = 1.0 if (front_ankle.x - front_hip.x) >= 0 else -1.0
            overshoot = step_dir * (front_knee.x - front_toe.x) / torso_length
            self._rep_max_knee_past_toe = max(self._rep_max_knee_past_toe, overshoot)

            # Knee tracking: sideways drift off the hip->ankle ("thigh") line.
            deviation = abs(
                _line_deviation(front_hip, front_ankle, front_knee, torso_length)
            )
            self._rep_max_knee_tracking_dev = max(
                self._rep_max_knee_tracking_dev, deviation
            )

        # ---- "half rep" partial-rep coaching (pre-transition, while standing) ----
        partial_feedback = None
        if self.stage == "standing":
            if (
                self._attempt_peak_depth is None
                or self.smoothed_depth > self._attempt_peak_depth
            ):
                self._attempt_peak_depth = self.smoothed_depth
            elif (
                not self._attempt_flagged
                and self._attempt_peak_depth is not None
                and self._attempt_peak_depth - self.smoothed_depth > PARTIAL_REP_BOUNCE
                and self._attempt_peak_depth < DEPTH_OPEN_THRESH - PARTIAL_REP_MARGIN
                and self._attempt_peak_depth - DEPTH_CLOSED_THRESH
                > PARTIAL_REP_MIN_RISE
            ):
                self._attempt_flagged = True
                self.partial_rep_count += 1
                partial_feedback = (
                    f"Half rep — you only reached {self._attempt_peak_depth:.0f}/100 depth, "
                    "step further and lunge all the way down."
                )

            if self.smoothed_depth < DEPTH_CLOSED_THRESH - 3:
                self._attempt_peak_depth = None
                self._attempt_flagged = False

        # ---- depth arc-length accumulator (sanity check vs tiny wobbles) ----
        if self.stage == "standing" and self.smoothed_depth > DEPTH_CLOSED_THRESH:
            self._depth_acc = 0.0
        if self.last_depth is not None:
            self._depth_acc += abs(self.smoothed_depth - self.last_depth)

        # ---- rep completion: back to standing ----
        if (
            self.stage == "down"
            and self.smoothed_depth < DEPTH_CLOSED_THRESH
            and knee_height_diff < KNEE_HEIGHT_DIFF_NEUTRAL * 2.5
        ):
            self.stage = "standing"
            rep_completed = True

        rep_duration = rep_avg_speed = rep_class = rep_form_quality = None
        form_score = None
        feedback = framing_message or partial_feedback

        if rep_completed:
            completed_leg = self.active_leg
            rep_duration = (
                (t - self.rep_start_time) if self.rep_start_time is not None else None
            )
            if rep_duration and rep_duration > 0:
                rep_avg_speed = self._depth_acc / rep_duration

            valid = (
                rep_duration is not None
                and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                and self._depth_acc >= MIN_DEPTH_DELTA
                and completed_leg is not None
            )

            if valid:
                self.rep_count += 1
                if completed_leg == "left":
                    self.left_reps += 1
                else:
                    self.right_reps += 1
                rep_class = self._classify_tempo(rep_duration)

                if (
                    self._rep_min_front_knee_angle
                    > FRONT_KNEE_UP_ANGLE + PARTIAL_REP_MARGIN
                ):
                    self._current_rep_issues.add("shallow_lunge")
                if self._rep_max_knee_past_toe > KNEE_PAST_TOE_RATIO:
                    self._current_rep_issues.add("knee_past_toes")
                if self._rep_max_knee_tracking_dev > KNEE_TRACKING_MAX_DEVIATION:
                    self._current_rep_issues.add("knee_tracking")
                if self._rep_min_back_knee_angle > BACK_KNEE_BEND_MAX_ANGLE:
                    self._current_rep_issues.add("back_knee_not_lowered")
                self._current_rep_issues.update(issues)

                form_score = 100
                for issue in self._current_rep_issues:
                    form_score -= MISTAKE_PENALTY.get(issue, 10)
                form_score = max(0, form_score)
                self.form_scores.append(form_score)

                if self._current_rep_issues:
                    rep_form_quality = "needs_improvement"
                    self.flawed_reps += 1
                    issue_text = ", ".join(
                        i.replace("_", " ") for i in sorted(self._current_rep_issues)
                    )
                    feedback = (
                        f"Rep {self.rep_count} ({completed_leg} leg) counted, "
                        f"but watch your form ({issue_text})."
                    )
                else:
                    rep_form_quality = "good"
                    self.good_reps += 1
                    if rep_class in ("good", "fast"):
                        feedback = f"Clean {completed_leg}-leg rep — {rep_class} tempo ({rep_duration:.2f}s)."
                    elif rep_class in ("slow", "too_slow"):
                        feedback = (
                            f"Good depth, nice and controlled ({rep_duration:.2f}s)."
                        )
                    else:
                        feedback = (
                            f"Clean rep, but control the tempo ({rep_duration:.2f}s)."
                        )
            else:
                rep_completed = False
                if rep_duration is not None and rep_duration < MIN_REP_DURATION:
                    feedback = (
                        "Too fast — that one wasn't counted, control the movement."
                    )
                elif rep_duration is not None and rep_duration > MAX_REP_DURATION:
                    feedback = "That rep took too long — not counted. Keep moving."
                else:
                    feedback = "Not enough range of motion — not counted."

            self.rep_start_time = None
            self._depth_acc = 0.0
            self._current_rep_issues = set()
            self.active_leg = None

        self.last_depth = self.smoothed_depth
        self.last_timestamp_s = t

        # ---- leg balance nudge (live, session-level — never blocks counting) ----
        leg_diff = self.left_reps - self.right_reps
        leg_balance_ok = abs(leg_diff) <= LEG_BALANCE_WARN_DIFF
        leg_balance_message = None
        if not leg_balance_ok:
            lagging = "right" if leg_diff > 0 else "left"
            leg_balance_message = (
                f"You're favoring one side — do a few more on your {lagging} leg."
            )

        if feedback is None and messages:
            feedback = messages[0]
        if feedback is None and not leg_balance_ok:
            feedback = leg_balance_message
        if feedback is None and not self.calibrated:
            feedback = (
                "Stand tall facing the camera, feet together, and hold still "
                "for a second — calibrating your posture."
            )
        if feedback is None:
            feedback = "Good position — keep going."

        response.update(
            {
                "pose_detected": True,
                "depth": round(raw_depth, 1),
                "smoothed_depth": round(self.smoothed_depth, 1),
                "front_knee_angle": (
                    round(front_knee_angle, 1) if front_knee_angle is not None else None
                ),
                "back_knee_angle": (
                    round(back_knee_angle, 1) if back_knee_angle is not None else None
                ),
                "left_knee_angle": round(left_knee_angle, 1),
                "right_knee_angle": round(right_knee_angle, 1),
                "active_leg": self.active_leg,
                "depth_velocity": (
                    round(depth_velocity, 1) if depth_velocity is not None else None
                ),
                "stage": self.stage,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "partial_rep_count": self.partial_rep_count,
                "left_reps": self.left_reps,
                "right_reps": self.right_reps,
                "leg_balance_ok": leg_balance_ok,
                "leg_balance_message": leg_balance_message,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_duration": (
                    round(rep_duration, 2) if rep_duration is not None else None
                ),
                "rep_avg_speed": (
                    round(rep_avg_speed, 1) if rep_avg_speed is not None else None
                ),
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "calibrated": self.calibrated,
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
        return response


class LungeSession:
    """Full lunge session: one shared pose model + one analyzer.

    `target_reps` / `target_sets` / `set_number` are the coach-assigned plan
    for this user, supplied by the caller (the websocket route, from query
    params) — same convention as squat/push-up. The frontend does not decide
    on its own whether a set/exercise is done; `session_complete` (this
    set's reps are done) and `exercise_complete` (the whole assigned plan —
    all sets — is done) are computed here.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = LungeAnalyzer(target_reps)
        self.target_sets = max(1, target_sets)
        self.set_number = max(1, min(set_number, self.target_sets))

    def detect(self, frame, timestamp_ms: int) -> dict[str, Any]:
        landmarks = self.engine.detect(frame, timestamp_ms)
        result = self.analyzer.update(landmarks, timestamp_ms)
        result["landmarks"] = (
            PoseEngine.landmarks_to_json(landmarks) if landmarks else []
        )

        # Backend-validated plan progress — frontend just reads these, it
        # never computes them itself.
        result["set_number"] = self.set_number
        result["target_sets"] = self.target_sets
        result["exercise_complete"] = bool(
            result["session_complete"] and self.set_number >= self.target_sets
        )
        return result

    def close(self):
        self.engine.close()
