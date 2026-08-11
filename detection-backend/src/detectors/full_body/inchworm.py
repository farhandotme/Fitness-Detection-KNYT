"""
Production-Grade Inchworm Engine & State Machine Analyzer.

MOVEMENT CYCLE STAGES (Matched to Exercise Physiology):
  1. STAGE "standing"    : Upright standing posture (torso vertical, shoulders high above hips).
  2. STAGE "walking_out" : Hinging at hips, hands on floor moving away from feet.
  3. STAGE "plank"       : Full extension plank position (hands under shoulders, held >= 1.0s).
  4. STAGE "walking_back": Hands walking back towards feet (hips piking up).
  5. RETURN TO "standing": Full standing tall posture reached -> REP COUNTED!
"""

import math
from typing import Any, Optional

try:
    from src.engines.poseEngine import (  # type: ignore
        LEFT_ANKLE,
        LEFT_HIP,
        LEFT_KNEE,
        LEFT_SHOULDER,
        LEFT_WRIST,
        NOSE,
        PoseEngine,
        RIGHT_ANKLE,
        RIGHT_HIP,
        RIGHT_KNEE,
        RIGHT_SHOULDER,
        RIGHT_WRIST,
    )
except ImportError:
    NOSE = 0
    LEFT_SHOULDER, RIGHT_SHOULDER = 11, 12
    LEFT_WRIST, RIGHT_WRIST = 15, 16
    LEFT_HIP, RIGHT_HIP = 23, 24
    LEFT_KNEE, RIGHT_KNEE = 25, 26
    LEFT_ANKLE, RIGHT_ANKLE = 27, 28

    class PoseEngine:
        def detect(self, frame, timestamp_ms: int):
            return None

        @staticmethod
        def landmarks_to_json(landmarks):
            return []

        def close(self):
            pass


# Thresholds & Calibrations
MIN_VISIBILITY = 0.35
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)

MIN_HOLD_SECONDS = 0.8
MAX_ATTEMPT_SECONDS = 30.0

# Scale-invariant multipliers normalized by torso length L_torso
PLANK_EXT_MIN_RATIO = 1.15  # wrst-to-ankle horizontal dx >= 1.15 * L_torso
HINGE_EXT_MAX_RATIO = 0.85  # wrst-to-ankle horizontal dx <= 0.85 * L_torso
STANDING_TORSO_Y_MIN = 0.35  # (y_hip - y_shoulder) >= 0.35 * L_torso (standing upright)
HAND_SHOULDER_ALIGN_MAX = 0.65  # wrst-to-shoulder horizontal offset

HIP_SAG_THRESHOLD = 0.20
HIP_PIKE_THRESHOLD = -0.20

FRAME_MARGIN = 0.02


def _get_x(lm: Any) -> float:
    if lm is None:
        return 0.0
    return (
        float(lm.get("x", 0.0))
        if isinstance(lm, dict)
        else float(getattr(lm, "x", 0.0))
    )


def _get_y(lm: Any) -> float:
    if lm is None:
        return 0.0
    return (
        float(lm.get("y", 0.0))
        if isinstance(lm, dict)
        else float(getattr(lm, "y", 0.0))
    )


def _get_vis(lm: Any) -> float:
    if lm is None:
        return 0.0
    v = (
        lm.get("visibility", 1.0)
        if isinstance(lm, dict)
        else getattr(lm, "visibility", 1.0)
    )
    return float(v) if v is not None else 1.0


def _visible(points: tuple) -> bool:
    return all(p is not None and _get_vis(p) >= MIN_VISIBILITY for p in points)


def _looks_like_person(landmarks) -> bool:
    if not landmarks or len(landmarks) < 12:
        return False
    return (
        sum(
            1
            for i in CORE_LANDMARKS
            if i < len(landmarks) and _get_vis(landmarks[i]) >= 0.5
        )
        >= 3
    )


class InchwormAnalyzer:
    """Stateful Inchworm exercise rep counter and form analyzer."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.stage = "standing"  # "standing", "walking_out", "plank", "walking_back"
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.partial_rep_count = 0

        self.session_start_time: Optional[float] = None
        self._attempt_start_time: Optional[float] = None
        self._plank_start_time: Optional[float] = None

        self._plank_achieved = False
        self._hold_confirmed = False
        self._current_rep_issues: set[str] = set()

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "position_ok": False,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "partial_rep_count": self.partial_rep_count,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_duration": None,
            "rep_hold_duration": None,
            "rep_form_quality": None,
            "hold_progress": 0.0,
            "hold_elapsed": 0.0,
            "hold_confirmed": self._hold_confirmed,
            "alignment_ok": True,
            "alignment_issue": None,
            "feedback": None,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None or not _looks_like_person(landmarks):
            response["feedback"] = (
                "No person detected — stand in clear view of the camera."
            )
            return response

        response["pose_detected"] = True

        l_sh, r_sh = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_wr, r_wr = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_ank, r_ank = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        # Core point averages
        sh_x, sh_y = (_get_x(l_sh) + _get_x(r_sh)) / 2.0, (
            _get_y(l_sh) + _get_y(r_sh)
        ) / 2.0
        hip_x, hip_y = (_get_x(l_hip) + _get_x(r_hip)) / 2.0, (
            _get_y(l_hip) + _get_y(r_hip)
        ) / 2.0

        # Hand averages (fall back to shoulders if wrists obscured)
        if _visible((l_wr, r_wr)):
            wr_x, wr_y = (_get_x(l_wr) + _get_x(r_wr)) / 2.0, (
                _get_y(l_wr) + _get_y(r_wr)
            ) / 2.0
        elif _visible((l_wr,)):
            wr_x, wr_y = _get_x(l_wr), _get_y(l_wr)
        elif _visible((r_wr,)):
            wr_x, wr_y = _get_x(r_wr), _get_y(r_wr)
        else:
            wr_x, wr_y = sh_x, sh_y

        # Feet averages (fall back to knees if ankles out of frame)
        if _visible((l_ank, r_ank)):
            ank_x, ank_y = (_get_x(l_ank) + _get_x(r_ank)) / 2.0, (
                _get_y(l_ank) + _get_y(r_ank)
            ) / 2.0
        else:
            l_kn, r_kn = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
            ank_x = (_get_x(l_kn) + _get_x(r_kn)) / 2.0
            ank_y = (_get_y(l_kn) + _get_y(r_kn)) / 2.0

        # Scale-invariant normalizer: Torso length L_torso
        torso_len = max(math.hypot(hip_x - sh_x, hip_y - sh_y), 1e-4)

        # 1. Torso vertical drop (standing upright vs horizontal plank)
        torso_vert_gap = (hip_y - sh_y) / torso_len  # Positive when standing upright

        # 2. Horizontal extension (Wrists to Ankles)
        reach_ext = abs(wr_x - ank_x) / torso_len

        # 3. Horizontal wrist-to-shoulder offset
        hand_sh_offset = abs(wr_x - sh_x) / torso_len

        # Posture Check
        is_standing_upright = (
            torso_vert_gap >= STANDING_TORSO_Y_MIN
            and abs(sh_x - ank_x) / torso_len < 0.60
        )
        is_extended_plank = (
            reach_ext >= PLANK_EXT_MIN_RATIO and torso_vert_gap < STANDING_TORSO_Y_MIN
        )

        # Check for stalled rep timeout
        if (
            self._attempt_start_time is not None
            and (t - self._attempt_start_time) > MAX_ATTEMPT_SECONDS
        ):
            self._reset_state()

        # ---------------------------------------------------------------------
        # STATE MACHINE TRANSITIONS
        # ---------------------------------------------------------------------
        rep_completed = False
        rep_duration = None
        rep_hold_duration = None
        rep_quality = None
        feedback = None

        if self.stage == "standing":
            response["position_ok"] = True
            if not is_standing_upright and (
                reach_ext > HINGE_EXT_MAX_RATIO or wr_y > hip_y
            ):
                # Transition: User hinged down and started walking hands out
                self.stage = "walking_out"
                self._attempt_start_time = t
                self._current_rep_issues.clear()
                feedback = "Walking out — keep moving until you reach a full plank."

        elif self.stage == "walking_out":
            if is_extended_plank:
                # Transition: Full Plank reached!
                self.stage = "plank"
                self._plank_achieved = True
                self._plank_start_time = t
                feedback = "Plank reached! Hold steady."
            elif is_standing_upright:
                # User stood back up without reaching plank
                self.stage = "standing"
                self.partial_rep_count += 1
                feedback = "Walk all the way out into a full plank before returning."

        elif self.stage == "plank":
            response["position_ok"] = True
            hold_elapsed = (
                (t - self._plank_start_time) if self._plank_start_time else 0.0
            )
            response["hold_elapsed"] = round(hold_elapsed, 2)
            response["hold_progress"] = min(1.0, hold_elapsed / MIN_HOLD_SECONDS)

            if hold_elapsed >= MIN_HOLD_SECONDS:
                self._hold_confirmed = True
                response["hold_confirmed"] = True

            # Alignment Checks in Plank
            alignment_issue = None
            if hand_sh_offset > HAND_SHOULDER_ALIGN_MAX:
                alignment_issue = "hands_not_under_shoulders"
            else:
                # Hip Sag / Pike check
                expected_hip_y = (sh_y + ank_y) / 2.0
                hip_dev = (hip_y - expected_hip_y) / torso_len
                if hip_dev > HIP_SAG_THRESHOLD:
                    alignment_issue = "hip_sag"
                elif hip_dev < HIP_PIKE_THRESHOLD:
                    alignment_issue = "hip_pike"

            if alignment_issue:
                self._current_rep_issues.add(alignment_issue)
                response["alignment_ok"] = False
                response["alignment_issue"] = alignment_issue

            # Transition out of plank (hands start walking back)
            if reach_ext < PLANK_EXT_MIN_RATIO or torso_vert_gap > 0.20:
                self.stage = "walking_back"
                feedback = "Good hold! Walk hands back towards your feet."

        elif self.stage == "walking_back":
            if is_standing_upright:
                # Completed full cycle: Return to standing!
                rep_duration = (
                    (t - self._attempt_start_time) if self._attempt_start_time else 0.0
                )
                rep_hold_duration = (
                    (t - self._plank_start_time) if self._plank_start_time else 0.0
                )

                if self._plank_achieved and self._hold_confirmed:
                    self.rep_count += 1
                    rep_completed = True

                    if not self._current_rep_issues:
                        self.good_reps += 1
                        rep_quality = "good"
                        feedback = f"Great Inchworm! Rep {self.rep_count} completed."
                    else:
                        self.flawed_reps += 1
                        rep_quality = "needs_improvement"
                        issues_str = ", ".join(
                            i.replace("_", " ")
                            for i in sorted(self._current_rep_issues)
                        )
                        feedback = (
                            f"Rep {self.rep_count} counted — watch form ({issues_str})."
                        )
                else:
                    self.partial_rep_count += 1
                    feedback = "Hold the plank position for at least 1 second."

                self._reset_state()

        if feedback is None:
            if self.stage == "standing":
                feedback = "Stand tall, hinge forward, and walk your hands out."
            elif self.stage == "walking_out":
                feedback = "Keep walking hands forward into a full plank."
            elif self.stage == "plank":
                feedback = "Hold core tight and keep body in a straight line."
            elif self.stage == "walking_back":
                feedback = "Walk hands back to feet and stand up tall."

        response.update(
            {
                "stage": self.stage,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "partial_rep_count": self.partial_rep_count,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_duration": round(rep_duration, 2) if rep_duration else None,
                "rep_hold_duration": (
                    round(rep_hold_duration, 2) if rep_hold_duration else None
                ),
                "rep_form_quality": rep_quality,
                "feedback": feedback,
            }
        )
        return response

    def _reset_state(self):
        self.stage = "standing"
        self._attempt_start_time = None
        self._plank_start_time = None
        self._plank_achieved = False
        self._hold_confirmed = False
        self._current_rep_issues.clear()


class InchwormSession:
    """Full Inchworm session manager wrapper."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = InchwormAnalyzer(target_reps)
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
