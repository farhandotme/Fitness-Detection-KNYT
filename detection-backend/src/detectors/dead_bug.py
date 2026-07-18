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

MIN_VIS = 0.15

CORE_LANDMARKS = (
    LEFT_SHOULDER,
    RIGHT_SHOULDER,
    LEFT_HIP,
    RIGHT_HIP,
)


class _Pt:
    __slots__ = ("x", "y", "v")

    def __init__(self, x: float, y: float, v: Optional[float] = None):
        self.x = x
        self.y = y
        self.v = v


def _mid(a: _Pt, b: _Pt) -> _Pt:
    return _Pt((a.x + b.x) * 0.5, (a.y + b.y) * 0.5)


def _visible(p: Optional[_Pt]) -> bool:
    return p is not None and (p.v is None or p.v >= MIN_VIS)


def _ang(a: _Pt, b: _Pt, c: _Pt) -> float:
    """Angle at b (degrees)."""
    ang = math.degrees(
        math.atan2(c.y - b.y, c.x - b.x) - math.atan2(a.y - b.y, a.x - b.x)
    )
    ang = abs(ang)
    if ang > 180.0:
        ang = 360.0 - ang
    return ang


def _dist(a: _Pt, b: _Pt) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _wrap_landmarks(lm_list):
    out = {}
    for i, lm in enumerate(lm_list):
        v = getattr(lm, "visibility", None)
        out[i] = _Pt(lm.x, lm.y, v)
    return out


class DeadBugAnalyzer:
    """
    Minimal dead-bug counter:
      - Side = right_arm_left_leg or left_arm_right_leg
      - State: "start" (tabletop) -> "extend" -> "start"
      - Uses global arm/leg orientation relative to torso instead of just elbow/knee angles.
    """

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.stage = {
            "right_arm_left_leg": "start",
            "left_arm_right_leg": "start",
        }
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.not_counted_incomplete = 0

        self.session_start_time: Optional[float] = None

        # Per-side timing
        self.rep_start_time: dict[str, Optional[float]] = {
            "right_arm_left_leg": None,
            "left_arm_right_leg": None,
        }

        # Simple smoothing
        self._prev_arm_orient: dict[str, Optional[float]] = {
            "right": None,
            "left": None,
        }
        self._prev_leg_orient: dict[str, Optional[float]] = {
            "right": None,
            "left": None,
        }
        self.orient_smooth = 0.5

        # Very simple ROM tracking
        self._rep_max_arm_ext: dict[str, float] = {"right": 0.0, "left": 0.0}
        self._rep_max_leg_ext: dict[str, float] = {"right": 0.0, "left": 0.0}

        # Baselines (optional, can be defaulted)
        self.calibrated = False
        self._baseline_arm_orient: dict[str, float] = {"right": 0.0, "left": 0.0}
        self._baseline_leg_orient: dict[str, float] = {"right": 0.0, "left": 0.0}

        # Calibration samples
        self._calib_arm: dict[str, list[float]] = {"right": [], "left": []}
        self._calib_leg: dict[str, list[float]] = {"right": [], "left": []}
        self._calib_count = 0

        # Thresholds (will be tuned once we see real numbers)
        self.ARM_EXT_THRESH = 0.35  # normalized extension
        self.LEG_EXT_THRESH = 0.35

        self.MIN_REP_DURATION = 0.8
        self.MAX_REP_DURATION = 10.0

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _torso_axis(self, l_sh, r_sh, l_hip, r_hip):
        """Return (mid_shoulder, mid_hip, torso_vector)."""
        ms = _mid(l_sh, r_sh)
        mh = _mid(l_hip, r_hip)
        vec = _Pt(ms.x - mh.x, ms.y - mh.y)
        length = max(_dist(ms, mh), 1e-6)
        vec = _Pt(vec.x / length, vec.y / length)
        return ms, mh, vec

    def _arm_extension(self, shoulder: _Pt, wrist: _Pt, torso_vec: _Pt) -> float:
        """
        Returns a normalized 'extension' score:
          ~0 = arm by side / neutral
          ~1 = arm fully overhead (aligned with torso axis).
        """
        arm_vec = _Pt(wrist.x - shoulder.x, wrist.y - shoulder.y)
        arm_len = max(_dist(wrist, shoulder), 1e-6)
        arm_vec = _Pt(arm_vec.x / arm_len, arm_vec.y / arm_len)

        # Dot product with torso axis
        dot = arm_vec.x * torso_vec.x + arm_vec.y * torso_vec.y
        # Map [-1, 1] -> [0, 1]
        return (dot + 1.0) * 0.5

    def _leg_extension(self, hip: _Pt, knee: _Pt, ankle: _Pt, torso_vec: _Pt) -> float:
        """
        Normalized leg extension:
          ~0 = knee tucked (tabletop)
          ~1 = leg extended toward floor.
        Uses hip->ankle orientation relative to torso.
        """
        ankle_vec = _Pt(ankle.x - hip.x, ankle.y - hip.y)
        ankle_len = max(_dist(ankle, hip), 1e-6)
        ankle_vec = _Pt(ankle_vec.x / ankle_len, ankle_vec.y / ankle_len)

        dot = ankle_vec.x * torso_vec.x + ankle_vec.y * torso_vec.y
        return (dot + 1.0) * 0.5

    def _maybe_calibrate(
        self,
        l_sh,
        r_sh,
        l_hip,
        r_hip,
        l_el,
        r_el,
        l_wr,
        r_wr,
        l_knee,
        r_knee,
        l_ankle,
        r_ankle,
        torso_vec,
    ):
        """Collect a few samples in 'start' pose to set baselines."""
        if self.calibrated:
            return

        # Only calibrate when both sides are in "start"
        if (
            self.stage["right_arm_left_leg"] != "start"
            or self.stage["left_arm_right_leg"] != "start"
        ):
            return

        # Compute arm/leg orientations
        r_arm_ext = self._arm_extension(r_sh, r_wr, torso_vec)
        l_arm_ext = self._arm_extension(l_sh, l_wr, torso_vec)

        r_leg_ext = self._leg_extension(r_hip, r_knee, r_ankle, torso_vec)
        l_leg_ext = self._leg_extension(l_hip, l_knee, l_ankle, torso_vec)

        self._calib_arm["right"].append(r_arm_ext)
        self._calib_arm["left"].append(l_arm_ext)
        self._calib_leg["right"].append(r_leg_ext)
        self._calib_leg["left"].append(l_leg_ext)
        self._calib_count += 1

        if self._calib_count >= 10:
            for side in ("right", "left"):
                arr_arm = self._calib_arm[side]
                arr_leg = self._calib_leg[side]
                if arr_arm:
                    self._baseline_arm_orient[side] = sum(arr_arm) / len(arr_arm)
                if arr_leg:
                    self._baseline_leg_orient[side] = sum(arr_leg) / len(arr_leg)
            self.calibrated = True

    def _update_side(
        self,
        side_name: str,
        arm_side: str,
        leg_side: str,
        arm_ext: float,
        leg_ext: float,
        t: float,
    ) -> Optional[dict]:
        """Simple state machine for one contralateral pair."""

        # Smooth orientations
        prev_arm = self._prev_arm_orient[arm_side]
        if prev_arm is None:
            prev_arm = arm_ext
        smooth_arm = self.orient_smooth * arm_ext + (1 - self.orient_smooth) * prev_arm
        self._prev_arm_orient[arm_side] = smooth_arm

        prev_leg = self._prev_leg_orient[leg_side]
        if prev_leg is None:
            prev_leg = leg_ext
        smooth_leg = self.orient_smooth * leg_ext + (1 - self.orient_smooth) * prev_leg
        self._prev_leg_orient[leg_side] = smooth_leg

        base_arm = self._baseline_arm_orient[arm_side]
        base_leg = self._baseline_leg_orient[leg_side]

        # Normalized extension relative to baseline
        arm_excess = max(0.0, smooth_arm - base_arm)
        leg_excess = max(0.0, smooth_leg - base_leg)

        outcome: dict[str, Any] = {
            "rep_completed": False,
            "counted": False,
            "rep_duration": None,
            "rep_avg_speed": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "issues": set(),
            "feedback": None,
            "arm_ext": smooth_arm,
            "leg_ext": smooth_leg,
        }

        stage = self.stage[side_name]
        rep_completed = False

        # Simple threshold-based extension detection
        arm_extended = arm_excess > self.ARM_EXT_THRESH
        leg_extended = leg_excess > self.LEG_EXT_THRESH

        if stage == "start":
            if arm_extended and leg_extended:
                self.stage[side_name] = "extend"
                self.rep_start_time[side_name] = t
                self._rep_max_arm_ext[arm_side] = arm_excess
                self._rep_max_leg_ext[leg_side] = leg_excess
        elif stage == "extend":
            # Track max extension
            self._rep_max_arm_ext[arm_side] = max(
                self._rep_max_arm_ext[arm_side], arm_excess
            )
            self._rep_max_leg_ext[leg_side] = max(
                self._rep_max_leg_ext[leg_side], leg_excess
            )

            # Return to start when both are no longer extended
            if not arm_extended and not leg_extended:
                self.stage[side_name] = "start"
                rep_completed = True

        if rep_completed:
            rep_duration = (
                (t - self.rep_start_time[side_name])
                if self.rep_start_time[side_name] is not None
                else None
            )

            motion_valid = (
                rep_duration is not None
                and self.MIN_REP_DURATION <= rep_duration <= self.MAX_REP_DURATION
            )

            arm_rom = self._rep_max_arm_ext[arm_side]
            leg_rom = self._rep_max_leg_ext[leg_side]

            rom_ok = (
                arm_rom >= self.ARM_EXT_THRESH * 0.6
                and leg_rom >= self.LEG_EXT_THRESH * 0.6
            )

            if not motion_valid:
                if rep_duration is not None and rep_duration < self.MIN_REP_DURATION:
                    outcome["feedback"] = (
                        "Too fast — keep it slow and controlled. Not counted."
                    )
                elif rep_duration is not None and rep_duration > self.MAX_REP_DURATION:
                    outcome["feedback"] = (
                        "That took too long — not counted. Move with purpose."
                    )
                else:
                    outcome["feedback"] = "Movement not clear enough — not counted."
            elif not rom_ok:
                self.not_counted_incomplete += 1
                outcome["feedback"] = (
                    "Extend your arm and leg more — that rep was too shallow, not counted."
                )
            else:
                self.rep_count += 1
                outcome["counted"] = True
                outcome["rep_completed"] = True
                outcome["rep_duration"] = round(rep_duration, 2)

                # Very coarse tempo classification
                if rep_duration >= 3.0:
                    cls = "slow"
                elif rep_duration >= 1.5:
                    cls = "good"
                else:
                    cls = "fast"

                outcome["rep_classification"] = cls
                outcome["rep_form_quality"] = "good"
                self.good_reps += 1
                outcome["feedback"] = f"Clean dead bug ({rep_duration:.2f}s, {cls})."

            # Reset per-rep
            self.rep_start_time[side_name] = None
            self._rep_max_arm_ext[arm_side] = 0.0
            self._rep_max_leg_ext[leg_side] = 0.0

        return outcome

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
            "active_side": None,
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
            "_debug": {},
        }

        if landmarks is None:
            response["feedback"] = (
                "No person detected — lie on your back with full body in frame."
            )
            return response

        # Wrap landmarks
        lm = _wrap_landmarks(landmarks)

        l_sh, r_sh = lm[LEFT_SHOULDER], lm[RIGHT_SHOULDER]
        l_el, r_el = lm[LEFT_ELBOW], lm[RIGHT_ELBOW]
        l_wr, r_wr = lm[LEFT_WRIST], lm[RIGHT_WRIST]
        l_hip_pt, r_hip_pt = lm[LEFT_HIP], lm[RIGHT_HIP]
        l_knee, r_knee = lm[LEFT_KNEE], lm[RIGHT_KNEE]
        l_ankle, r_ankle = lm[LEFT_ANKLE], lm[RIGHT_ANKLE]
        nose = lm[NOSE]

        # Basic visibility: just need torso+head and at least one arm+leg pair
        torso_ok = (
            _visible(l_sh)
            and _visible(r_sh)
            and _visible(l_hip_pt)
            and _visible(r_hip_pt)
        )
        head_ok = nose is not None and (nose.v is None or nose.v >= MIN_VIS)

        if not torso_ok or not head_ok:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your upper body and head clearly — lie on your back with your whole torso and head in frame."
            )
            return response

        # Compute torso axis
        ms, mh, torso_vec = self._torso_axis(l_sh, r_sh, l_hip_pt, r_hip_pt)

        # Try calibrate first
        self._maybe_calibrate(
            l_sh,
            r_sh,
            l_hip_pt,
            r_hip_pt,
            l_el,
            r_el,
            l_wr,
            r_wr,
            l_knee,
            r_knee,
            l_ankle,
            r_ankle,
            torso_vec,
        )

        # Compute arm/leg extensions per side
        # Right arm + left leg
        r_arm_ext = (
            self._arm_extension(r_sh, r_wr, torso_vec)
            if _visible(r_sh) and _visible(r_wr)
            else None
        )
        l_leg_ext = (
            self._leg_extension(l_hip_pt, l_knee, l_ankle, torso_vec)
            if _visible(l_hip_pt) and _visible(l_ankle)
            else None
        )

        # Left arm + right leg
        l_arm_ext = (
            self._arm_extension(l_sh, l_wr, torso_vec)
            if _visible(l_sh) and _visible(l_wr)
            else None
        )
        r_leg_ext = (
            self._leg_extension(r_hip_pt, r_knee, r_ankle, torso_vec)
            if _visible(r_hip_pt) and _visible(r_ankle)
            else None
        )

        # Fallback: if one side is missing data, skip that side this frame
        right_outcome = None
        left_outcome = None

        if r_arm_ext is not None and l_leg_ext is not None:
            right_outcome = self._update_side(
                "right_arm_left_leg",
                "right",
                "left",
                r_arm_ext,
                l_leg_ext,
                t,
            )

        if l_arm_ext is not None and r_leg_ext is not None:
            left_outcome = self._update_side(
                "left_arm_right_leg",
                "left",
                "right",
                l_arm_ext,
                r_leg_ext,
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

        feedback = None
        if completed and completed["feedback"]:
            feedback = completed["feedback"]
        if feedback is None and not self.calibrated:
            feedback = "Hold your start position still — calibrating your baseline."
        if feedback is None:
            feedback = "Good dead bug position — move slowly and keep your core tight."

        response.update(
            {
                "pose_detected": True,
                # For now, we still expose dummy "angles" for UI compatibility
                "left_arm_angle": (
                    round(l_arm_ext, 2) if l_arm_ext is not None else None
                ),
                "right_arm_angle": (
                    round(r_arm_ext, 2) if r_arm_ext is not None else None
                ),
                "left_leg_angle": (
                    round(l_leg_ext, 2) if l_leg_ext is not None else None
                ),
                "right_leg_angle": (
                    round(r_leg_ext, 2) if r_leg_ext is not None else None
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
                "posture_ok": True,
                "posture_issues": [],
                "posture_messages": [],
                "framing_ok": True,
                "framing_message": None,
                "feedback": feedback,
                "_debug": {
                    "r_arm_ext": r_arm_ext,
                    "l_arm_ext": l_arm_ext,
                    "r_leg_ext": r_leg_ext,
                    "l_leg_ext": l_leg_ext,
                    "stage": dict(self.stage),
                },
            }
        )
        return response


class DeadBugSession:
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
