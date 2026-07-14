

import math
from typing import Any, Optional
from src.engines.poseEngine import (  # type: ignore
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_SHOULDER,
    LEFT_WRIST,
    PoseEngine,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)

# -------------------------------------------------------------------------
# Tunable constants
# -------------------------------------------------------------------------

MIN_LANDMARK_VISIBILITY = 0.5

# Elbow angle (shoulder-elbow-wrist) thresholds that drive the rep state
# machine. These also act as the hysteresis band, so a noisy angle sitting
# near one edge can't flicker the stage back and forth.
DOWN_ANGLE = 160.0  # arm considered fully extended
UP_ANGLE = 50.0  # arm considered fully contracted
MIN_ANGLE_DELTA = 25.0  # total angle travel required for a rep to "count"
MIN_REP_DURATION = 0.25  # seconds — faster than this = uncontrolled/momentum
MAX_REP_DURATION = 10.0  # seconds — slower than this = probably a pause, not a rep

# Posture calibration + thresholds. Deltas are measured against the
# person's own relaxed baseline rather than a fixed number, since "normal"
# elbow/torso angles vary a lot by body type and camera placement.
CALIBRATION_FRAMES = 15
ELBOW_FLARE_DELTA_DEG = 22.0  # allowed increase over personal baseline
ELBOW_FLARE_HARD_MAX_DEG = 55.0  # hard ceiling regardless of calibration
TORSO_LEAN_DELTA_DEG = 12.0
SHOULDER_SHRUG_RATIO = 0.08  # fraction of torso length the shoulder may rise

PARTIAL_REP_MARGIN_DEG = 15.0
PARTIAL_REP_MIN_DESCENT_DEG = 20.0
PARTIAL_REP_BOUNCE_DEG = 8.0

JOINTS = {
    "left": {
        "shoulder": LEFT_SHOULDER,
        "elbow": LEFT_ELBOW,
        "wrist": LEFT_WRIST,
        "hip": LEFT_HIP,
        "opp_shoulder": RIGHT_SHOULDER,
        "opp_hip": RIGHT_HIP,
    },
    "right": {
        "shoulder": RIGHT_SHOULDER,
        "elbow": RIGHT_ELBOW,
        "wrist": RIGHT_WRIST,
        "hip": RIGHT_HIP,
        "opp_shoulder": LEFT_SHOULDER,
        "opp_hip": LEFT_HIP,
    },
}


class _Point:
    __slots__ = ("x", "y")

    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y


def _midpoint(a, b) -> _Point:
    return _Point((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)


def _visible(points) -> bool:
    for p in points:
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


class ArmCurlAnalyzer:
    """Stateful bicep-curl rep counter + posture checker for ONE arm."""

    def __init__(self, side: str, target_reps: Optional[int] = None):
        if side not in ("left", "right"):
            raise ValueError("side must be 'left' or 'right'")

        self.side = side
        cfg = JOINTS[side]
        self.shoulder_idx = cfg["shoulder"]
        self.elbow_idx = cfg["elbow"]
        self.wrist_idx = cfg["wrist"]
        self.hip_idx = cfg["hip"]
        self.opp_shoulder_idx = cfg["opp_shoulder"]
        self.opp_hip_idx = cfg["opp_hip"]

        self.target_reps = target_reps

        # Rep state machine
        self.stage = "down"
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

        # "Curl higher" partial-rep detection
        self._attempt_min_angle: Optional[float] = None
        self._attempt_flagged = False

        # Personal posture baseline, captured at rest
        self._calib_samples: list[tuple[float, float, float, float]] = []
        self.calibrated = False
        self._baseline_elbow_flare = 0.0
        self._baseline_torso_lean = 0.0
        self._baseline_shoulder_offset = 0.0
        self._baseline_torso_length = 1.0

        self._current_rep_issues: set[str] = set()

    # ---------------------------------------------------------------
    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 2.5:
            return "too_slow"
        if duration >= 1.5:
            return "slow"
        if duration >= 0.8:
            return "good"
        if duration >= 0.4:
            return "fast"
        return "too_fast"

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _finish_calibration(self):
        n = len(self._calib_samples)
        self._baseline_elbow_flare = sum(s[0] for s in self._calib_samples) / n
        self._baseline_torso_lean = sum(s[1] for s in self._calib_samples) / n
        self._baseline_shoulder_offset = sum(s[2] for s in self._calib_samples) / n
        self._baseline_torso_length = max(
            sum(s[3] for s in self._calib_samples) / n, 1e-6
        )
        self.calibrated = True

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "side": self.side,
            "pose_detected": False,
            "angle": None,
            "smoothed_angle": None,
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
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None:
            response["feedback"] = "No person detected — step into frame."
            return response

        shoulder = landmarks[self.shoulder_idx]
        elbow = landmarks[self.elbow_idx]
        wrist = landmarks[self.wrist_idx]
        hip = landmarks[self.hip_idx]
        opp_shoulder = landmarks[self.opp_shoulder_idx]
        opp_hip = landmarks[self.opp_hip_idx]

        if not _visible((shoulder, elbow, wrist)):
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["angle"] = self.last_angle
            response["smoothed_angle"] = self.smoothed_angle
            response["feedback"] = (
                f"Can't see your {self.side} arm clearly — adjust your position."
            )
            return response

        torso_visible = _visible((hip, opp_shoulder, opp_hip))

        # ---- elbow angle (drives rep counting) ----
        raw_angle = _angle_deg(shoulder, elbow, wrist)
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

        # ---- posture metrics + calibration ----
        elbow_flare = torso_lean = shoulder_offset = torso_length = None
        if torso_visible:
            elbow_flare = _angle_deg(hip, shoulder, elbow)

            mid_shoulder = _midpoint(shoulder, opp_shoulder)
            mid_hip = _midpoint(hip, opp_hip)
            vertical_ref = _Point(mid_hip.x, mid_hip.y - 1.0)
            torso_lean = _angle_deg(vertical_ref, mid_hip, mid_shoulder)

            torso_length = math.hypot(shoulder.x - hip.x, shoulder.y - hip.y) or 1e-6
            shoulder_offset = hip.y - shoulder.y  # positive: shoulder above hip

            if self.stage == "down" and not self.calibrated:
                self._calib_samples.append(
                    (elbow_flare, torso_lean, shoulder_offset, torso_length)
                )
                if len(self._calib_samples) >= CALIBRATION_FRAMES:
                    self._finish_calibration()

        issues: list[str] = []
        messages: list[str] = []
        if self.calibrated and torso_visible:
            if (
                elbow_flare - self._baseline_elbow_flare > ELBOW_FLARE_DELTA_DEG
                or elbow_flare > ELBOW_FLARE_HARD_MAX_DEG
            ):
                issues.append("elbow_flare")
                messages.append(
                    f"Pin your {self.side} elbow to your side — it's drifting away from your body."
                )

            if abs(torso_lean - self._baseline_torso_lean) > TORSO_LEAN_DELTA_DEG:
                issues.append("torso_sway")
                messages.append(
                    "Keep your torso steady — don't swing your body for momentum."
                )

            normalized_shrug = (
                shoulder_offset - self._baseline_shoulder_offset
            ) / self._baseline_torso_length
            if normalized_shrug > SHOULDER_SHRUG_RATIO:
                issues.append("shoulder_shrug")
                messages.append(
                    f"Relax your {self.side} shoulder — don't shrug it toward your ear."
                )

        # ---- "curl higher" partial-rep coaching (pre-transition stage) ----
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
                    f"Curl higher — you stopped around {self._attempt_min_angle:.0f}°, "
                    f"aim for {UP_ANGLE:.0f}° or less at the top."
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
        feedback = partial_feedback

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
                            f"Good form, nice and controlled ({rep_duration:.2f}s)."
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

        response.update(
            {
                "pose_detected": True,
                "angle": raw_angle,
                "smoothed_angle": self.smoothed_angle,
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
                "feedback": feedback,
            }
        )
        return response


class SingleArmCurlSession:
    """Left- or right-arm curl session: one shared pose model + one analyzer."""

    def __init__(self, side: str, target_reps: Optional[int] = None):
        self.engine = PoseEngine()
        self.analyzer = ArmCurlAnalyzer(side, target_reps)

    def detect(self, frame, timestamp_ms: int) -> dict[str, Any]:
        landmarks = self.engine.detect(frame, timestamp_ms)
        result = self.analyzer.update(landmarks, timestamp_ms)
        result["landmarks"] = (
            PoseEngine.landmarks_to_json(landmarks) if landmarks else []
        )
        return result

    def close(self):
        self.engine.close()


class BothArmCurlSession:
    """Both-arm curl session: one shared pose model, two analyzers.

    The combined rep count is `min(left, right)` so an arm that lags behind
    can't inflate the count, and live feedback tells the person which arm
    needs to catch up if they drift out of sync.
    """

    def __init__(self, target_reps: Optional[int] = None):
        self.engine = PoseEngine()
        self.left = ArmCurlAnalyzer("left", target_reps)
        self.right = ArmCurlAnalyzer("right", target_reps)
        self.target_reps = target_reps

        self.combined_rep_count = 0
        self.combined_good_reps = 0
        self.combined_flawed_reps = 0
        self._last_left_quality: Optional[str] = None
        self._last_right_quality: Optional[str] = None

    def detect(self, frame, timestamp_ms: int) -> dict[str, Any]:
        landmarks = self.engine.detect(frame, timestamp_ms)
        left_result = self.left.update(landmarks, timestamp_ms)
        right_result = self.right.update(landmarks, timestamp_ms)

        if left_result.get("rep_form_quality"):
            self._last_left_quality = left_result["rep_form_quality"]
        if right_result.get("rep_form_quality"):
            self._last_right_quality = right_result["rep_form_quality"]

        new_count = min(left_result["rep_count"], right_result["rep_count"])
        newly_completed = new_count > self.combined_rep_count
        if newly_completed:
            self.combined_rep_count = new_count
            if "needs_improvement" in (
                self._last_left_quality,
                self._last_right_quality,
            ):
                self.combined_flawed_reps += 1
            else:
                self.combined_good_reps += 1

        rep_diff = left_result["rep_count"] - right_result["rep_count"]
        sync_ok = abs(rep_diff) <= 1

        if not sync_ok:
            lagging = "right" if rep_diff > 0 else "left"
            feedback = (
                f"Move both arms together — your {lagging} arm is falling behind."
            )
        elif newly_completed:
            feedback = f"Nice, synced rep #{self.combined_rep_count} on both arms!"
        else:
            feedback = left_result.get("feedback") or right_result.get("feedback")

        session_complete = (
            self.target_reps is not None and self.combined_rep_count >= self.target_reps
        )

        landmarks_json = PoseEngine.landmarks_to_json(landmarks) if landmarks else []

        return {
            "pose_detected": left_result["pose_detected"]
            or right_result["pose_detected"],
            "left_arm": left_result,
            "right_arm": right_result,
            "stage": self._combined_stage(left_result["stage"], right_result["stage"]),
            "rep_count": self.combined_rep_count,
            "good_reps": self.combined_good_reps,
            "flawed_reps": self.combined_flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": session_complete,
            "rep_completed": newly_completed,
            "sync_ok": sync_ok,
            "feedback": feedback,
            "elapsed_time": max(
                left_result["elapsed_time"], right_result["elapsed_time"]
            ),
            "landmarks": landmarks_json,
        }

    @staticmethod
    def _combined_stage(left_stage: str, right_stage: str) -> str:
        if left_stage == "up" and right_stage == "up":
            return "up"
        if left_stage == "down" and right_stage == "down":
            return "down"
        return "mixed"

    def close(self):
        self.engine.close()
