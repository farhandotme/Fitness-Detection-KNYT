
import math
from collections import deque
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_SHOULDER,
    LEFT_WRIST,
    PoseEngine,
    RIGHT_ANKLE,
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

# Arm abduction angle (hip-shoulder-wrist), degrees.
ARM_ANGLE_CLOSED = 25.0   # arms relaxed down at the sides
ARM_ANGLE_OPEN = 150.0    # arms raised overhead

# Elbow angle (shoulder-elbow-wrist), degrees. Should stay near-straight.
ELBOW_STRAIGHT_MIN = 150.0

# Ankle-to-ankle distance / shoulder-width ratio.
LEG_SPREAD_RATIO_CLOSED = 0.55  # feet together
LEG_SPREAD_RATIO_OPEN = 1.6     # feet spread wide

# Combined 0-100 "openness" hysteresis band driving the rep state machine.
OPENNESS_CLOSED_THRESH = 22.0
OPENNESS_OPEN_THRESH = 72.0
MIN_OPENNESS_DELTA = 35.0  # total travel required for a rep to "count"
MIN_REP_DURATION = 0.28    # seconds — faster than this = noise/bounce
MAX_REP_DURATION = 6.0     # seconds — slower than this = paused, not a rep

CALIBRATION_FRAMES = 15

# Posture: torso should stay close to upright throughout (less forgiving
# than a squat, which expects forward lean).
TORSO_LEAN_DELTA_DEG = 18.0
TORSO_LEAN_HARD_MAX_DEG = 40.0

# Left/right synchronization tolerances.
ARM_SYNC_MAX_DIFF_DEG = 55.0
LEG_SYNC_MAX_DIFF_RATIO = 0.35  # normalized by shoulder width

# Stability: allowed sideways hip drift during a rep, normalized by
# shoulder width. Vertical bounce from the jump itself is NOT penalized.
STABILITY_MAX_DRIFT_RATIO = 0.55

# "Half rep" partial-rep heuristic (mirrors squat's PARTIAL_REP_* family).
PARTIAL_REP_MARGIN = 12.0
PARTIAL_REP_MIN_RISE = 20.0
PARTIAL_REP_BOUNCE = 8.0

# Per-mistake form_score penalty.
MISTAKE_PENALTY = {
    "arms_not_fully_raised": 25,
    "legs_not_spread_enough": 25,
    "bent_elbows": 20,
    "poor_posture": 15,
    "asymmetrical_movement": 15,
}

SCORE_HISTORY = 10  # reps kept for rolling-average scores
TEMPO_HISTORY = 5   # reps kept for reps-per-minute estimate
FPS_WINDOW = 30      # frames kept for fps estimate

# -------------------------------------------------------------------------
# Camera framing / stance-position thresholds
# -------------------------------------------------------------------------
FRAME_EDGE_MARGIN = 0.03
TORSO_SPAN_TOO_CLOSE = 0.45
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


def _framing_feedback(
    l_shoulder, r_shoulder, l_hip, r_hip, l_wrist, r_wrist, legs_visible: bool
) -> Optional[str]:
    """Coaches the user into a good spot for the camera to track a jumping
    jack — checked every frame, independent of exercise form.

    Checks, in order of how badly they break tracking:
      1. Part of the body (including a raised wrist) clipped at a frame edge.
      2. Legs/ankles not visible (can't score leg spread without them).
      3. Too close / too far from the camera.
      4. Standing off to one side instead of centered.
    """
    mid_shoulder = _midpoint(l_shoulder, r_shoulder)
    mid_hip = _midpoint(l_hip, r_hip)

    edge_check_points = [l_shoulder, r_shoulder, l_hip, r_hip]
    for w in (l_wrist, r_wrist):
        if w is not None and getattr(w, "visibility", 1.0) is not None and (
            w.visibility is None or w.visibility > MIN_LANDMARK_VISIBILITY
        ):
            edge_check_points.append(w)

    for p in edge_check_points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — step back so your raised arms "
                "and legs both stay in view."
            )

    if not legs_visible:
        return "Step back so your legs and ankles are visible — I need your full body in frame for jumping jacks."

    torso_span = abs(mid_hip.y - mid_shoulder.y)
    if torso_span > TORSO_SPAN_TOO_CLOSE:
        return "You're too close to the camera — step back until your whole body fits in frame."
    if torso_span < TORSO_SPAN_TOO_FAR:
        return "You're too far from the camera — move a bit closer for accurate tracking."

    if abs(mid_hip.x - 0.5) > CENTER_X_TOLERANCE:
        side = "left" if mid_hip.x < 0.5 else "right"
        return f"Move to the center of frame — you're too far to the {side}."

    return None


def _combine_openness(arm_frac: Optional[float], leg_frac: Optional[float]) -> Optional[float]:
    """Weighted average of the two 0-1(+) extension fractions, each clamped
    to [0, 1] first so an overreaching limb can't mask a missing one.
    Falls back to whichever single signal is available; returns None only
    if neither is."""
    components = []
    if arm_frac is not None:
        components.append((_clip(arm_frac), 0.5))
    if leg_frac is not None:
        components.append((_clip(leg_frac), 0.5))
    if not components:
        return None
    total_w = sum(w for _, w in components)
    return 100.0 * sum(v * w for v, w in components) / total_w


class JumpingJackAnalyzer:
    """Stateful, bilateral jumping-jack rep counter + form/score analyzer."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        # Rep state machine
        self.stage = "closed"  # "closed" = resting, "open" = arms/legs extended
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.partial_rep_count = 0

        self.smoothed_openness: Optional[float] = None
        self.last_openness: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None
        self.rep_start_time: Optional[float] = None
        self._openness_acc = 0.0
        self.openness_smooth_alpha = 0.5

        self.session_start_time: Optional[float] = None

        # "Half rep" partial-rep detection
        self._attempt_peak_openness: Optional[float] = None
        self._attempt_flagged = False

        # Personal posture baseline, captured at rest.
        self._calib_samples: list[float] = []
        self.calibrated = False
        self._baseline_torso_lean = 0.0

        self._current_rep_issues: set[str] = set()

        # Per-rep peak/extremum trackers, reset when a rep starts.
        self._rep_peak_arm_frac = 0.0
        self._rep_peak_leg_frac = 0.0
        self._rep_min_elbow_angle = 180.0
        self._rep_max_arm_diff = 0.0
        self._rep_max_leg_diff = 0.0
        self._rep_hip_x_start: Optional[float] = None
        self._rep_hip_x_max_dev = 0.0

        # Rolling score/tempo history.
        self.form_scores: deque = deque(maxlen=SCORE_HISTORY)
        self.rom_scores: deque = deque(maxlen=SCORE_HISTORY)
        self.stability_scores: deque = deque(maxlen=SCORE_HISTORY)
        self.sync_scores: deque = deque(maxlen=SCORE_HISTORY)
        self.recent_rep_durations: deque = deque(maxlen=TEMPO_HISTORY)

        self._frame_times: deque = deque(maxlen=FPS_WINDOW)

    # ---------------------------------------------------------------
    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 2.2:
            return "too_slow"
        if duration >= 1.4:
            return "slow"
        if duration >= 0.5:
            return "good"
        if duration >= 0.32:
            return "fast"
        return "too_fast"

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _finish_calibration(self):
        n = len(self._calib_samples)
        self._baseline_torso_lean = sum(self._calib_samples) / n
        self.calibrated = True

    def _reset_rep_trackers(self, arm_frac, leg_frac, elbow_angle, hip_x):
        self._rep_peak_arm_frac = arm_frac if arm_frac is not None else 0.0
        self._rep_peak_leg_frac = leg_frac if leg_frac is not None else 0.0
        self._rep_min_elbow_angle = elbow_angle if elbow_angle is not None else 180.0
        self._rep_max_arm_diff = 0.0
        self._rep_max_leg_diff = 0.0
        self._rep_hip_x_start = hip_x
        self._rep_hip_x_max_dev = 0.0

    @staticmethod
    def _avg(d: deque) -> Optional[float]:
        return round(sum(d) / len(d), 1) if d else None

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        self._frame_times.append(t)
        fps = None
        if len(self._frame_times) >= 2:
            span = self._frame_times[-1] - self._frame_times[0]
            if span > 0:
                fps = round((len(self._frame_times) - 1) / span, 1)

        response: dict[str, Any] = {
            "pose_detected": False,
            "openness": None,
            "smoothed_openness": None,
            "arm_angle_left": None,
            "arm_angle_right": None,
            "elbow_angle_left": None,
            "elbow_angle_right": None,
            "leg_spread_ratio": None,
            "openness_velocity": None,
            "stage": self.stage,
            "phase": "start",
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "partial_rep_count": self.partial_rep_count,
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
            "rom_score": None,
            "avg_rom_score": self._avg(self.rom_scores),
            "stability_score": None,
            "avg_stability_score": self._avg(self.stability_scores),
            "sync_score": None,
            "avg_sync_score": self._avg(self.sync_scores),
            "speed_analysis": {
                "duration": None,
                "classification": None,
                "reps_per_minute": (
                    round(60.0 / (sum(self.recent_rep_durations) / len(self.recent_rep_durations)), 1)
                    if self.recent_rep_durations
                    else None
                ),
            },
            "fps": fps,
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
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        left_arm_ok = _visible((l_hip, l_shoulder, l_elbow, l_wrist))
        right_arm_ok = _visible((r_hip, r_shoulder, r_elbow, r_wrist))
        legs_visible = _visible((l_hip, r_hip, l_ankle, r_ankle))

        if not left_arm_ok and not right_arm_ok and not legs_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["smoothed_openness"] = self.smoothed_openness
            response["feedback"] = (
                "Can't see your arms or legs clearly — step back for a full-body view."
            )
            return response

        shoulder_width = max(_dist(l_shoulder, r_shoulder), 1e-6)

        # ---- arm abduction angle (hip -> shoulder -> wrist) ----
        left_arm_angle = _angle_deg(l_hip, l_shoulder, l_wrist) if left_arm_ok else None
        right_arm_angle = _angle_deg(r_hip, r_shoulder, r_wrist) if right_arm_ok else None
        arm_angles = [a for a in (left_arm_angle, right_arm_angle) if a is not None]
        arm_frac = None
        if arm_angles:
            avg_arm_angle = sum(arm_angles) / len(arm_angles)
            arm_frac = (avg_arm_angle - ARM_ANGLE_CLOSED) / (ARM_ANGLE_OPEN - ARM_ANGLE_CLOSED)

        # ---- elbow straightness ----
        left_elbow_angle = _angle_deg(l_shoulder, l_elbow, l_wrist) if left_arm_ok else None
        right_elbow_angle = _angle_deg(r_shoulder, r_elbow, r_wrist) if right_arm_ok else None
        elbow_angles = [a for a in (left_elbow_angle, right_elbow_angle) if a is not None]
        avg_elbow_angle = sum(elbow_angles) / len(elbow_angles) if elbow_angles else None

        # ---- leg spread ratio ----
        leg_frac = None
        leg_spread_ratio = None
        if legs_visible:
            leg_spread_ratio = _dist(l_ankle, r_ankle) / shoulder_width
            leg_frac = (leg_spread_ratio - LEG_SPREAD_RATIO_CLOSED) / (
                LEG_SPREAD_RATIO_OPEN - LEG_SPREAD_RATIO_CLOSED
            )

        # ---- torso lean (posture) ----
        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
        torso_lean = None
        mid_hip = None
        if torso_visible:
            mid_shoulder = _midpoint(l_shoulder, r_shoulder)
            mid_hip = _midpoint(l_hip, r_hip)
            vertical_ref = _Point(mid_hip.x, mid_hip.y - 1.0)
            torso_lean = _angle_deg(vertical_ref, mid_hip, mid_shoulder)

        # ---- combined openness (drives the rep state machine) ----
        raw_openness = _combine_openness(arm_frac, leg_frac)
        if raw_openness is None:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["smoothed_openness"] = self.smoothed_openness
            response["feedback"] = "Can't get a clear reading — step back for a full-body view."
            return response

        if self.smoothed_openness is None:
            self.smoothed_openness = raw_openness
        else:
            self.smoothed_openness = (
                self.openness_smooth_alpha * raw_openness
                + (1 - self.openness_smooth_alpha) * self.smoothed_openness
            )

        openness_velocity = None
        if self.last_openness is not None and self.last_timestamp_s is not None:
            dt = t - self.last_timestamp_s
            if dt > 0:
                openness_velocity = (self.smoothed_openness - self.last_openness) / dt

        # ---- camera framing check (every frame) ----
        framing_message = None
        if torso_visible:
            framing_message = _framing_feedback(
                l_shoulder, r_shoulder, l_hip, r_hip, l_wrist, r_wrist, legs_visible
            )

        # ---- calibration (torso-lean baseline, captured at rest) ----
        if self.stage == "closed" and not self.calibrated and torso_lean is not None:
            self._calib_samples.append(torso_lean)
            if len(self._calib_samples) >= CALIBRATION_FRAMES:
                self._finish_calibration()

        # ---- live posture / sync issues ----
        issues: list[str] = []
        messages: list[str] = []
        if self.calibrated and torso_lean is not None:
            if (
                torso_lean - self._baseline_torso_lean > TORSO_LEAN_DELTA_DEG
                or torso_lean > TORSO_LEAN_HARD_MAX_DEG
            ):
                issues.append("poor_posture")
                messages.append("Keep your torso upright — you're leaning too much.")

        if self.stage == "open" and avg_elbow_angle is not None and avg_elbow_angle < ELBOW_STRAIGHT_MIN:
            issues.append("bent_elbows")
            messages.append("Keep your arms straight as you raise them.")

        arm_diff = (
            abs(left_arm_angle - right_arm_angle)
            if left_arm_angle is not None and right_arm_angle is not None
            else None
        )
        leg_diff_ratio = None
        if legs_visible and mid_hip is not None:
            l_dev = abs(l_ankle.x - mid_hip.x) / shoulder_width
            r_dev = abs(r_ankle.x - mid_hip.x) / shoulder_width
            leg_diff_ratio = abs(l_dev - r_dev)

        if (arm_diff is not None and arm_diff > ARM_SYNC_MAX_DIFF_DEG) or (
            leg_diff_ratio is not None and leg_diff_ratio > LEG_SYNC_MAX_DIFF_RATIO
        ):
            issues.append("asymmetrical_movement")
            messages.append("Move both arms and legs together, evenly.")

        # ---- per-rep peak/extremum tracking (only while "open") ----
        if self.stage == "open":
            if arm_frac is not None:
                self._rep_peak_arm_frac = max(self._rep_peak_arm_frac, arm_frac)
            if leg_frac is not None:
                self._rep_peak_leg_frac = max(self._rep_peak_leg_frac, leg_frac)
            if avg_elbow_angle is not None:
                self._rep_min_elbow_angle = min(self._rep_min_elbow_angle, avg_elbow_angle)
            if arm_diff is not None:
                self._rep_max_arm_diff = max(self._rep_max_arm_diff, arm_diff)
            if leg_diff_ratio is not None:
                self._rep_max_leg_diff = max(self._rep_max_leg_diff, leg_diff_ratio)
            if mid_hip is not None:
                if self._rep_hip_x_start is None:
                    self._rep_hip_x_start = mid_hip.x
                else:
                    dev = abs(mid_hip.x - self._rep_hip_x_start) / shoulder_width
                    self._rep_hip_x_max_dev = max(self._rep_hip_x_max_dev, dev)
            self._current_rep_issues.update(issues)

        # ---- "half rep" partial-rep coaching (pre-transition, while closed) ----
        partial_feedback = None
        if self.stage == "closed":
            if self._attempt_peak_openness is None or self.smoothed_openness > self._attempt_peak_openness:
                self._attempt_peak_openness = self.smoothed_openness
            elif (
                not self._attempt_flagged
                and self._attempt_peak_openness is not None
                and self._attempt_peak_openness - self.smoothed_openness > PARTIAL_REP_BOUNCE
                and self._attempt_peak_openness < OPENNESS_OPEN_THRESH - PARTIAL_REP_MARGIN
                and self._attempt_peak_openness - OPENNESS_CLOSED_THRESH > PARTIAL_REP_MIN_RISE
            ):
                self._attempt_flagged = True
                self.partial_rep_count += 1
                partial_feedback = (
                    f"Half rep — you only reached {self._attempt_peak_openness:.0f}/100 extension, "
                    "go all the way: arms overhead, feet wide."
                )

            if self.smoothed_openness < OPENNESS_CLOSED_THRESH - 3:
                self._attempt_peak_openness = None
                self._attempt_flagged = False

        # ---- openness arc-length accumulator (sanity check vs tiny wobbles) ----
        if self.stage == "closed" and self.smoothed_openness > OPENNESS_CLOSED_THRESH:
            self._openness_acc = 0.0
        if self.last_openness is not None:
            self._openness_acc += abs(self.smoothed_openness - self.last_openness)

        # ---- rep state machine ----
        rep_completed = False
        if self.stage == "closed" and self.smoothed_openness > OPENNESS_OPEN_THRESH:
            self.stage = "open"
            self.rep_start_time = t
            self._openness_acc = 0.0
            self._current_rep_issues = set()
            self._reset_rep_trackers(
                arm_frac, leg_frac, avg_elbow_angle, mid_hip.x if mid_hip else None
            )
        elif self.stage == "open" and self.smoothed_openness < OPENNESS_CLOSED_THRESH:
            self.stage = "closed"
            rep_completed = True

        # ---- phase overlay (start / open / close / rep_complete) ----
        if self.stage == "closed":
            phase = "start"
        elif openness_velocity is not None and openness_velocity < -5.0:
            phase = "close"
        else:
            phase = "open"

        rep_duration = rep_avg_speed = rep_class = rep_form_quality = None
        form_score = rom_score = stability_score = sync_score = None
        feedback = framing_message or partial_feedback

        if rep_completed:
            rep_duration = (t - self.rep_start_time) if self.rep_start_time is not None else None
            if rep_duration and rep_duration > 0:
                rep_avg_speed = self._openness_acc / rep_duration

            valid = (
                rep_duration is not None
                and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                and self._openness_acc >= MIN_OPENNESS_DELTA
            )

            if valid:
                self.rep_count += 1
                rep_class = self._classify_tempo(rep_duration)
                self.recent_rep_durations.append(rep_duration)

                if self._rep_peak_arm_frac < 0.82:
                    self._current_rep_issues.add("arms_not_fully_raised")
                if self._rep_peak_leg_frac < 0.82:
                    self._current_rep_issues.add("legs_not_spread_enough")
                if self._rep_min_elbow_angle < ELBOW_STRAIGHT_MIN:
                    self._current_rep_issues.add("bent_elbows")

                rom_score = round(
                    100 * _clip((self._rep_peak_arm_frac + self._rep_peak_leg_frac) / 2.0)
                )
                stability_score = round(
                    100 * _clip(1 - self._rep_hip_x_max_dev / STABILITY_MAX_DRIFT_RATIO)
                )
                arm_sync = 100 * _clip(1 - self._rep_max_arm_diff / ARM_SYNC_MAX_DIFF_DEG)
                leg_sync = 100 * _clip(1 - self._rep_max_leg_diff / LEG_SYNC_MAX_DIFF_RATIO)
                sync_score = round((arm_sync + leg_sync) / 2.0)

                form_score = 100
                for issue in self._current_rep_issues:
                    form_score -= MISTAKE_PENALTY.get(issue, 10)
                form_score = max(0, form_score)

                self.rom_scores.append(rom_score)
                self.stability_scores.append(stability_score)
                self.sync_scores.append(sync_score)
                self.form_scores.append(form_score)

                if self._current_rep_issues:
                    rep_form_quality = "needs_improvement"
                    self.flawed_reps += 1
                    issue_text = ", ".join(
                        i.replace("_", " ") for i in sorted(self._current_rep_issues)
                    )
                    feedback = f"Rep {self.rep_count} counted, but watch your form ({issue_text})."
                else:
                    rep_form_quality = "good"
                    self.good_reps += 1
                    if rep_class in ("good", "fast"):
                        feedback = f"Clean rep — {rep_class} tempo ({rep_duration:.2f}s)."
                    elif rep_class in ("slow", "too_slow"):
                        feedback = f"Full extension, nice and controlled ({rep_duration:.2f}s)."
                    else:
                        feedback = f"Clean rep, but control the tempo ({rep_duration:.2f}s)."
            else:
                rep_completed = False
                if rep_duration is not None and rep_duration < MIN_REP_DURATION:
                    feedback = "Too fast — that one wasn't counted, control the movement."
                elif rep_duration is not None and rep_duration > MAX_REP_DURATION:
                    feedback = "That rep took too long — not counted. Keep moving."
                else:
                    feedback = "Not enough range of motion — not counted."

            self.rep_start_time = None
            self._openness_acc = 0.0
            self._current_rep_issues = set()
            phase = "rep_complete"

        self.last_openness = self.smoothed_openness
        self.last_timestamp_s = t

        if feedback is None and messages:
            feedback = messages[0]
        if feedback is None and not (left_arm_ok or right_arm_ok):
            feedback = "Can't see your arms clearly — face the camera with your arms visible."
        elif feedback is None and not legs_visible:
            feedback = "Can't see your legs clearly — step back for a full-body view."
        elif feedback is None and not self.calibrated:
            feedback = (
                "Stand tall facing the camera, arms at your sides, and hold still "
                "for a second — calibrating your posture."
            )
        if feedback is None:
            feedback = "Good position — keep going."

        response.update(
            {
                "pose_detected": True,
                "openness": round(raw_openness, 1),
                "smoothed_openness": round(self.smoothed_openness, 1),
                "arm_angle_left": round(left_arm_angle, 1) if left_arm_angle is not None else None,
                "arm_angle_right": round(right_arm_angle, 1) if right_arm_angle is not None else None,
                "elbow_angle_left": round(left_elbow_angle, 1) if left_elbow_angle is not None else None,
                "elbow_angle_right": round(right_elbow_angle, 1) if right_elbow_angle is not None else None,
                "leg_spread_ratio": round(leg_spread_ratio, 2) if leg_spread_ratio is not None else None,
                "openness_velocity": round(openness_velocity, 1) if openness_velocity is not None else None,
                "stage": self.stage,
                "phase": phase,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "partial_rep_count": self.partial_rep_count,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_duration": round(rep_duration, 2) if rep_duration is not None else None,
                "rep_avg_speed": round(rep_avg_speed, 1) if rep_avg_speed is not None else None,
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
                "rom_score": rom_score,
                "avg_rom_score": self._avg(self.rom_scores),
                "stability_score": stability_score,
                "avg_stability_score": self._avg(self.stability_scores),
                "sync_score": sync_score,
                "avg_sync_score": self._avg(self.sync_scores),
                "speed_analysis": {
                    "duration": round(rep_duration, 2) if rep_duration is not None else None,
                    "classification": rep_class,
                    "reps_per_minute": (
                        round(60.0 / (sum(self.recent_rep_durations) / len(self.recent_rep_durations)), 1)
                        if self.recent_rep_durations
                        else None
                    ),
                },
                "fps": fps,
                "feedback": feedback,
            }
        )
        return response


class JumpingJackSession:
    """Full jumping-jack session: one shared pose model + one bilateral analyzer."""

    def __init__(self, target_reps: Optional[int] = None):
        self.engine = PoseEngine()
        self.analyzer = JumpingJackAnalyzer(target_reps)

    def detect(self, frame, timestamp_ms: int) -> dict[str, Any]:
        landmarks = self.engine.detect(frame, timestamp_ms)
        result = self.analyzer.update(landmarks, timestamp_ms)
        result["landmarks"] = (
            PoseEngine.landmarks_to_json(landmarks) if landmarks else []
        )
        return result

    def close(self):
        self.engine.close()
