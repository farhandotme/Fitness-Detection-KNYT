"""
Dead Bug core-stability rep counting + form validation.

Design
------
`DeadBugAnalyzer` follows the same shape as JabAnalyzer / squat.py:
- One shared PoseEngine (owned by `DeadBugSession`) feeds it 33-point
  landmarks every frame.
- It knows nothing about the camera or websocket.

Dead bug specifics
------------------
- User lies supine (on back), arms extended toward ceiling, knees bent
  ~90° in “tabletop” (hips and knees at ~90°).
- A rep = contralateral arm+leg extension and return:
  * e.g. right arm overhead + left leg straight out, then back to start.
  * then optionally left arm + right leg, etc.
- Core must stay braced: lower back pressed into floor, minimal arching.
- Movement should be slow, controlled, no jerking.

Form gates & metrics
--------------------
Each side (right arm+left leg, left arm+right leg) is tracked with its own
state machine:

  * "start"   — arms up, knees tabletop, not extending yet.
  * "extend"  — arm overhead + opposite leg extended.
  * "return"  — back to start.

A rep completes on the "extend" -> "start" return transition.

Mistake / form checks (live, per rep):
  * arched_back   — lower back rises off floor (pelvis tilts, lumbar extension).
  * rib_flare     — rib cage pops up, chest over-extends.
  * leg_too_low   — lowering leg drops below a safe hip-flexion angle.
  * arm_not_straight — elbow bends during overhead reach.
  * too_fast / too slow — rep duration outside valid window.
  * incomplete_range — arm/leg didn’t extend far enough.

A rep that completes but has issues still counts, marked
`rep_form_quality: "needs_improvement"` with specific issues.
A rep that doesn’t meet minimum range or timing may be not counted and
tracked separately (e.g. `not_counted_incomplete`).

Landmarks used
--------------
- Shoulders (11,12), elbows (13,14), wrists (15,16)
- Hips (23,24), knees (25,26), ankles (27,28)
- Nose (0) for reference / orientation check
- For “back on floor” we infer from hip/shoulder height vs torso ref.

Camera framing
--------------
- Camera should be to the side (sagittal view) or slightly above, showing
  full body from head to feet.
- User lying on back, whole body visible, not cut off.
- `_framing_feedback` checks edge clipping, distance, and centering.

"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    LEFT_WRIST,
    NOSE,
    PoseEngine,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
    LEFT_ANKLE,
    RIGHT_ANKLE,
)

# -------------------------------------------------------------------------
# Tunable constants
# -------------------------------------------------------------------------

MIN_LANDMARK_VISIBILITY = 0.4
CORE_LANDMARKS = (
    LEFT_SHOULDER,
    RIGHT_SHOULDER,
    LEFT_HIP,
    RIGHT_HIP,
    LEFT_KNEE,
    RIGHT_KNEE,
)

CALIBRATION_FRAMES = 15

# Arm angle: shoulder-elbow-wrist, degrees.
# ~180 = straight overhead, ~90 = elbow bent 90°.
ARM_STRAIGHT_MIN = 150.0  # arm considered "straight enough" when >= this
ARM_BENT_THRESHOLD = 110.0  # arm considered "bent" when <= this

# Leg angle: hip-knee-ankle, degrees.
# ~180 = fully straight, ~90 = 90° bend.
LEG_EXTENDED_MIN = 150.0  # leg considered "extended" when >= this
LEG_BENT_THRESHOLD = 110.0  # leg considered "bent" when <= this

# Hip angle: shoulder-hip-knee (approx hip flexion).
# Controls how low the leg is dropping.
HIP_FLEXION_SAFE_MAX = 120.0  # above this = leg too low / unsafe

# Back arch / rib flare proxies:
# Use shoulder-hip line vs world vertical and relative heights.
BACK_ARCH_HEIGHT_DELTA = 0.08  # normalized by torso_ref

# Rep timing
MIN_REP_DURATION = 1.5  # dead bug should be slow & controlled
MAX_REP_DURATION = 6.0  # slower than this = not a proper rep

# Range-of-motion thresholds
ARM_EXTENSION_ROM_MIN = 0.6
LEG_EXTENSION_ROM_MIN = 0.6

# -------------------------------------------------------------------------
# Camera framing thresholds
# -------------------------------------------------------------------------
FRAME_EDGE_MARGIN = 0.04
TORSO_SPAN_TOO_CLOSE = 0.55
TORSO_SPAN_TOO_FAR = 0.10
CENTER_X_TOLERANCE = 0.30


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
    l_shoulder,
    r_shoulder,
    l_hip,
    r_hip,
    l_knee,
    r_knee,
    l_ankle,
    r_ankle,
    body_visible: bool,
) -> Optional[str]:
    """Coaches the user into a good spot for the camera — dead bug:
    full body visible, side or slight top-down view."""
    mid_shoulder = _midpoint(l_shoulder, r_shoulder)
    mid_hip = _midpoint(l_hip, r_hip)

    body_points = [
        l_shoulder,
        r_shoulder,
        l_hip,
        r_hip,
        l_knee,
        r_knee,
        l_ankle,
        r_ankle,
    ]

    for p in body_points:
        if p is None:
            continue
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return "You're partly out of frame — center yourself so your whole body is visible."

    if not body_visible:
        return "Can't see your full body — get your head, torso, and legs in frame."

    torso_span = _dist(mid_shoulder, mid_hip)
    if torso_span > TORSO_SPAN_TOO_CLOSE:
        return "You're too close to the camera — step back until your whole body fits in frame."
    if torso_span < TORSO_SPAN_TOO_FAR:
        return (
            "You're too far from the camera — move a bit closer for accurate tracking."
        )

    if abs(mid_shoulder.x - 0.5) > CENTER_X_TOLERANCE:
        return (
            "Center yourself in frame; lie on your back with your full length visible."
        )

    return None


class DeadBugAnalyzer:
    """Stateful dead bug core exercise rep counter + form validator."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        # Each contralateral pair is its own “side”:
        # "right_arm_left_leg" and "left_arm_right_leg"
        self.stage = {
            "right_arm_left_leg": "start",
            "left_arm_right_leg": "start",
        }
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.not_counted_incomplete = 0

        # Smoothed angles
        self.smoothed_arm_angle: dict[str, Optional[float]] = {
            "right": None,
            "left": None,
        }
        self.smoothed_leg_angle: dict[str, Optional[float]] = {
            "right": None,
            "left": None,
        }
        self.last_arm_angle: dict[str, Optional[float]] = {
            "right": None,
            "left": None,
        }
        self.last_leg_angle: dict[str, Optional[float]] = {
            "right": None,
            "left": None,
        }

        self.rep_start_time: dict[str, Optional[float]] = {
            "right_arm_left_leg": None,
            "left_arm_right_leg": None,
        }
        self._arm_angle_acc: dict[str, float] = {"right": 0.0, "left": 0.0}
        self._leg_angle_acc: dict[str, float] = {"right": 0.0, "left": 0.0}
        self.angle_smooth_alpha = 0.5

        self.session_start_time: Optional[float] = None

        # Calibration: baseline “arms up, knees 90°” pose
        self._calib_arm_angle: dict[str, list[float]] = {
            "right": [],
            "left": [],
        }
        self._calib_leg_angle: dict[str, list[float]] = {
            "right": [],
            "left": [],
        }
        self._calib_hip_angle: dict[str, list[float]] = {
            "right": [],
            "left": [],
        }
        self.calibrated = False

        self._baseline_arm_angle = {"right": 90.0, "left": 90.0}
        self._baseline_leg_angle = {"right": 90.0, "left": 90.0}
        self._baseline_hip_angle = {"right": 90.0, "left": 90.0}

        self._current_rep_issues: dict[str, set] = {
            "right_arm_left_leg": set(),
            "left_arm_right_leg": set(),
        }

        # ROM tracking for this rep
        self._rep_max_arm_angle = {"right": 0.0, "left": 0.0}
        self._rep_max_leg_angle = {"right": 0.0, "left": 0.0}
        self._rep_min_hip_angle = {"right": 180.0, "left": 180.0}

        # Back arch detection
        self._baseline_shoulder_hip_height_delta = 0.0
        self._calib_shoulder_hip_delta: list[float] = []

    # ---------------------------------------------------------------
    def _is_complete(self) -> bool:
        if self.target_reps is None:
            return False
        return self.rep_count >= self.target_reps

    def _finish_calibration(self):
        for side in ("right", "left"):
            arm_samples = self._calib_arm_angle[side]
            leg_samples = self._calib_leg_angle[side]
            hip_samples = self._calib_hip_angle[side]

            if arm_samples:
                self._baseline_arm_angle[side] = sum(arm_samples) / len(arm_samples)
            if leg_samples:
                self._baseline_leg_angle[side] = sum(leg_samples) / len(leg_samples)
            if hip_samples:
                self._baseline_hip_angle[side] = sum(hip_samples) / len(hip_samples)

        if self._calib_shoulder_hip_delta:
            self._baseline_shoulder_hip_height_delta = sum(
                self._calib_shoulder_hip_delta
            ) / len(self._calib_shoulder_hip_delta)
        self.calibrated = True

    # ---------------------------------------------------------------
    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 4.0:
            return "too_slow"
        if duration >= 2.5:
            return "slow"
        if duration >= 1.8:
            return "good"
        if duration >= 1.2:
            return "fast"
        return "too_fast"

    # ---------------------------------------------------------------
    def _update_side(
        self,
        side_name: str,
        arm_side: str,
        leg_side: str,
        raw_arm_angle: Optional[float],
        raw_leg_angle: Optional[float],
        raw_hip_angle: Optional[float],
        shoulder_hip_height_delta: float,
        t: float,
    ) -> Optional[dict]:
        """Runs the state machine for one contralateral pair
        (e.g. right arm + left leg)."""
        if raw_arm_angle is None or raw_leg_angle is None:
            return None

        # Smooth arm angle
        prev_arm = self.smoothed_arm_angle[arm_side]
        self.smoothed_arm_angle[arm_side] = (
            raw_arm_angle
            if prev_arm is None
            else self.angle_smooth_alpha * raw_arm_angle
            + (1 - self.angle_smooth_alpha) * prev_arm
        )
        arm_angle = self.smoothed_arm_angle[arm_side]

        # Smooth leg angle
        prev_leg = self.smoothed_leg_angle[leg_side]
        self.smoothed_leg_angle[leg_side] = (
            raw_leg_angle
            if prev_leg is None
            else self.angle_smooth_alpha * raw_leg_angle
            + (1 - self.angle_smooth_alpha) * prev_leg
        )
        leg_angle = self.smoothed_leg_angle[leg_side]

        outcome: dict[str, Any] = {
            "rep_completed": False,
            "counted": False,
            "rep_duration": None,
            "rep_avg_speed": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "issues": set(),
            "feedback": None,
        }

        # ---- state machine ----
        stage = self.stage[side_name]
        rep_completed = False

        # Consider "extended" when both arm and leg are sufficiently straight
        arm_extended = arm_angle >= ARM_STRAIGHT_MIN
        leg_extended = leg_angle >= LEG_EXTENDED_MIN

        if stage == "start":
            # Transition to "extend" when both arm & leg start extending
            if arm_extended and leg_extended:
                self.stage[side_name] = "extend"
                self.rep_start_time[side_name] = t
                self._arm_angle_acc[arm_side] = 0.0
                self._leg_angle_acc[leg_side] = 0.0
                self._current_rep_issues[side_name] = set()
                self._rep_max_arm_angle[arm_side] = arm_angle
                self._rep_max_leg_angle[leg_side] = leg_angle
                self._rep_min_hip_angle[leg_side] = (
                    raw_hip_angle if raw_hip_angle is not None else 180.0
                )
        elif stage == "extend":
            # Track peak extension and min hip angle
            if arm_angle > self._rep_max_arm_angle[arm_side]:
                self._rep_max_arm_angle[arm_side] = arm_angle
            if leg_angle > self._rep_max_leg_angle[leg_side]:
                self._rep_max_leg_angle[leg_side] = leg_angle
            if (
                raw_hip_angle is not None
                and raw_hip_angle < self._rep_min_hip_angle[leg_side]
            ):
                self._rep_min_hip_angle[leg_side] = raw_hip_angle

            # Form checks while extended
            # 1) arched_back (shoulder-hip height delta too large)
            if self.calibrated:
                delta_change = abs(
                    shoulder_hip_height_delta - self._baseline_shoulder_hip_height_delta
                )
                if delta_change > BACK_ARCH_HEIGHT_DELTA:
                    self._current_rep_issues[side_name].add("arched_back")

            # 2) leg_too_low (hip flexion too large -> leg dropping)
            if raw_hip_angle is not None and raw_hip_angle > HIP_FLEXION_SAFE_MAX:
                self._current_rep_issues[side_name].add("leg_too_low")

            # 3) arm_not_straight (if arm angle dips below threshold during "extend")
            if arm_angle < ARM_STRAIGHT_MIN - 15:
                self._current_rep_issues[side_name].add("arm_not_straight")

            # Return to start when both arm & leg come back to bent position
            arm_bent = arm_angle <= ARM_BENT_THRESHOLD
            leg_bent = leg_angle <= LEG_BENT_THRESHOLD
            if arm_bent and leg_bent:
                self.stage[side_name] = "start"
                rep_completed = True

        # Accumulate angle change for speed estimate
        if self.last_arm_angle[arm_side] is not None:
            self._arm_angle_acc[arm_side] += abs(
                arm_angle - self.last_arm_angle[arm_side]
            )
        if self.last_leg_angle[leg_side] is not None:
            self._leg_angle_acc[leg_side] += abs(
                leg_angle - self.last_leg_angle[leg_side]
            )

        if rep_completed:
            rep_duration = (
                (t - self.rep_start_time[side_name])
                if self.rep_start_time[side_name] is not None
                else None
            )
            total_angle_travel = (
                self._arm_angle_acc[arm_side] + self._leg_angle_acc[leg_side]
            )
            rep_avg_speed = (
                total_angle_travel / rep_duration
                if rep_duration and rep_duration > 0
                else None
            )

            # Range-of-motion checks
            arm_rom = (
                (self._rep_max_arm_angle[arm_side] - self._baseline_arm_angle[arm_side])
                / (180.0 - self._baseline_arm_angle[arm_side])
                if (180.0 - self._baseline_arm_angle[arm_side]) > 1e-3
                else 0.0
            )
            leg_rom = (
                (self._rep_max_leg_angle[leg_side] - self._baseline_leg_angle[leg_side])
                / (180.0 - self._baseline_leg_angle[leg_side])
                if (180.0 - self._baseline_leg_angle[leg_side]) > 1e-3
                else 0.0
            )

            motion_valid = (
                rep_duration is not None
                and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
            )

            if not motion_valid:
                if rep_duration is not None and rep_duration < MIN_REP_DURATION:
                    outcome["feedback"] = (
                        "Too fast — dead bug should be slow and controlled. Not counted."
                    )
                elif rep_duration is not None and rep_duration > MAX_REP_DURATION:
                    outcome["feedback"] = (
                        "That took too long — not counted. Keep it smooth but purposeful."
                    )
                else:
                    outcome["feedback"] = "Movement not clear enough — not counted."
            elif arm_rom < ARM_EXTENSION_ROM_MIN or leg_rom < LEG_EXTENSION_ROM_MIN:
                self.not_counted_incomplete += 1
                outcome["feedback"] = (
                    "Extend your arm and leg more — that rep was too shallow, not counted."
                )
            else:
                self.rep_count += 1
                outcome["counted"] = True
                outcome["rep_completed"] = True
                outcome["rep_duration"] = round(rep_duration, 2)
                outcome["rep_avg_speed"] = (
                    round(rep_avg_speed, 1) if rep_avg_speed else None
                )
                outcome["rep_classification"] = self._classify_tempo(rep_duration)

                issues = self._current_rep_issues[side_name]
                outcome["issues"] = issues

                if issues:
                    outcome["rep_form_quality"] = "needs_improvement"
                    self.flawed_reps += 1
                    issue_text = ", ".join(i.replace("_", " ") for i in sorted(issues))
                    outcome["feedback"] = (
                        f"Dead bug {self.rep_count} counted, but watch your form ({issue_text})."
                    )
                else:
                    outcome["rep_form_quality"] = "good"
                    self.good_reps += 1
                    cls = outcome["rep_classification"]
                    if cls in ("good", "slow"):
                        outcome["feedback"] = (
                            f"Clean dead bug — {cls} tempo ({rep_duration:.2f}s)."
                        )
                    else:
                        outcome["feedback"] = (
                            f"Clean dead bug, keep it controlled ({rep_duration:.2f}s)."
                        )

            # Reset per-rep accumulators
            self.rep_start_time[side_name] = None
            self._arm_angle_acc[arm_side] = 0.0
            self._leg_angle_acc[leg_side] = 0.0
            self._current_rep_issues[side_name] = set()
            self._rep_max_arm_angle[arm_side] = 0.0
            self._rep_max_leg_angle[leg_side] = 0.0
            self._rep_min_hip_angle[leg_side] = 180.0

        self.last_arm_angle[arm_side] = arm_angle
        self.last_leg_angle[leg_side] = leg_angle
        return outcome

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "left_arm_angle": None,
            "right_arm_angle": None,
            "left_leg_angle": None,
            "right_leg_angle": None,
            "active_side": None,  # "right_arm_left_leg" | "left_arm_right_leg" | None
            "phase": "start",
            "stage": "start",
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "not_counted_incomplete": self.not_counted_incomplete,
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
            response["feedback"] = (
                "No person detected — lie on your back with full body in frame."
            )
            return response

        # Extract landmarks
        l_sh, r_sh = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_el, r_el = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wr, r_wr = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_hip_pt, r_hip_pt = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]
        nose = landmarks[NOSE]

        # Visibility checks
        left_arm_ok = _visible((l_sh, l_el, l_wr))
        right_arm_ok = _visible((r_sh, r_el, r_wr))
        left_leg_ok = _visible((l_hip_pt, l_knee, l_ankle))
        right_leg_ok = _visible((r_hip_pt, r_knee, r_ankle))
        torso_ok = _visible((l_sh, r_sh, l_hip_pt, r_hip_pt))
        nose_visible = nose is not None and (
            nose.visibility is None or nose.visibility >= MIN_LANDMARK_VISIBILITY
        )

        if not torso_ok or not nose_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your upper body and head clearly — lie on your back "
                "with your whole torso and head in frame."
            )
            return response

        if not (left_arm_ok and right_arm_ok):
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see both arms — get your arms and hands in frame."
            )
            return response

        if not (left_leg_ok and right_leg_ok):
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see both legs — get your knees and feet in frame."
            )
            return response

        mid_shoulder = _midpoint(l_sh, r_sh)
        mid_hip = _midpoint(l_hip_pt, r_hip_pt)
        torso_ref = max(_dist(mid_shoulder, mid_hip), 1e-6)

        framing_message = _framing_feedback(
            l_sh, r_sh, l_hip_pt, r_hip_pt, l_knee, r_knee, l_ankle, r_ankle, True
        )

        # Compute angles
        # Arm angles: shoulder-elbow-wrist
        left_arm_angle = _angle_deg(l_sh, l_el, l_wr) if left_arm_ok else None
        right_arm_angle = _angle_deg(r_sh, r_el, r_wr) if right_arm_ok else None

        # Leg angles: hip-knee-ankle
        left_leg_angle = _angle_deg(l_hip_pt, l_knee, l_ankle) if left_leg_ok else None
        right_leg_angle = (
            _angle_deg(r_hip_pt, r_knee, r_ankle) if right_leg_ok else None
        )

        # Hip angles (approx hip flexion): shoulder-hip-knee
        left_hip_angle = (
            _angle_deg(l_sh, l_hip_pt, l_knee)
            if (l_sh and l_hip_pt and l_knee)
            else None
        )
        right_hip_angle = (
            _angle_deg(r_sh, r_hip_pt, r_knee)
            if (r_sh and r_hip_pt and r_knee)
            else None
        )

        # Back arch proxy: shoulder vs hip height (y) relative to torso_ref
        shoulder_hip_height_delta = (mid_shoulder.y - mid_hip.y) / torso_ref

        # Calibration: when both arms up and knees ~90°, and both sides in "start"
        both_start = (
            self.stage["right_arm_left_leg"] == "start"
            and self.stage["left_arm_right_leg"] == "start"
        )
        if (
            both_start
            and not self.calibrated
            and left_arm_angle is not None
            and right_arm_angle is not None
            and left_leg_angle is not None
            and right_leg_angle is not None
        ):
            self._calib_arm_angle["left"].append(left_arm_angle)
            self._calib_arm_angle["right"].append(right_arm_angle)
            self._calib_leg_angle["left"].append(left_leg_angle)
            self._calib_leg_angle["right"].append(right_leg_angle)
            if left_hip_angle is not None:
                self._calib_hip_angle["left"].append(left_hip_angle)
            if right_hip_angle is not None:
                self._calib_hip_angle["right"].append(right_hip_angle)
            self._calib_shoulder_hip_delta.append(shoulder_hip_height_delta)

            if len(self._calib_arm_angle["left"]) >= CALIBRATION_FRAMES:
                self._finish_calibration()

        # Fallback calibration if user never calibrates
        if not self.calibrated and elapsed > 10.0:
            for side in ("left", "right"):
                if not self._baseline_arm_angle[side]:
                    self._baseline_arm_angle[side] = 90.0
                if not self._baseline_leg_angle[side]:
                    self._baseline_leg_angle[side] = 90.0
                if not self._baseline_hip_angle[side]:
                    self._baseline_hip_angle[side] = 90.0
            if not self._baseline_shoulder_hip_height_delta:
                self._baseline_shoulder_hip_height_delta = 0.0
            self.calibrated = True

        # Per-side state updates
        right_outcome = self._update_side(
            "right_arm_left_leg",
            "right",
            "left",
            right_arm_angle,
            left_leg_angle,
            right_hip_angle,
            shoulder_hip_height_delta,
            t,
        )
        left_outcome = self._update_side(
            "left_arm_right_leg",
            "left",
            "right",
            left_arm_angle,
            right_leg_angle,
            left_hip_angle,
            shoulder_hip_height_delta,
            t,
        )

        completed = None
        if right_outcome and right_outcome["rep_completed"]:
            completed = right_outcome
        elif left_outcome and left_outcome["rep_completed"]:
            completed = left_outcome

        active_side = None
        if self.stage["right_arm_left_leg"] == "extend":
            active_side = "right_arm_left_leg"
        elif self.stage["left_arm_right_leg"] == "extend":
            active_side = "left_arm_right_leg"

        phase = "start"
        if completed:
            phase = "rep_complete"
        elif active_side:
            phase = f"{active_side}_extend"

        # Posture messages
        issues: list[str] = []
        messages: list[str] = []
        if completed and completed["issues"]:
            if "arched_back" in completed["issues"]:
                issues.append("arched_back")
                messages.append(
                    "Keep your lower back pressed into the floor; don't arch."
                )
            if "leg_too_low" in completed["issues"]:
                issues.append("leg_too_low")
                messages.append("Don't let your leg drop too low; keep it controlled.")
            if "arm_not_straight" in completed["issues"]:
                issues.append("arm_not_straight")
                messages.append("Keep your reaching arm straighter, not bent.")

        feedback = framing_message
        if feedback is None and completed and completed["feedback"]:
            feedback = completed["feedback"]
        if feedback is None and messages:
            feedback = messages[0]
        if feedback is None and not self.calibrated:
            feedback = "Hold your start position still — calibrating your baseline."
        if feedback is None:
            feedback = "Good dead bug position — move slowly and keep your core tight."

        response.update(
            {
                "pose_detected": True,
                "left_arm_angle": (
                    round(self.smoothed_arm_angle["left"], 1)
                    if self.smoothed_arm_angle["left"] is not None
                    else None
                ),
                "right_arm_angle": (
                    round(self.smoothed_arm_angle["right"], 1)
                    if self.smoothed_arm_angle["right"] is not None
                    else None
                ),
                "left_leg_angle": (
                    round(self.smoothed_leg_angle["left"], 1)
                    if self.smoothed_leg_angle["left"] is not None
                    else None
                ),
                "right_leg_angle": (
                    round(self.smoothed_leg_angle["right"], 1)
                    if self.smoothed_leg_angle["right"] is not None
                    else None
                ),
                "active_side": active_side,
                "phase": phase,
                "stage": phase,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "not_counted_incomplete": self.not_counted_incomplete,
                "session_complete": self._is_complete(),
                "rep_completed": bool(completed),
                "rep_duration": completed["rep_duration"] if completed else None,
                "rep_avg_speed": completed["rep_avg_speed"] if completed else None,
                "rep_classification": (
                    completed["rep_classification"] if completed else None
                ),
                "rep_form_quality": (
                    completed["rep_form_quality"] if completed else None
                ),
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


class DeadBugSession:
    """Full dead bug session: one shared pose model + one analyzer."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = DeadBugAnalyzer(target_reps)
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
            result["session_complete"]
            and self.set_number >= self.target_sets
            and self.analyzer.target_reps is not None
        )
        return result

    def close(self):
        self.engine.close()
