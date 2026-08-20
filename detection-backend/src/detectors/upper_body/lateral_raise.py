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

REST_ANGLE = 35.0
RAISE_ANGLE = 85.0

LIFT_RAISED_THRESH = 72.0
LIFT_GROUNDED_THRESH = 24.0
MIN_ANGLE_DELTA = 18.0
MIN_REP_DURATION = 0.25
MAX_REP_DURATION = 6.0
CALIBRATION_FRAMES: int = 15

PARTIAL_REP_MARGIN = 12.0
PARTIAL_REP_MIN_RISE = 16.0
PARTIAL_REP_BOUNCE = 7.0

TORSO_LEAN_DELTA_DEG = 14.0
SHRUG_DELTA_RATIO = 0.10
ASYMMETRY_DEG = 18.0

# --- NEW STRICT BIOMECHANICS ---
ELBOW_BEND_MIN_DEG = 135.0  # Allows for the necessary slight bend
ELBOW_LOCKOUT_MAX_DEG = 172.0  # Penalizes straight, locked arms
MIN_LATERAL_WRIST_SPREAD = (
    1.6  # Wrists must be 1.6x wider than shoulders (blocks front raise)
)
WORK_ZONE_LIFT_THRESH = 40.0  # Only judge elbow bend/lockout and wrist path once the
# arm is meaningfully elevated. Below this, the arm is still near the rest position,
# where it naturally hangs fully straight — that isn't a "locked elbow" mistake, it's
# just the bottom of the rep, so it must not be counted against the lift.

PACE_SLOW_RPM = 15.0
PACE_FAST_RPM = 55.0

MISTAKE_PENALTY = {
    "poor_posture": 15,
    "shrugging": 15,
    "elbows_too_bent": 10,
    "locked_elbows": 15,  # New penalty
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


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _clip(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _lift_score(angle: float) -> float:
    return 100.0 * _clip((angle - REST_ANGLE) / (RAISE_ANGLE - REST_ANGLE))


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
    return 360 - ang if ang > 180 else ang


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
        return f"Move to the center of frame — you're too far to the {'left' if mid_hip.x < 0.5 else 'right'}."
    return None


class LateralRaiseAnalyzer:
    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps
        self.stage = "down"
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.rejected_reps = 0
        self.partial_rep_count = 0
        self.smoothed_lift: Optional[float] = None
        self.last_smoothed_lift: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None
        self.lift_smooth_alpha = 0.35
        self.form_smooth_alpha = 0.3  # smooths lean/shrug/asymmetry to filter jitter
        self._smoothed_torso_lean: Optional[float] = None
        self._smoothed_shrug_gap: Optional[float] = None
        self._smoothed_arm_gap: Optional[float] = None
        self._smoothed_left_elbow: Optional[float] = None
        self._smoothed_right_elbow: Optional[float] = None
        self._smoothed_lateral_spread: Optional[float] = None
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
        self._rep_max_elbow_angle = 0.0
        self._rep_max_asymmetry = 0.0
        self._rep_min_lateral_spread = float("inf")
        self.form_scores: deque = deque(maxlen=SCORE_HISTORY)
        self._rep_complete_times: deque = deque(maxlen=RPM_WINDOW)

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _stabilize(self, landmarks, indices) -> dict:
        out = {}
        for i in indices:
            lm = landmarks[i]
            vis = getattr(lm, "visibility", None)
            if vis is not None and vis < MIN_LANDMARK_VISIBILITY:
                cached = self._landmark_cache.get(i)
                if cached is not None and cached[1] < MAX_LANDMARK_HOLD_FRAMES:
                    out[i] = cached[0]
                    self._landmark_cache[i] = (cached[0], cached[1] + 1)
                    continue
            point = _Point(lm.x, lm.y, vis)
            out[i] = point
            self._landmark_cache[i] = (point, 0)
        return out

    def _finish_calibration(self):
        if self._calib_lean_samples:
            self._baseline_torso_lean = sum(self._calib_lean_samples) / len(
                self._calib_lean_samples
            )
        if self._calib_shrug_samples:
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
            "rejected_reps": self.rejected_reps,
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

        if not _visible((l_shoulder, l_elbow, l_wrist, l_hip)) and not _visible(
            (r_shoulder, r_elbow, r_wrist, r_hip)
        ):
            response.update(
                {
                    "pose_detected": True,
                    "low_visibility": True,
                    "feedback": "Can't see your arms clearly.",
                }
            )
            return response
        if not _visible((l_shoulder, r_shoulder, l_hip, r_hip)):
            response.update(
                {
                    "pose_detected": True,
                    "low_visibility": True,
                    "feedback": "Can't see your torso clearly.",
                }
            )
            return response

        response["pose_detected"] = True

        shoulder_dist = max(_dist(l_shoulder, r_shoulder), 1e-6)
        wrist_dist = _dist(l_wrist, r_wrist)
        raw_lateral_spread_ratio = wrist_dist / shoulder_dist
        # Wrists are the fastest-moving, noisiest-to-track landmarks in the whole
        # skeleton, so this ratio jitters frame to frame even when your actual path
        # is dead straight out to the sides. Smooth it, or "front raise vs lateral
        # raise" ends up decided by tracking noise instead of your real movement.
        a0 = self.form_smooth_alpha
        self._smoothed_lateral_spread = (
            raw_lateral_spread_ratio
            if self._smoothed_lateral_spread is None
            else a0 * raw_lateral_spread_ratio
            + (1 - a0) * self._smoothed_lateral_spread
        )
        lateral_spread_ratio = self._smoothed_lateral_spread

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)

        framing_message = _framing_feedback(l_shoulder, r_shoulder, l_hip, r_hip)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        left_angle = _angle_deg(l_hip, l_shoulder, l_elbow)
        right_angle = _angle_deg(r_hip, r_shoulder, r_elbow)
        raw_angle = (left_angle + right_angle) / 2.0
        response.update(
            {
                "left_abduction_angle": round(left_angle, 1),
                "right_abduction_angle": round(right_angle, 1),
                "angle": round(raw_angle, 1),
            }
        )
        arm_gap = abs(left_angle - right_angle)

        raw_lift = _lift_score(raw_angle)
        self.smoothed_lift = (
            raw_lift
            if self.smoothed_lift is None
            else (
                self.lift_smooth_alpha * raw_lift
                + (1 - self.lift_smooth_alpha) * self.smoothed_lift
            )
        )

        left_elbow_angle = _angle_deg(l_shoulder, l_elbow, l_wrist)
        right_elbow_angle = _angle_deg(r_shoulder, r_elbow, r_wrist)
        # Same reasoning as the wrist spread ratio above: elbow/wrist landmarks are
        # noisy, and elbow angle is what decides "too bent" vs "locked straight".
        # Smooth each arm's angle over time so a single jittery frame can't flip
        # the verdict on an otherwise identical rep.
        self._smoothed_left_elbow = (
            left_elbow_angle
            if self._smoothed_left_elbow is None
            else a0 * left_elbow_angle + (1 - a0) * self._smoothed_left_elbow
        )
        self._smoothed_right_elbow = (
            right_elbow_angle
            if self._smoothed_right_elbow is None
            else a0 * right_elbow_angle + (1 - a0) * self._smoothed_right_elbow
        )
        min_elbow_angle = min(self._smoothed_left_elbow, self._smoothed_right_elbow)
        max_elbow_angle = max(self._smoothed_left_elbow, self._smoothed_right_elbow)

        vertical_ref = _Point(mid_hip.x, mid_hip.y - 1.0)
        torso_lean = _angle_deg(vertical_ref, mid_hip, mid_shoulder)
        shrug_gap = (
            (mid_shoulder.y - nose.y) / torso_length if _visible((nose,)) else None
        )

        # Smooth these before they feed any threshold check. Raw per-frame pose
        # landmarks jitter a few pixels frame to frame, which — for these three
        # signals in particular — translates into several degrees of noise. Since
        # each rep is judged on its single worst frame, unsmoothed noise alone
        # would trip a flaw on nearly every rep regardless of actual form.
        a = a0
        self._smoothed_torso_lean = (
            torso_lean
            if self._smoothed_torso_lean is None
            else a * torso_lean + (1 - a) * self._smoothed_torso_lean
        )
        if shrug_gap is not None:
            self._smoothed_shrug_gap = (
                shrug_gap
                if self._smoothed_shrug_gap is None
                else a * shrug_gap + (1 - a) * self._smoothed_shrug_gap
            )
        self._smoothed_arm_gap = (
            arm_gap
            if self._smoothed_arm_gap is None
            else a * arm_gap + (1 - a) * self._smoothed_arm_gap
        )

        if self.stage == "down" and not self.calibrated:
            self._calib_lean_samples.append(torso_lean)
            if shrug_gap is not None:
                self._calib_shrug_samples.append(shrug_gap)
            if len(self._calib_lean_samples) >= CALIBRATION_FRAMES:
                self._finish_calibration()

        lean_delta = (
            abs(self._smoothed_torso_lean - self._baseline_torso_lean)
            if self.calibrated
            else 0.0
        )
        shrug_delta = (
            (self._baseline_shrug_gap - self._smoothed_shrug_gap)
            if self.calibrated and self._smoothed_shrug_gap is not None
            else 0.0
        )
        rep_completed = False

        if self.stage == "down":
            if self.smoothed_lift >= LIFT_RAISED_THRESH:
                self.stage = "up"
                self.rep_start_time = t
                self._lift_acc = 0.0
                self._current_rep_issues = set()
                self._rep_max_torso_lean_delta = lean_delta
                self._rep_max_shrug_delta = shrug_delta
                self._rep_min_elbow_angle = min_elbow_angle
                self._rep_max_elbow_angle = max_elbow_angle
                self._rep_max_asymmetry = self._smoothed_arm_gap
                # This frame is already past LIFT_RAISED_THRESH (> WORK_ZONE_LIFT_THRESH),
                # so it's a valid first sample of the working range.
                self._rep_min_lateral_spread = lateral_spread_ratio
                if lateral_spread_ratio < MIN_LATERAL_WRIST_SPREAD:
                    # Real-time heads-up only. The rep isn't blocked here — it's
                    # judged on the *whole* working range at completion below, so a
                    # single noisy frame can't wrongly let a front raise through.
                    response["feedback"] = (
                        "That looks like a front raise — lift OUT to your sides."
                    )
        else:
            # Only judge posture, shrug, elbow bend/lockout, wrist path, and
            # left/right symmetry while the arm is meaningfully elevated. Near the
            # bottom of the movement the arm is supposed to hang straight and one
            # side naturally starts/finishes a beat before the other — that's the
            # rest/transition position, not a form mistake.
            if self.smoothed_lift >= WORK_ZONE_LIFT_THRESH:
                self._rep_max_torso_lean_delta = max(
                    self._rep_max_torso_lean_delta, lean_delta
                )
                self._rep_max_shrug_delta = max(self._rep_max_shrug_delta, shrug_delta)
                self._rep_min_elbow_angle = min(
                    self._rep_min_elbow_angle, min_elbow_angle
                )
                self._rep_max_elbow_angle = max(
                    self._rep_max_elbow_angle, max_elbow_angle
                )
                self._rep_min_lateral_spread = min(
                    self._rep_min_lateral_spread, lateral_spread_ratio
                )
                self._rep_max_asymmetry = max(
                    self._rep_max_asymmetry, self._smoothed_arm_gap
                )

            if self.last_smoothed_lift is not None:
                self._lift_acc += abs(self.smoothed_lift - self.last_smoothed_lift)
            if self.smoothed_lift <= LIFT_GROUNDED_THRESH:
                self.stage = "down"
                rep_completed = True

        response["lift"] = round(raw_lift, 1)
        response["smoothed_lift"] = round(self.smoothed_lift, 1)

        rep_duration = rep_class = rep_form_quality = form_score = None
        feedback = response.get("feedback") or framing_message

        if rep_completed:
            rep_duration = (t - self.rep_start_time) if self.rep_start_time else None
            valid = (
                rep_duration is not None
                and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                and self._lift_acc >= MIN_ANGLE_DELTA
            )
            # Judged over the whole working range (not just the entry frame), so a
            # rep only passes if the wrists stayed out to the sides throughout —
            # not merely at the instant it crossed the "raised" threshold.
            is_front_raise = (
                valid and self._rep_min_lateral_spread < MIN_LATERAL_WRIST_SPREAD
            )

            if is_front_raise:
                valid = False
                self.rejected_reps += 1
                feedback = (
                    "That was a front raise, not a lateral raise — raise the "
                    "weights out to your sides, not forward. Not counted."
                )

            if valid:
                self.rep_count += 1
                rep_class = self._classify_tempo(rep_duration)

                if self._rep_max_torso_lean_delta > TORSO_LEAN_DELTA_DEG:
                    self._current_rep_issues.add("poor_posture")
                if self._rep_max_shrug_delta > SHRUG_DELTA_RATIO:
                    self._current_rep_issues.add("shrugging")
                if self._rep_min_elbow_angle < ELBOW_BEND_MIN_DEG:
                    self._current_rep_issues.add("elbows_too_bent")
                if self._rep_max_elbow_angle > ELBOW_LOCKOUT_MAX_DEG:
                    self._current_rep_issues.add("locked_elbows")
                if self._rep_max_asymmetry > ASYMMETRY_DEG:
                    self._current_rep_issues.add("asymmetric_raise")

                form_score = 100
                for issue in self._current_rep_issues:
                    form_score -= MISTAKE_PENALTY.get(issue, 10)
                self.form_scores.append(max(0, form_score))
                self._rep_complete_times.append(t)

                issue_messages = {
                    "poor_posture": "Keep your torso still.",
                    "shrugging": "Keep your shoulders down.",
                    "elbows_too_bent": "Don't bend elbows too much.",
                    "locked_elbows": "Keep a slight bend in your arms — don't lock your elbows straight.",
                    "asymmetric_raise": "Raise both arms evenly.",
                }
                messages = [issue_messages[i] for i in sorted(self._current_rep_issues)]

                if self._current_rep_issues:
                    rep_form_quality = "needs_improvement"
                    self.flawed_reps += 1
                    feedback = (
                        f"Rep {self.rep_count} counted, but watch form: "
                        + " ".join(messages)
                    )
                else:
                    rep_form_quality = "good"
                    self.good_reps += 1
                    feedback = f"Clean lateral raise — {rep_class} tempo."

                response.update(
                    {
                        "posture_ok": not self._current_rep_issues,
                        "posture_issues": sorted(self._current_rep_issues),
                        "posture_messages": messages,
                    }
                )
            self.rep_start_time = None
            self._lift_acc = 0.0
            self._current_rep_issues.clear()

        self.last_smoothed_lift = self.smoothed_lift
        if feedback is None:
            feedback = "Good position — raise both arms out to shoulder height."
        response.update(
            {
                "rep_completed": rep_completed,
                "rep_duration": (round(rep_duration, 2) if rep_duration else None),
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "form_score": form_score,
                "avg_form_score": self._avg(self.form_scores),
                "session_complete": self._is_complete(),
                "stage": self.stage,
                "feedback": feedback,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "rejected_reps": self.rejected_reps,
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
        self.engine, self.analyzer = PoseEngine(), LateralRaiseAnalyzer(target_reps)
        self.target_sets, self.set_number = max(1, target_sets), max(
            1, min(set_number, max(1, target_sets))
        )

    def detect(self, frame, timestamp_ms: int) -> dict[str, Any]:
        landmarks = self.engine.detect(frame, timestamp_ms)
        result = self.analyzer.update(landmarks, timestamp_ms)
        result["landmarks"] = (
            PoseEngine.landmarks_to_json(landmarks) if landmarks else []
        )
        result.update(
            {
                "set_number": self.set_number,
                "target_sets": self.target_sets,
                "exercise_complete": bool(
                    result["session_complete"] and self.set_number >= self.target_sets
                ),
            }
        )
        return result

    def close(self):
        self.engine.close()
