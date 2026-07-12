"""
Squat rep counting + posture correction.

Design
------
`SquatAnalyzer` is a pure, stateful, whole-body analyzer (unlike the bicep
curl analyzer, a squat is inherently bilateral — both legs move together —
so there's no "left/right/both" split here, just one analyzer fed the
33-point pose landmark list each frame). It knows nothing about the camera
or the MediaPipe model — `SquatSession` owns a single shared `PoseEngine`
and feeds it landmarks every frame, exactly like the bicep curl sessions.

Rep counting
------------
Driven by the average hip-knee-ankle angle across both legs (falling back
to whichever single leg is visible). Standing tall is the "down"/rest
stage (angle near 180°); squatting to at least parallel is the "up"/
contracted stage (angle at or below `UP_ANGLE`) — the same hysteresis
naming convention as the bicep curl analyzer, so the shared frontend
components (AngleGauge, stage badges) work unmodified.

Posture correction
-------------------
Three form issues are actively detected, each calibrated against the
person's own relaxed standing posture (captured automatically during the
first ~15 "standing" frames, so it works regardless of body type, distance
from camera, or camera angle):

  * knee_valgus       — knees caving inward toward each other during the
                         descent instead of tracking over the toes (a very
                         common, injury-risk squat mistake).
  * heel_lift         — heels rising off the ground, which shifts the load
                         onto the toes and reduces stability/depth.
  * excessive_forward_lean — the torso pitching too far forward / the back
                         rounding, instead of keeping a proud chest and a
                         (mostly) neutral spine.

A rep is still counted the moment it meets the range-of-motion and tempo
requirements (a flawed-form rep still counts as a rep — "perfect or
nothing" counting is discouraging), but it's tagged
`rep_form_quality: "needs_improvement"` with the specific issue(s), and a
running `good_reps` / `flawed_reps` split is kept for the session summary.

A "partial rep" heuristic also fires live coaching ("squat lower") when the
user visibly starts a descent but reverses direction before reaching real
depth — this does NOT get counted (correctly — it never crosses the
rep-completion threshold), it just adds an explanatory feedback message
instead of silence.
"""

import math
from typing import Any, Optional
from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_FOOT_INDEX,
    LEFT_HEEL,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_FOOT_INDEX,
    RIGHT_HEEL,
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
    return visible_core >= 3  # at least 3 of 4 core points confidently visible


# Knee angle (hip-knee-ankle) thresholds that drive the rep state machine.
# These also act as the hysteresis band, so a noisy angle sitting near one
# edge can't flicker the stage back and forth.
DOWN_ANGLE = 160.0  # legs considered fully standing/extended
UP_ANGLE = 100.0  # roughly parallel-or-below squat depth
MIN_ANGLE_DELTA = 40.0  # total angle travel required for a rep to "count"
MIN_REP_DURATION = 0.5  # seconds — faster than this = uncontrolled/momentum
MAX_REP_DURATION = 12.0  # seconds — slower than this = probably a pause, not a rep

# Posture calibration + thresholds. Deltas are measured against the
# person's own relaxed standing baseline rather than a fixed number, since
# "normal" stance width, torso length, and camera angle vary a lot.
CALIBRATION_FRAMES = 15

# knee-to-knee distance / ankle-to-ankle distance ratio. A healthy squat
# keeps this ratio roughly stable; it drops when the knees cave inward.
KNEE_VALGUS_RATIO_DROP = 0.20  # allowed fractional drop vs personal baseline
KNEE_VALGUS_HARD_MIN_RATIO = 0.55  # hard floor regardless of calibration

# heel/toe vertical gap, normalized by foot length. Rises when the heel
# lifts off the ground.
HEEL_LIFT_DELTA = 0.16
HEEL_LIFT_HARD_MAX = 0.55

# Forward lean is *expected* during a squat (unlike a bicep curl's torso
# sway, which should stay near zero), so the allowed delta over baseline is
# much more generous — only flags a genuinely excessive lean / rounded back.
FORWARD_LEAN_DELTA_DEG = 30.0
FORWARD_LEAN_HARD_MAX_DEG = 70.0

PARTIAL_REP_MARGIN_DEG = 15.0
PARTIAL_REP_MIN_DESCENT_DEG = 25.0
PARTIAL_REP_BOUNCE_DEG = 8.0

# -------------------------------------------------------------------------
# Camera framing / stance-position thresholds
# -------------------------------------------------------------------------
# These are independent of squat *form* — they check whether the user is
# even standing where the camera can see them well enough to trust the
# angle math above. A "perfect" detector has to get this right first: bad
# framing (too close, too far, off to one side, half out of shot) is the
# #1 cause of flaky rep counting and posture checks that never calibrate,
# so it gets checked every frame and takes priority in the coach feedback.
FRAME_EDGE_MARGIN = 0.04  # landmark within 4% of a frame edge = likely clipped
TORSO_SPAN_TOO_CLOSE = 0.42  # shoulder-to-hip normalized y-span: too large = too close
TORSO_SPAN_TOO_FAR = 0.10  # too small = too far from the camera
CENTER_X_TOLERANCE = 0.22  # allowed horizontal drift of hip midline from frame center


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


def _framing_feedback(
    l_shoulder, r_shoulder, l_hip, r_hip, feet_visible: bool
) -> Optional[str]:
    """Coaches the user into a good spot for the camera to track a squat —
    checked every frame, independent of exercise form. Returns a short
    instruction, or None if the current framing looks good.

    Checks, in order of how badly they break tracking:
      1. Part of the body clipped at a frame edge.
      2. Feet not visible (can't score depth/heel-lift without them).
      3. Too close / too far from the camera (using torso span as a
         camera-agnostic proxy for distance).
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

    if not feet_visible:
        return "Step back so your feet and ankles are visible — I need your full body in frame for a squat."

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


class SquatAnalyzer:
    """Stateful, bilateral squat rep counter + posture checker."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        # Rep state machine
        self.stage = "down"  # "down" = standing (rest), "up" = squatted
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.partial_rep_count = 0

        self.smoothed_angle: Optional[float] = None
        self.last_angle: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None
        self.rep_start_time: Optional[float] = None
        self._rep_angle_acc = 0.0
        self.angle_smooth_alpha = 0.6

        self.session_start_time: Optional[float] = None

        # "Squat lower" partial-rep detection
        self._attempt_min_angle: Optional[float] = None
        self._attempt_flagged = False

        # Personal posture baseline, captured at rest (standing). Heel gap
        # is stored separately as Optional because it needs the feet in
        # frame — a common framing miss — whereas knee-tracking and torso
        # lean only need the legs + shoulders, so they shouldn't be held
        # hostage by feet visibility.
        self._calib_samples: list[tuple[float, float, Optional[float]]] = []
        self.calibrated = False
        self._baseline_knee_ankle_ratio = 1.0
        self._baseline_torso_lean = 0.0
        self._baseline_heel_gap: Optional[float] = None

        self._current_rep_issues: set[str] = set()

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
        if duration >= 0.6:
            return "fast"
        return "too_fast"

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _finish_calibration(self):
        n = len(self._calib_samples)
        self._baseline_knee_ankle_ratio = max(
            sum(s[0] for s in self._calib_samples) / n, 1e-6
        )
        self._baseline_torso_lean = sum(s[1] for s in self._calib_samples) / n
        heel_samples = [s[2] for s in self._calib_samples if s[2] is not None]
        # Only set a heel-lift baseline if we actually saw the feet during
        # calibration. If we never did, leave it None so the heel-lift
        # check stays silently disabled instead of comparing against a
        # fabricated 0.0 baseline (which would misfire the moment the feet
        # do become visible mid-set).
        self._baseline_heel_gap = (
            sum(heel_samples) / len(heel_samples) if heel_samples else None
        )
        self.calibrated = True

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "angle": None,
            "smoothed_angle": None,
            "left_knee_angle": None,
            "right_knee_angle": None,
            "angle_velocity": None,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
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
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None:
            response["feedback"] = "No person detected — step into frame."
            return response

        if not _looks_like_a_person(landmarks):
            response["feedback"] = "No person detected — step into frame."
            return response

        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]
        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_heel, r_heel = landmarks[LEFT_HEEL], landmarks[RIGHT_HEEL]
        l_toe, r_toe = landmarks[LEFT_FOOT_INDEX], landmarks[RIGHT_FOOT_INDEX]

        left_leg_ok = _visible((l_hip, l_knee, l_ankle))
        right_leg_ok = _visible((r_hip, r_knee, r_ankle))

        if not left_leg_ok and not right_leg_ok:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["angle"] = self.last_angle
            response["smoothed_angle"] = self.smoothed_angle
            response["feedback"] = (
                "Can't see your legs clearly — step back so your full body is in frame."
            )
            return response

        # ---- knee angle (drives rep counting) — average of both legs, or
        # whichever single leg is visible ----
        left_angle = _angle_deg(l_hip, l_knee, l_ankle) if left_leg_ok else None
        right_angle = _angle_deg(r_hip, r_knee, r_ankle) if right_leg_ok else None
        angles = [a for a in (left_angle, right_angle) if a is not None]
        raw_angle = sum(angles) / len(angles)

        if self.smoothed_angle is None:
            self.smoothed_angle = raw_angle
        else:
            self.smoothed_angle = (
                self.angle_smooth_alpha * raw_angle
                + (1 - self.angle_smooth_alpha) * self.smoothed_angle
            )

        angle_velocity = None
        if self.last_angle is not None and self.last_timestamp_s is not None:
            dt = t - self.last_timestamp_s
            if dt > 0:
                angle_velocity = (self.smoothed_angle - self.last_angle) / dt

        # ---- posture metrics + calibration (need both legs + torso) ----
        both_legs_visible = left_leg_ok and right_leg_ok
        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
        feet_visible = _visible((l_heel, r_heel, l_toe, r_toe))

        knee_ankle_ratio = torso_lean = heel_gap = None

        if both_legs_visible:
            knee_dist = _dist(l_knee, r_knee)
            ankle_dist = max(_dist(l_ankle, r_ankle), 1e-6)
            knee_ankle_ratio = knee_dist / ankle_dist

        if torso_visible:
            mid_shoulder = _midpoint(l_shoulder, r_shoulder)
            mid_hip = _midpoint(l_hip, r_hip)
            vertical_ref = _Point(mid_hip.x, mid_hip.y - 1.0)
            torso_lean = _angle_deg(vertical_ref, mid_hip, mid_shoulder)

        if feet_visible:
            l_foot_len = max(_dist(l_heel, l_toe), 1e-6)
            r_foot_len = max(_dist(r_heel, r_toe), 1e-6)
            l_gap = (l_toe.y - l_heel.y) / l_foot_len
            r_gap = (r_toe.y - r_heel.y) / r_foot_len
            heel_gap = (l_gap + r_gap) / 2.0

        # ---- camera framing / stance-position check (every frame) ----
        # This runs independent of calibration state — bad framing is worth
        # flagging immediately, and it's also *why* calibration or posture
        # checks may be silently failing, so it doubles as the explanation.
        framing_message = None
        if torso_visible:
            framing_message = _framing_feedback(
                l_shoulder, r_shoulder, l_hip, r_hip, feet_visible
            )
        elif both_legs_visible:
            framing_message = (
                "Step back — I can see your legs but not your upper body. "
                "Get your full body in frame, facing the camera."
            )

        # Calibration only strictly needs both legs + torso (knee tracking,
        # torso lean). Feet are nice-to-have for the heel-lift check but
        # shouldn't block calibration entirely — plenty of valid camera
        # setups crop the feet out.
        can_calibrate = knee_ankle_ratio is not None and torso_lean is not None
        if self.stage == "down" and not self.calibrated and can_calibrate:
            self._calib_samples.append((knee_ankle_ratio, torso_lean, heel_gap))
            if len(self._calib_samples) >= CALIBRATION_FRAMES:
                self._finish_calibration()

        issues: list[str] = []
        messages: list[str] = []
        if self.calibrated:
            if knee_ankle_ratio is not None:
                drop = (
                    self._baseline_knee_ankle_ratio - knee_ankle_ratio
                ) / self._baseline_knee_ankle_ratio
                if (
                    drop > KNEE_VALGUS_RATIO_DROP
                    or knee_ankle_ratio < KNEE_VALGUS_HARD_MIN_RATIO
                ):
                    issues.append("knee_valgus")
                    messages.append("Push your knees out — don't let them cave inward.")

            if heel_gap is not None and self._baseline_heel_gap is not None:
                if (
                    heel_gap - self._baseline_heel_gap > HEEL_LIFT_DELTA
                    or heel_gap > HEEL_LIFT_HARD_MAX
                ):
                    issues.append("heel_lift")
                    messages.append(
                        "Keep your heels flat on the ground — weight is shifting to your toes."
                    )

            if torso_lean is not None:
                if (
                    torso_lean - self._baseline_torso_lean > FORWARD_LEAN_DELTA_DEG
                    or torso_lean > FORWARD_LEAN_HARD_MAX_DEG
                ):
                    issues.append("excessive_forward_lean")
                    messages.append(
                        "Keep your chest up — you're leaning too far forward."
                    )

        # ---- "squat lower" partial-rep coaching (pre-transition stage) ----
        partial_feedback = None
        if self.stage == "down":
            if (
                self._attempt_min_angle is None
                or self.smoothed_angle < self._attempt_min_angle
            ):
                self._attempt_min_angle = self.smoothed_angle
            elif (
                not self._attempt_flagged
                and self._attempt_min_angle is not None
                and self.smoothed_angle - self._attempt_min_angle
                > PARTIAL_REP_BOUNCE_DEG
                and self._attempt_min_angle > UP_ANGLE + PARTIAL_REP_MARGIN_DEG
                and DOWN_ANGLE - self._attempt_min_angle > PARTIAL_REP_MIN_DESCENT_DEG
            ):
                self._attempt_flagged = True
                self.partial_rep_count += 1
                partial_feedback = (
                    f"Squat lower — you stopped around {self._attempt_min_angle:.0f}°, "
                    f"aim for {UP_ANGLE:.0f}° or less (thighs at least parallel)."
                )

            if self.smoothed_angle > DOWN_ANGLE - 5:
                self._attempt_min_angle = None
                self._attempt_flagged = False

        # ---- rep arc-length accumulator (sanity check against tiny wobbles) ----
        if self.stage == "down" and self.smoothed_angle < UP_ANGLE:
            self.rep_start_time = t
            self._rep_angle_acc = 0.0
        if self.last_angle is not None:
            self._rep_angle_acc += abs(self.smoothed_angle - self.last_angle)

        # ---- rep state machine ----
        rep_completed = False
        if self.stage == "down" and self.smoothed_angle < UP_ANGLE:
            self.stage = "up"
            self._current_rep_issues = set()
        elif self.stage == "up" and self.smoothed_angle > DOWN_ANGLE:
            self.stage = "down"
            rep_completed = True

        if self.stage == "up":
            self._current_rep_issues.update(issues)

        rep_duration = rep_avg_speed = rep_class = rep_form_quality = None
        # Framing problems make every other signal unreliable, so they beat
        # the "squat lower" nudge — but a rep that just completed is still
        # the single most important thing to tell the user, so it's allowed
        # to override both below.
        feedback = framing_message or partial_feedback

        if rep_completed:
            rep_duration = (
                (t - self.rep_start_time) if self.rep_start_time is not None else None
            )
            if rep_duration and rep_duration > 0:
                rep_avg_speed = self._rep_angle_acc / rep_duration

            valid = (
                rep_duration is not None
                and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                and self._rep_angle_acc >= MIN_ANGLE_DELTA
            )

            if valid:
                self.rep_count += 1
                rep_class = self._classify_tempo(rep_duration)

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
                        feedback = (
                            f"Clean rep — {rep_class} tempo ({rep_duration:.2f}s)."
                        )
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
            self._rep_angle_acc = 0.0
            self._current_rep_issues = set()

        self.last_angle = self.smoothed_angle
        self.last_timestamp_s = t

        if feedback is None and messages:
            feedback = messages[0]
        if feedback is None and not both_legs_visible:
            feedback = "Only one leg is fully visible — step back for a full-body view."
        if feedback is None and not self.calibrated:
            feedback = (
                "Stand tall facing the camera, feet shoulder-width apart, and hold "
                "still for a second — calibrating your posture."
            )
        if feedback is None:
            feedback = "Good position — posture looks good."

        response.update(
            {
                "pose_detected": True,
                "angle": raw_angle,
                "smoothed_angle": self.smoothed_angle,
                "left_knee_angle": left_angle,
                "right_knee_angle": right_angle,
                "angle_velocity": angle_velocity,
                "stage": self.stage,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_duration": rep_duration,
                "rep_avg_speed": rep_avg_speed,
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "calibrated": self.calibrated,
                "posture_ok": len(issues) == 0,
                "posture_issues": issues,
                "posture_messages": messages,
                "framing_ok": framing_message is None,
                "framing_message": framing_message,
                "feedback": feedback,
            }
        )
        return response


class SquatSession:
    """Full squat session: one shared pose model + one bilateral analyzer."""

    def __init__(self, target_reps: Optional[int] = None):
        self.engine = PoseEngine()
        self.analyzer = SquatAnalyzer(target_reps)

    def detect(self, frame, timestamp_ms: int) -> dict[str, Any]:
        landmarks = self.engine.detect(frame, timestamp_ms)
        result = self.analyzer.update(landmarks, timestamp_ms)
        result["landmarks"] = (
            PoseEngine.landmarks_to_json(landmarks) if landmarks else []
        )
        return result

    def close(self):
        self.engine.close()
