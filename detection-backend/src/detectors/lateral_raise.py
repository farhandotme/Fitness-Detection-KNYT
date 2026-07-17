import math
from collections import deque
from typing import Any, Optional

from src.engines.poseEngine import (
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

MIN_LANDMARK_VISIBILITY = 0.4
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)

# MediaPipe's confidence on a wrist/elbow can dip for a frame or two right at full extension
# (self-occlusion, motion blur). Holding the last confidently-tracked position for a short
# window stops a single noisy frame from causing a dropped frame of processing.
MAX_LANDMARK_HOLD_FRAMES = 4
STABILIZED_LANDMARK_INDICES = (
    LEFT_SHOULDER,
    RIGHT_SHOULDER,
    LEFT_ELBOW,
    RIGHT_ELBOW,
    LEFT_WRIST,
    RIGHT_WRIST,
    LEFT_HIP,
    RIGHT_HIP,
    NOSE,
)

# Shoulder-height calibration
REST_ANGLE = 35.0
RAISE_ANGLE = 85.0

# Rep counting thresholds
LIFT_RAISED_THRESH = 72.0
LIFT_GROUNDED_THRESH = 24.0
MIN_ANGLE_DELTA = 18.0
MIN_REP_DURATION = 0.25
MAX_REP_DURATION = 6.0
CALIBRATION_FRAMES: int = 15

# Partial rep
PARTIAL_REP_MARGIN = 12.0
PARTIAL_REP_MIN_RISE = 16.0
PARTIAL_REP_BOUNCE = 7.0

# Form checks
TORSO_LEAN_DELTA_DEG = 14.0
SHRUG_DELTA_RATIO = 0.10
ELBOW_STRAIGHT_MIN_DEG = 150.0
ASYMMETRY_DEG = 18.0

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

FRAME_EDGE_MARGIN = 0.03
TORSO_SPAN_TOO_CLOSE = 0.60
TORSO_SPAN_TOO_FAR = 0.10
CENTER_X_TOLERANCE = 0.28


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 3


class _Point:
    __slots__ = ("x", "y", "visibility")

    def __init__(self, x: float, y: float, visibility: Optional[float] = None):
        self.x = x
        self.y = y
        self.visibility = visibility


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


def _lift_score(angle: float) -> float:
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
            return (
                "You're partly out of frame — center yourself with space on both sides."
            )

    torso_span = abs(mid_hip.y - mid_shoulder.y)
    if torso_span > TORSO_SPAN_TOO_CLOSE:
        return "You're too close to the camera — step back so your arms fit fully out to the sides in frame."
    if torso_span < TORSO_SPAN_TOO_FAR:
        return (
            "You're too far from the camera — move a bit closer for accurate tracking."
        )

    if abs(mid_hip.x - 0.5) > CENTER_X_TOLERANCE:
        side = "left" if mid_hip.x < 0.5 else "right"
        return f"Move to the center of frame — you're too far to the {side}."

    return None


class LateralRaiseAnalyzer:
    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps
        self.stage = "down"
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.partial_rep_count = 0

        self.smoothed_lift: Optional[float] = None
        self.last_smoothed_lift: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None
        self.lift_smooth_alpha = 0.35
        self._landmark_cache: dict[int, tuple] = {}

        self.rep_start_time: Optional[float] = None
        self._lift_acc = 0.0
        self.session_start_time: Optional[float] = None

        self._attempt_peak_lift: Optional[float] = None
        self._attempt_flagged = False

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

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _stabilize(self, landmarks, indices) -> dict:
        """
        Holds onto the last confidently-tracked position for a landmark for a few frames if its
        visibility briefly drops (common at full extension, where MediaPipe's confidence on a
        wrist or elbow can dip for a frame or two). This stops a single noisy frame from making
        us skip processing that frame entirely, which was causing inconsistent rep counting.
        """
        out = {}
        for i in indices:
            lm = landmarks[i]
            vis = getattr(lm, "visibility", None)
            if vis is not None and vis < MIN_LANDMARK_VISIBILITY:
                cached = self._landmark_cache.get(i)
                if cached is not None and cached[1] < MAX_LANDMARK_HOLD_FRAMES:
                    point, age = cached
                    out[i] = point
                    self._landmark_cache[i] = (point, age + 1)
                    continue
                out[i] = lm
            else:
                point = _Point(lm.x, lm.y, vis)
                out[i] = point
                self._landmark_cache[i] = (point, 0)
        return out

    def _finish_calibration(self):
        n = len(self._calib_lean_samples)
        if n:
            self._baseline_torso_lean = sum(self._calib_lean_samples) / n
        m = len(self._calib_shrug_samples)
        if m:
            self._baseline_shrug_gap = sum(self._calib_shrug_samples) / m
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

        stable = self._stabilize(landmarks, STABILIZED_LANDMARK_INDICES)
        l_shoulder, r_shoulder = stable[LEFT_SHOULDER], stable[RIGHT_SHOULDER]
        l_elbow, r_elbow = stable[LEFT_ELBOW], stable[RIGHT_ELBOW]
        l_wrist, r_wrist = stable[LEFT_WRIST], stable[RIGHT_WRIST]
        l_hip, r_hip = stable[LEFT_HIP], stable[RIGHT_HIP]
        nose = stable[NOSE]

        left_arm_ok = _visible((l_shoulder, l_elbow, l_wrist, l_hip))
        right_arm_ok = _visible((r_shoulder, r_elbow, r_wrist, r_hip))
        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))

        if not left_arm_ok and not right_arm_ok:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your arms clearly — adjust the camera so your shoulders, elbows, and wrists are all in frame."
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

        framing_message = _framing_feedback(l_shoulder, r_shoulder, l_hip, r_hip)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        left_angle = _angle_deg(l_hip, l_shoulder, l_elbow) if left_arm_ok else None
        right_angle = _angle_deg(r_hip, r_shoulder, r_elbow) if right_arm_ok else None
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

        elbow_angles = []
        if left_arm_ok:
            elbow_angles.append(_angle_deg(l_shoulder, l_elbow, l_wrist))
        if right_arm_ok:
            elbow_angles.append(_angle_deg(r_shoulder, r_elbow, r_wrist))
        min_elbow_angle = min(elbow_angles) if elbow_angles else 180.0

        vertical_ref = _Point(mid_hip.x, mid_hip.y - 1.0)
        torso_lean = _angle_deg(vertical_ref, mid_hip, mid_shoulder)

        nose_ok = _visible((nose,))
        shrug_gap = (mid_shoulder.y - nose.y) / torso_length if nose_ok else None

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
            (self._baseline_shrug_gap - shrug_gap)
            if self.calibrated and shrug_gap is not None
            else 0.0
        )

        rep_completed = False

        # Everything below drives off smoothed_lift, not raw_lift. raw_lift is a single noisy
        # per-frame reading from MediaPipe — using it directly for threshold crossings meant a
        # single glitchy frame could make the exact same rep register one time and not the next.
        # smoothed_lift (the EMA calculated above) filters that noise out before it reaches the
        # state machine, which is what actually makes counting consistent and precise.

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
                and self._attempt_peak_lift > PARTIAL_REP_MIN_RISE
            ):
                self._attempt_flagged = True
                self.partial_rep_count += 1
                response["feedback"] = (
                    f"Half rep — only got to {self._attempt_peak_lift:.0f}/100 of shoulder height, raise all the way up."
                )

            if self.smoothed_lift <= LIFT_GROUNDED_THRESH:
                self._attempt_peak_lift = None
                self._attempt_flagged = False

            # Just check the threshold — the `if self.stage == "down":` branch we're already
            # inside only runs while we're in "down", so this naturally only fires once per
            # raise (as soon as we transition to "up", this whole branch stops running). The
            # previous version also required last_smoothed_lift to have been specifically below
            # (LIFT_RAISED_THRESH - 8) on the prior frame — but if a frame got dropped, or the
            # raise happened fast enough that the value jumped straight past that narrow window
            # in one step, that condition could never be satisfied again while the arm stayed
            # up, permanently stranding the stage on "down" no matter how clearly raised the arm
            # was. The 72/24 gap between the raise and grounded thresholds already gives plenty
            # of hysteresis against flicker, so this extra check wasn't protecting anything.
            if self.smoothed_lift >= LIFT_RAISED_THRESH:
                self.stage = "up"
                self.rep_start_time = t
                self._lift_acc = 0.0
                self._current_rep_issues = set()
                self._rep_max_torso_lean_delta = lean_delta
                self._rep_max_shrug_delta = shrug_delta
                self._rep_min_elbow_angle = min_elbow_angle
                self._rep_max_asymmetry = arm_gap
        else:
            self._rep_max_torso_lean_delta = max(
                self._rep_max_torso_lean_delta, lean_delta
            )
            self._rep_max_shrug_delta = max(self._rep_max_shrug_delta, shrug_delta)
            self._rep_min_elbow_angle = min(self._rep_min_elbow_angle, min_elbow_angle)
            self._rep_max_asymmetry = max(self._rep_max_asymmetry, arm_gap)

            if self.last_smoothed_lift is not None:
                self._lift_acc += abs(self.smoothed_lift - self.last_smoothed_lift)

            # Same fix as above, mirrored for the way back down: just check the threshold.
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
                    feedback = (
                        "Too fast — that one wasn't counted, control the movement."
                    )
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

        self.last_smoothed_lift = self.smoothed_lift
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
            feedback = "Stand tall with your arms relaxed at your sides for a second — calibrating your posture."
        if feedback is None:
            feedback = "Good position — raise both arms out to shoulder height."

        response.update(
            {
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
