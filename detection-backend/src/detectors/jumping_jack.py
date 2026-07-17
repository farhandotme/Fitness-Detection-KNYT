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

# -------------------------
# Tunable constants
# -------------------------

MIN_LANDMARK_VISIBILITY = 0.12

CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)

# Arm / leg geometry
ARM_ANGLE_CLOSED = 55.0
ARM_ANGLE_OPEN = 92.0

LEG_SPREAD_RATIO_CLOSED = 0.28
LEG_SPREAD_RATIO_OPEN = 0.72

OPENNESS_CLOSED_THRESH = 14.0
OPENNESS_OPEN_THRESH = 24.0

MIN_REP_DURATION = 0.12
MAX_REP_DURATION = 5.0

# Calibration / posture
CALIBRATION_FRAMES = 3
TORSO_LEAN_DELTA_DEG = 50.0
TORSO_LEAN_HARD_MAX_DEG = 75.0

# Framing (much looser)
FRAME_EDGE_MARGIN = 0.015
TORSO_SPAN_TOO_CLOSE = 0.80
TORSO_SPAN_TOO_FAR = 0.03
CENTER_X_TOLERANCE = 0.65

# Rep quality thresholds
ARM_OPENNESS_MIN_GOOD = 0.35
LEG_OPENNESS_MIN_GOOD = 0.35

MISTAKE_PENALTY = {
    "arms_not_fully_raised": 5,
    "legs_not_spread_enough": 5,
    "bent_elbows": 3,
    "poor_posture": 3,
    "asymmetrical_movement": 3,
}

ISSUE_TIPS = {
    "arms_not_fully_raised": "try raising your arms a bit higher",
    "legs_not_spread_enough": "try spreading your legs a little wider",
    "bent_elbows": "try keeping your arms a bit straighter",
    "poor_posture": "try keeping your back a little straighter",
    "asymmetrical_movement": "try moving your arms and legs together",
}

SCORE_HISTORY = 10
TEMPO_HISTORY = 5
FPS_WINDOW = 30

STABILITY_MAX_DRIFT_RATIO = 1.20

# Stabilized indices (same as before)
STABILIZED_LANDMARK_INDICES = (
    LEFT_SHOULDER,
    RIGHT_SHOULDER,
    LEFT_ELBOW,
    RIGHT_ELBOW,
    LEFT_WRIST,
    RIGHT_WRIST,
    LEFT_HIP,
    RIGHT_HIP,
    LEFT_ANKLE,
    RIGHT_ANKLE,
)


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.25
    )
    return visible_core >= 2


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


def _combine_openness(
    arm_frac: Optional[float], leg_frac: Optional[float]
) -> Optional[float]:
    parts = []
    if arm_frac is not None:
        parts.append((_clip(arm_frac), 0.6))
    if leg_frac is not None:
        parts.append((_clip(leg_frac), 0.4))
    if not parts:
        return None
    total = sum(w for _, w in parts)
    return 100.0 * sum(v * w for v, w in parts) / total


def _framing_feedback(
    l_shoulder, r_shoulder, l_hip, r_hip, l_wrist, r_wrist, legs_visible: bool
) -> Optional[str]:
    mid_shoulder = _midpoint(l_shoulder, r_shoulder)
    mid_hip = _midpoint(l_hip, r_hip)

    pts = [l_shoulder, r_shoulder, l_hip, r_hip]
    for w in (l_wrist, r_wrist):
        if w is not None and getattr(w, "visibility", 1.0) is not None:
            if w.visibility is None or w.visibility > MIN_LANDMARK_VISIBILITY:
                pts.append(w)

    for p in pts:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
        ):
            return "Step back a little so I can see all of you"

    if not legs_visible:
        return "Make sure your whole body is visible in the frame"

    torso_span = abs(mid_hip.y - mid_shoulder.y)
    if torso_span > TORSO_SPAN_TOO_CLOSE:
        return "You're a bit too close — step back a little"
    if torso_span < TORSO_SPAN_TOO_FAR:
        return "You're a bit far away — step a little closer"

    if abs(mid_hip.x - 0.5) > CENTER_X_TOLERANCE:
        return "Move to the center of the frame"

    return None


class JumpingJackAnalyzer:
    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps
        self.stage = "closed"
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.partial_rep_count = 0

        self.smoothed_openness: Optional[float] = None
        self.last_openness: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None
        self.rep_start_time: Optional[float] = None
        self._openness_acc = 0.0
        self.openness_smooth_alpha = 0.22

        self.session_start_time: Optional[float] = None
        self._attempt_peak_openness: Optional[float] = None
        self._attempt_flagged = False

        self._calib_samples: list[float] = []
        self.calibrated = False
        self._baseline_torso_lean = 0.0

        self._rep_open_frames = 0
        self._rep_issue_frame_counts: dict[str, int] = {}
        self._landmark_cache: dict[int, tuple] = {}

        self._rep_peak_arm_frac = 0.0
        self._rep_peak_leg_frac = 0.0
        self._rep_hip_x_start: Optional[float] = None
        self._rep_hip_x_max_dev = 0.0
        self._current_rep_issues: set = set()

        self.form_scores: deque = deque(maxlen=SCORE_HISTORY)
        self.rom_scores: deque = deque(maxlen=SCORE_HISTORY)
        self.stability_scores: deque = deque(maxlen=SCORE_HISTORY)
        self.sync_scores: deque = deque(maxlen=SCORE_HISTORY)
        self.recent_rep_durations: deque = deque(maxlen=TEMPO_HISTORY)
        self._frame_times: deque = deque(maxlen=FPS_WINDOW)

    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 2.0:
            return "too_slow"
        if duration >= 1.0:
            return "slow"
        if duration >= 0.25:
            return "good"
        if duration >= 0.12:
            return "fast"
        return "too_fast"

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _finish_calibration(self):
        self._baseline_torso_lean = sum(self._calib_samples) / len(self._calib_samples)
        self.calibrated = True

    def _reset_rep_trackers(self, arm_frac, leg_frac, hip_x):
        self._rep_peak_arm_frac = arm_frac if arm_frac is not None else 0.0
        self._rep_peak_leg_frac = leg_frac if leg_frac is not None else 0.0
        self._rep_hip_x_start = hip_x
        self._rep_hip_x_max_dev = 0.0
        self._rep_open_frames = 0
        self._rep_issue_frame_counts = {}

    def _stabilize(self, landmarks, indices) -> dict:
        out = {}
        for i in indices:
            lm = landmarks[i]
            vis = getattr(lm, "visibility", None)
            # Very permissive: only cache short glitches
            if vis is not None and vis < MIN_LANDMARK_VISIBILITY:
                cached = self._landmark_cache.get(i)
                if cached is not None and cached[1] < 3:
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

    @staticmethod
    def _avg(d: deque) -> Optional[float]:
        return round(sum(d) / len(d), 1) if d else None

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
                    round(
                        60.0
                        / (
                            sum(self.recent_rep_durations)
                            / len(self.recent_rep_durations)
                        ),
                        1,
                    )
                    if self.recent_rep_durations
                    else None
                ),
            },
            "fps": fps,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        # --- basic person check ---
        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = "Step into the camera view to get started"
            return response

        # --- stable landmarks ---
        stable = self._stabilize(landmarks, STABILIZED_LANDMARK_INDICES)
        l_shoulder, r_shoulder = stable[LEFT_SHOULDER], stable[RIGHT_SHOULDER]
        l_elbow, r_elbow = stable[LEFT_ELBOW], stable[RIGHT_ELBOW]
        l_wrist, r_wrist = stable[LEFT_WRIST], stable[RIGHT_WRIST]
        l_hip, r_hip = stable[LEFT_HIP], stable[RIGHT_HIP]
        l_ankle, r_ankle = stable[LEFT_ANKLE], stable[RIGHT_ANKLE]

        left_arm_ok = _visible((l_hip, l_shoulder, l_elbow, l_wrist))
        right_arm_ok = _visible((r_hip, r_shoulder, r_elbow, r_wrist))
        legs_visible = _visible((l_hip, r_hip, l_ankle, r_ankle))

        # Only fail if we truly cannot see anything useful
        if not (left_arm_ok or right_arm_ok or legs_visible):
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = "Make sure your whole body is visible in the frame"
            return response

        shoulder_width = max(_dist(l_shoulder, r_shoulder), 1e-6)

        # --- arm angles ---
        left_arm_angle = _angle_deg(l_hip, l_shoulder, l_wrist) if left_arm_ok else None
        right_arm_angle = (
            _angle_deg(r_hip, r_shoulder, r_wrist) if right_arm_ok else None
        )
        arm_angles = [a for a in (left_arm_angle, right_arm_angle) if a is not None]
        arm_frac = None
        if arm_angles:
            avg_arm_angle = sum(arm_angles) / len(arm_angles)
            arm_frac = (avg_arm_angle - ARM_ANGLE_CLOSED) / (
                ARM_ANGLE_OPEN - ARM_ANGLE_CLOSED
            )

        # --- elbow angles (optional, lightweight) ---
        left_elbow_angle = (
            _angle_deg(l_shoulder, l_elbow, l_wrist) if left_arm_ok else None
        )
        right_elbow_angle = (
            _angle_deg(r_shoulder, r_elbow, r_wrist) if right_arm_ok else None
        )
        elbow_angles = [
            a for a in (left_elbow_angle, right_elbow_angle) if a is not None
        ]
        avg_elbow_angle = (
            sum(elbow_angles) / len(elbow_angles) if elbow_angles else None
        )

        # --- leg spread ---
        leg_frac = None
        leg_spread_ratio = None
        if legs_visible:
            leg_spread_ratio = _dist(l_ankle, r_ankle) / shoulder_width
            leg_frac = (leg_spread_ratio - LEG_SPREAD_RATIO_CLOSED) / (
                LEG_SPREAD_RATIO_OPEN - LEG_SPREAD_RATIO_CLOSED
            )

        # --- torso lean (posture) ---
        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
        torso_lean = None
        mid_hip = None
        if torso_visible:
            mid_shoulder = _midpoint(l_shoulder, r_shoulder)
            mid_hip = _midpoint(l_hip, r_hip)
            vertical_ref = _Point(mid_hip.x, mid_hip.y - 1.0)
            torso_lean = _angle_deg(vertical_ref, mid_hip, mid_shoulder)

        raw_openness = _combine_openness(arm_frac, leg_frac)
        if raw_openness is None:
            # Not enough to compute openness, but we still have a person
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Keep moving; I'll start counting once I see full jumps."
            )
            return response

        # --- smooth openness ---
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

        # --- framing (non‑blocking) ---
        framing_message = None
        if torso_visible:
            framing_message = _framing_feedback(
                l_shoulder, r_shoulder, l_hip, r_hip, l_wrist, r_wrist, legs_visible
            )

        # --- posture calibration ---
        if self.stage == "closed" and not self.calibrated and torso_lean is not None:
            self._calib_samples.append(torso_lean)
            if len(self._calib_samples) >= CALIBRATION_FRAMES:
                self._finish_calibration()

        issues: list[str] = []
        messages: list[str] = []

        if self.calibrated and torso_lean is not None:
            if (
                torso_lean - self._baseline_torso_lean > TORSO_LEAN_DELTA_DEG
                or torso_lean > TORSO_LEAN_HARD_MAX_DEG
            ):
                issues.append("poor_posture")
                messages.append("Try keeping your back a little straighter")

        # --- stage transitions (simple & robust) ---
        rep_completed = False

        if self.stage == "closed" and self.smoothed_openness > OPENNESS_OPEN_THRESH:
            self.stage = "open"
            self.rep_start_time = t
            self._openness_acc = 0.0
            self._reset_rep_trackers(arm_frac, leg_frac, mid_hip.x if mid_hip else None)
        elif self.stage == "open" and self.smoothed_openness < OPENNESS_CLOSED_THRESH:
            self.stage = "closed"
            rep_completed = True

        # --- rep quality tracking ---
        if self.stage == "open":
            if arm_frac is not None:
                self._rep_peak_arm_frac = max(self._rep_peak_arm_frac, arm_frac)
            if leg_frac is not None:
                self._rep_peak_leg_frac = max(self._rep_peak_leg_frac, leg_frac)
            if mid_hip is not None:
                if self._rep_hip_x_start is None:
                    self._rep_hip_x_start = mid_hip.x
                else:
                    dev = abs(mid_hip.x - self._rep_hip_x_start) / shoulder_width
                    self._rep_hip_x_max_dev = max(self._rep_hip_x_max_dev, dev)
            self._rep_open_frames += 1
            for issue in issues:
                self._rep_issue_frame_counts[issue] = (
                    self._rep_issue_frame_counts.get(issue, 0) + 1
                )

        # --- partial rep detection (simple) ---
        partial_feedback = None
        if self.stage == "closed":
            if (
                self._attempt_peak_openness is None
                or self.smoothed_openness > self._attempt_peak_openness
            ):
                self._attempt_peak_openness = self.smoothed_openness
            elif (
                not self._attempt_flagged
                and self._attempt_peak_openness is not None
                and self._attempt_peak_openness - self.smoothed_openness > 6
                and self._attempt_peak_openness < OPENNESS_OPEN_THRESH - 8
                and self._attempt_peak_openness - OPENNESS_CLOSED_THRESH > 6
            ):
                self._attempt_flagged = True
                self.partial_rep_count += 1
                partial_feedback = "Good start — try raising your arms a bit higher"

            if self.smoothed_openness < OPENNESS_CLOSED_THRESH - 2:
                self._attempt_peak_openness = None
                self._attempt_flagged = False

        # --- score & rep finalize ---
        rep_duration = rep_avg_speed = rep_class = rep_form_quality = None
        form_score = rom_score = stability_score = sync_score = None
        feedback = framing_message or partial_feedback

        if rep_completed:
            rep_duration = (
                (t - self.rep_start_time) if self.rep_start_time is not None else None
            )

            valid = (
                rep_duration is not None
                and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
            )

            if valid:
                self.rep_count += 1

                # Simple quality check
                confirmed_issues: set[str] = set()
                if self._rep_peak_arm_frac < ARM_OPENNESS_MIN_GOOD:
                    confirmed_issues.add("arms_not_fully_raised")
                if self._rep_peak_leg_frac < LEG_OPENNESS_MIN_GOOD:
                    confirmed_issues.add("legs_not_spread_enough")

                rom_score = round(
                    100
                    * _clip((self._rep_peak_arm_frac + self._rep_peak_leg_frac) / 2.0)
                )
                stability_score = round(
                    100 * _clip(1 - self._rep_hip_x_max_dev / STABILITY_MAX_DRIFT_RATIO)
                )
                sync_score = 80  # placeholder; can be expanded later

                form_score = 100
                for issue in confirmed_issues:
                    form_score -= MISTAKE_PENALTY.get(issue, 1)
                form_score = max(0, form_score)

                self.rom_scores.append(rom_score)
                self.stability_scores.append(stability_score)
                self.sync_scores.append(sync_score)
                self.form_scores.append(form_score)

                if confirmed_issues:
                    rep_form_quality = "needs_improvement"
                    self.flawed_reps += 1
                    tips = [
                        ISSUE_TIPS[issue]
                        for issue in confirmed_issues
                        if issue in ISSUE_TIPS
                    ]
                    if tips:
                        feedback = "Rep counted — " + ", ".join(tips[:2])
                    else:
                        feedback = "Rep counted."
                else:
                    rep_form_quality = "good"
                    self.good_reps += 1
                    feedback = "Nice rep! That one looked good."
            else:
                rep_completed = False
                if rep_duration is not None and rep_duration < MIN_REP_DURATION:
                    feedback = (
                        "That was too quick to count — try a slightly slower jump"
                    )
                elif rep_duration is not None and rep_duration > MAX_REP_DURATION:
                    feedback = "Try to keep moving a bit more continuously"
                else:
                    feedback = "Keep going"

            self.rep_start_time = None
            self._openness_acc = 0.0
            self._current_rep_issues = set()
            phase = "rep_complete"
        else:
            phase = "open" if self.stage == "open" else "start"

        self.last_openness = self.smoothed_openness
        self.last_timestamp_s = t

        if feedback is None and not (left_arm_ok or right_arm_ok):
            feedback = "Make sure your arms are visible in the frame"
        elif feedback is None and not legs_visible:
            feedback = "Make sure your legs are visible in the frame"
        elif feedback is None and not self.calibrated:
            feedback = "Stand still for a moment so I can get started"
        if feedback is None:
            feedback = "Keep going"

        response.update(
            {
                "pose_detected": True,
                "openness": round(raw_openness, 1),
                "smoothed_openness": round(self.smoothed_openness, 1),
                "arm_angle_left": (
                    round(left_arm_angle, 1) if left_arm_angle is not None else None
                ),
                "arm_angle_right": (
                    round(right_arm_angle, 1) if right_arm_angle is not None else None
                ),
                "elbow_angle_left": (
                    round(left_elbow_angle, 1) if left_elbow_angle is not None else None
                ),
                "elbow_angle_right": (
                    round(right_elbow_angle, 1)
                    if right_elbow_angle is not None
                    else None
                ),
                "leg_spread_ratio": (
                    round(leg_spread_ratio, 2) if leg_spread_ratio is not None else None
                ),
                "openness_velocity": (
                    round(openness_velocity, 1)
                    if openness_velocity is not None
                    else None
                ),
                "stage": self.stage,
                "phase": phase,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "partial_rep_count": self.partial_rep_count,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_duration": (
                    round(rep_duration, 2) if rep_duration is not None else None
                ),
                "rep_avg_speed": None,
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
                    "duration": (
                        round(rep_duration, 2) if rep_duration is not None else None
                    ),
                    "classification": rep_class,
                    "reps_per_minute": (
                        round(
                            60.0
                            / (
                                sum(self.recent_rep_durations)
                                / len(self.recent_rep_durations)
                            ),
                            1,
                        )
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
