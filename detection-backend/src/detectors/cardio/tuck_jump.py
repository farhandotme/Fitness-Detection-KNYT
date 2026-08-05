"""
Tuck Jump detector.

A tuck jump is a REP exercise (not a hold/timer exercise): stand tall (Position
A in the reference image), explosively jump straight up while driving both
knees up toward the chest (Position B), then land back on both feet with legs
extended, ready for the next rep.

For a rep to count, the backend requires BOTH of the following to have
genuinely happened during the same continuous attempt — not just one of them:

  1. The person actually left the ground (a real vertical jump, measured as
     hip-height rise relative to a calibrated standing baseline, normalized
     by leg length so it works regardless of how close/far the camera is).
  2. Both knees were actually pulled up toward the torso while airborne
     (measured via knee angle AND hip-flexion angle, so a jump with straight
     legs — or knees raised while still standing on the ground, like a high
     knee — does not count).

Landing back in a standing position (legs re-extended) closes out the rep.
Architecture/state-machine conventions (smoothed angle + hysteresis-band
stage machine, attempt-extremes tracking, rep-duration validity window,
framing checks, `ready`/calibration gating, session/set-completion contract)
intentionally mirror `pushup.py` so this detector, its route, and its
frontend hook behave the same way every other exercise in this app does.
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
)

# -------------------------------------------------------------------------
# Tunable constants
# -------------------------------------------------------------------------

MIN_LANDMARK_VISIBILITY = 0.4
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)

# "tuck_angle" = average of (knee angle, hip-flexion angle). High (~170-180)
# when standing straight; drops as the knees are actively pulled up toward
# the chest. This one number drives the rep state machine, same role
# `smoothed_angle` (elbow angle) plays in pushup.py.
#
# IMPORTANT — why this is angle-based, not distance-based: "knees touch the
# chest" is a body-CONTACT description, but MediaPipe landmarks are single
# points with no width/volume, and a knee landmark can never actually reach
# a chest landmark (the thigh and torso are what touch — the joints stay a
# thigh's length apart even at maximum tuck). Gating on point-to-point
# distance would therefore never fire, no matter how good the rep is. Angle
# is the correct, anatomically-honest proxy: at true max tuck a real
# person's knee angle and hip-flexion angle both bottom out somewhere
# around 60-100 depending on flexibility/camera angle — they don't need to
# hit some artificially extreme number for a perfectly good rep to count.
DOWN_ANGLE = 150.0  # standing / rest (top) — legs extended
UP_ANGLE = 135.0  # tucked (bottom of the "angle") — crossing this starts a rep attempt
TUCK_ANGLE_MAX = 140.0  # peak tuck must reach at least this to count — deliberately
# a little looser than UP_ANGLE so a real, fast tuck (measured from the RAW
# per-frame angle, not the lagged smoothed one — see `_attempt_min_tuck_angle`
# below) is never missed just because it only held its lowest point for 1-2 frames.
ANGLE_SMOOTH_ALPHA = 0.75  # responsive — a tuck jump is fast (~0.3-0.5s total)

# Jump-height gate — hip rise relative to calibrated standing baseline,
# normalized by the person's own (calibrated) leg length. This is what
# stops a standing high-knee raise (knees come up, feet stay planted) from
# being mistaken for a tuck jump — that move fails this check because the
# hips never actually rise off the calibrated baseline.
JUMP_MIN_RISE = 0.08
GOOD_JUMP_RISE = 0.16  # softer "great height" bonus — quality only, never gates
RISE_SMOOTH_ALPHA = 0.75  # responsive, matches ANGLE_SMOOTH_ALPHA — a jump is brief

MIN_REP_DURATION = 0.14  # seconds — faster than this is sensor noise, not a rep.
# Deliberately low: an explosive tuck jump can genuinely spend well under a
# quarter-second with the knees up near the chest, and rejecting those was
# throwing away real, well-executed reps.
MAX_REP_DURATION = 2.0  # seconds — slower than this means they paused, not jumped

# Soft, non-gating form checks (affect rep_form_quality only, never whether
# the rep counts).
ASYMMETRY_DEG_THRESHOLD = 25.0  # |left knee angle - right knee angle| at peak
TORSO_LEAN_ALERT_DEG = 45.0  # torso incline dropping below this while airborne

# -------------------------------------------------------------------------
# Standing calibration (this is the `ready`/floor-position equivalent).
# Unlike push-ups, the *correct* airborne pose looks nothing like the
# calibration pose — so once calibrated, `ready` stays sticky and is only
# ever dropped if tracking is actually lost (person leaves frame, bad
# framing) for a sustained period, never just because they're mid-jump.
# -------------------------------------------------------------------------
STANDING_ANGLE_MIN = 160.0
TORSO_UPRIGHT_MIN_DEG = 60.0
STABLE_STANDING_FRAMES = 5
LOST_GRACE_FRAMES = 20
BASELINE_EMA_ALPHA = 0.03  # slow adaptive refresh of the standing baseline

# Camera framing
FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.95
BBOX_TOO_FAR = 0.15


class _Point:
    __slots__ = ("x", "y")

    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y


def _visible(points) -> bool:
    for p in points:
        if p is None:
            return False
        v = getattr(p, "visibility", None)
        if v is not None and v < MIN_LANDMARK_VISIBILITY:
            return False
    return True


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 3


def _pair_mid(a, b) -> Optional[_Point]:
    """Midpoint of both sides if both are visible; falls back to whichever
    single side is visible (camera angle or partial occlusion tolerant),
    same fallback convention as pushup.py's `_leg_far_point`."""
    a_ok, b_ok = _visible((a,)), _visible((b,))
    if a_ok and b_ok:
        return _Point((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)
    if a_ok:
        return _Point(a.x, a.y)
    if b_ok:
        return _Point(b.x, b.y)
    return None


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


def _torso_incline_deg(mid_shoulder, mid_hip) -> Optional[float]:
    """~90 = perfectly vertical torso (standing tall), ~0 = horizontal."""
    dx = mid_hip.x - mid_shoulder.x
    dy = mid_hip.y - mid_shoulder.y
    if dx == 0 and dy == 0:
        return None
    return math.degrees(math.atan2(abs(dy), max(abs(dx), 1e-9)))


def _bbox_aspect(points: list[_Point]) -> Optional[float]:
    if len(points) < 4:
        return None
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    height = max(ys) - min(ys)
    if height <= 1e-6:
        return None
    return (max(xs) - min(xs)) / height


def _framing_feedback(points: list[_Point]) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — reposition so your whole body is visible."
            )

    if len(points) < 4:
        return None

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "You're too close to the camera — back up so your whole body fits in frame, with room above your head to jump."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class TuckJumpAnalyzer:
    """Stateful tuck-jump rep counter with a sticky standing calibration
    gate (rather than a per-frame position gate, since the correct in-air
    pose intentionally does NOT look like the calibration pose)."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        # Rep state machine. "down" = standing/landed (top), "up" = tucked
        # mid-air (bottom) — same hysteresis-band naming convention as
        # pushup.py, just applied to tuck_angle instead of elbow angle.
        self.stage = "down"
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.no_jump_count = 0  # knees tucked but never left the ground
        self.no_tuck_count = 0  # jumped but didn't tuck the knees up

        self.smoothed_tuck_angle: Optional[float] = None
        self.smoothed_hip_rise: Optional[float] = None
        self.last_angle: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None
        self.rep_start_time: Optional[float] = None

        self.session_start_time: Optional[float] = None

        # Standing calibration (the `ready` gate)
        self._standing_streak = 0
        self._lost_streak = 0
        self.ready = False
        self.baseline_hip_y: Optional[float] = None
        self.baseline_leg_length: Optional[float] = None

        # Per-attempt extremes, captured while stage == "up"
        self._attempt_min_tuck_angle: Optional[float] = None
        self._attempt_max_hip_rise: float = 0.0
        self._attempt_min_left_knee: Optional[float] = None
        self._attempt_min_right_knee: Optional[float] = None
        self._attempt_min_torso_incline: Optional[float] = None

    # ---------------------------------------------------------------
    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 1.4:
            return "too_slow"
        if duration >= 0.9:
            return "slow"
        if duration >= 0.4:
            return "good"
        if duration >= 0.22:
            return "fast"
        return "too_fast"

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _reset_attempt(self):
        self._attempt_min_tuck_angle = None
        self._attempt_max_hip_rise = 0.0
        self._attempt_min_left_knee = None
        self._attempt_min_right_knee = None
        self._attempt_min_torso_incline = None

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "ready": self.ready,
            "calibration_progress": min(
                1.0, self._standing_streak / STABLE_STANDING_FRAMES
            ),
            "airborne": False,
            "tuck_angle": None,
            "smoothed_tuck_angle": None,
            "left_knee_angle": None,
            "right_knee_angle": None,
            "hip_rise": None,
            "angle_velocity": None,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "no_jump_count": self.no_jump_count,
            "no_tuck_count": self.no_tuck_count,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_duration": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "alignment_ok": True,
            "alignment_issue": None,
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            self._lost_streak += 1
            if self._lost_streak >= LOST_GRACE_FRAMES:
                self.ready = False
                self._standing_streak = 0
            response["feedback"] = "No person detected — step into frame."
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
        left_leg_ok = _visible((l_hip, l_knee, l_ankle))
        right_leg_ok = _visible((r_hip, r_knee, r_ankle))

        if not torso_visible or (not left_leg_ok and not right_leg_ok):
            self._lost_streak += 1
            if self._lost_streak >= LOST_GRACE_FRAMES:
                self.ready = False
                self._standing_streak = 0
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your whole body — make sure your shoulders, "
                "hips, knees and ankles are all in frame."
            )
            return response

        response["pose_detected"] = True
        self._lost_streak = 0

        mid_shoulder = _pair_mid(l_shoulder, r_shoulder)
        mid_hip = _pair_mid(l_hip, r_hip)
        mid_knee = _pair_mid(l_knee, r_knee)
        mid_ankle = _pair_mid(l_ankle, r_ankle)

        # ---- camera framing ----
        bbox_points = [
            _Point(p.x, p.y)
            for p in (
                l_shoulder,
                r_shoulder,
                l_hip,
                r_hip,
                l_knee,
                r_knee,
                l_ankle,
                r_ankle,
            )
            if _visible((p,))
        ]
        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        # ---- per-leg knee angle (hip-knee-ankle) and hip-flexion angle
        # (shoulder-hip-knee) — averaged into `tuck_angle`, the single
        # number that drives the rep state machine. High = legs extended
        # and in line with the torso (standing). Low = knees driven up
        # toward the chest (tucked). ----
        left_knee_angle = _angle_deg(l_hip, l_knee, l_ankle) if left_leg_ok else None
        right_knee_angle = _angle_deg(r_hip, r_knee, r_ankle) if right_leg_ok else None
        left_hip_flex = _angle_deg(l_shoulder, l_hip, l_knee) if left_leg_ok else None
        right_hip_flex = _angle_deg(r_shoulder, r_hip, r_knee) if right_leg_ok else None

        knee_angles = [a for a in (left_knee_angle, right_knee_angle) if a is not None]
        hip_flex_angles = [a for a in (left_hip_flex, right_hip_flex) if a is not None]
        avg_knee_angle = sum(knee_angles) / len(knee_angles)
        avg_hip_flex = (
            sum(hip_flex_angles) / len(hip_flex_angles)
            if hip_flex_angles
            else avg_knee_angle
        )
        raw_tuck_angle = (avg_knee_angle + avg_hip_flex) / 2.0

        torso_incline = (
            _torso_incline_deg(mid_shoulder, mid_hip)
            if (mid_shoulder and mid_hip)
            else None
        )

        # ---- standing calibration (the `ready` gate) ----
        standing_candidate = (
            raw_tuck_angle >= STANDING_ANGLE_MIN
            and torso_incline is not None
            and torso_incline >= TORSO_UPRIGHT_MIN_DEG
            and framing_message is None
        )

        if standing_candidate:
            self._standing_streak += 1
        else:
            self._standing_streak = 0

        leg_length_now = _dist(mid_hip, mid_ankle) if (mid_hip and mid_ankle) else None

        if (
            not self.ready
            and self._standing_streak >= STABLE_STANDING_FRAMES
            and leg_length_now
            and leg_length_now > 1e-4
        ):
            self.ready = True
            self.baseline_hip_y = mid_hip.y
            self.baseline_leg_length = leg_length_now
        elif (
            self.ready
            and standing_candidate
            and self.stage == "down"
            and leg_length_now
            and leg_length_now > 1e-4
        ):
            # Slow adaptive refresh — only while confirmed standing on the
            # ground, never mid-jump, so it can't drift toward an airborne
            # frame becoming the new "floor".
            self.baseline_hip_y = (
                BASELINE_EMA_ALPHA * mid_hip.y
                + (1 - BASELINE_EMA_ALPHA) * self.baseline_hip_y
            )
            self.baseline_leg_length = (
                BASELINE_EMA_ALPHA * leg_length_now
                + (1 - BASELINE_EMA_ALPHA) * self.baseline_leg_length
            )

        response["ready"] = self.ready
        response["calibration_progress"] = min(
            1.0, self._standing_streak / STABLE_STANDING_FRAMES
        )

        # ---- hip rise (jump height), normalized by calibrated leg length ----
        hip_rise = None
        if self.ready and self.baseline_hip_y is not None and self.baseline_leg_length:
            hip_rise = (self.baseline_hip_y - mid_hip.y) / self.baseline_leg_length

        # ---- smoothing ----
        if self.smoothed_tuck_angle is None:
            self.smoothed_tuck_angle = raw_tuck_angle
        else:
            self.smoothed_tuck_angle = (
                ANGLE_SMOOTH_ALPHA * raw_tuck_angle
                + (1 - ANGLE_SMOOTH_ALPHA) * self.smoothed_tuck_angle
            )

        if hip_rise is not None:
            if self.smoothed_hip_rise is None:
                self.smoothed_hip_rise = hip_rise
            else:
                self.smoothed_hip_rise = (
                    RISE_SMOOTH_ALPHA * hip_rise
                    + (1 - RISE_SMOOTH_ALPHA) * self.smoothed_hip_rise
                )

        angle_velocity = None
        if self.last_angle is not None and self.last_timestamp_s is not None:
            dt = t - self.last_timestamp_s
            if dt > 0:
                angle_velocity = (self.smoothed_tuck_angle - self.last_angle) / dt

        response["airborne"] = bool(
            self.ready
            and self.smoothed_hip_rise is not None
            and self.smoothed_hip_rise >= JUMP_MIN_RISE
        )

        feedback = framing_message

        # ---- rep state machine — only ever runs once calibrated ----
        rep_completed = False
        rep_duration = rep_class = rep_form_quality = None

        if not self.ready:
            if feedback is None:
                feedback = (
                    f"Stand tall, feet together, whole body in frame — "
                    f"hold still to calibrate ({self._standing_streak}/{STABLE_STANDING_FRAMES})."
                )
        else:
            if self.stage == "down" and self.smoothed_tuck_angle < UP_ANGLE:
                self.rep_start_time = t
                self.stage = "up"
                self._reset_attempt()
            elif self.stage == "up" and self.smoothed_tuck_angle > DOWN_ANGLE:
                self.stage = "down"
                rep_completed = True

            if self.stage == "up":
                # Peaks are captured from the RAW per-frame angle/rise, not
                # the smoothed ones — a real tuck jump only spends a couple
                # of frames at its actual lowest point, and averaging that
                # against slower neighbouring frames would understate how
                # far the knees really came up. Smoothing is only used to
                # decide the stage transition (so single-frame jitter can't
                # flip stage back and forth); it must never be what decides
                # whether a genuinely good rep counts.
                if (
                    self._attempt_min_tuck_angle is None
                    or raw_tuck_angle < self._attempt_min_tuck_angle
                ):
                    self._attempt_min_tuck_angle = raw_tuck_angle
                if hip_rise is not None:
                    self._attempt_max_hip_rise = max(
                        self._attempt_max_hip_rise, hip_rise
                    )
                if left_knee_angle is not None and (
                    self._attempt_min_left_knee is None
                    or left_knee_angle < self._attempt_min_left_knee
                ):
                    self._attempt_min_left_knee = left_knee_angle
                if right_knee_angle is not None and (
                    self._attempt_min_right_knee is None
                    or right_knee_angle < self._attempt_min_right_knee
                ):
                    self._attempt_min_right_knee = right_knee_angle
                if torso_incline is not None and (
                    self._attempt_min_torso_incline is None
                    or torso_incline < self._attempt_min_torso_incline
                ):
                    self._attempt_min_torso_incline = torso_incline

            if rep_completed:
                rep_duration = (
                    (t - self.rep_start_time)
                    if self.rep_start_time is not None
                    else None
                )

                jumped = self._attempt_max_hip_rise >= JUMP_MIN_RISE
                tucked = (
                    self._attempt_min_tuck_angle is not None
                    and self._attempt_min_tuck_angle <= TUCK_ANGLE_MAX
                )
                duration_ok = (
                    rep_duration is not None
                    and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                )

                valid = jumped and tucked and duration_ok

                if valid:
                    self.rep_count += 1
                    rep_class = self._classify_tempo(rep_duration)

                    issues = set()
                    if (
                        self._attempt_min_left_knee is not None
                        and self._attempt_min_right_knee is not None
                        and abs(
                            self._attempt_min_left_knee - self._attempt_min_right_knee
                        )
                        > ASYMMETRY_DEG_THRESHOLD
                    ):
                        issues.add("uneven_tuck")
                    if (
                        self._attempt_min_torso_incline is not None
                        and self._attempt_min_torso_incline < TORSO_LEAN_ALERT_DEG
                    ):
                        issues.add("leaning_forward")

                    if issues:
                        rep_form_quality = "needs_improvement"
                        self.flawed_reps += 1
                        issue_text = ", ".join(
                            i.replace("_", " ") for i in sorted(issues)
                        )
                        feedback = f"Rep {self.rep_count} counted, but watch your form ({issue_text})."
                    else:
                        rep_form_quality = "good"
                        self.good_reps += 1
                        height_note = (
                            "great height"
                            if self._attempt_max_hip_rise >= GOOD_JUMP_RISE
                            else "nice tuck"
                        )
                        feedback = f"Clean rep — {height_note} ({rep_duration:.2f}s)."
                else:
                    rep_completed = False
                    if not jumped:
                        self.no_jump_count += 1
                        feedback = (
                            "That was a knee raise, not a jump — you never "
                            "left the ground. Push off and jump!"
                        )
                    elif not tucked:
                        self.no_tuck_count += 1
                        feedback = (
                            "You jumped but didn't tuck — pull both knees up "
                            "toward your chest at the top of the jump."
                        )
                    elif rep_duration is not None and rep_duration < MIN_REP_DURATION:
                        feedback = "Too fast to be a real jump — not counted."
                    else:
                        feedback = "Took too long — not counted. Land and reset."

                self.rep_start_time = None
                self._reset_attempt()

            if feedback is None:
                feedback = "Good form — keep jumping."

        self.last_angle = self.smoothed_tuck_angle
        self.last_timestamp_s = t

        alignment_issue = None
        if rep_form_quality == "needs_improvement":
            alignment_issue = "form_flagged_on_last_rep"
        response["alignment_ok"] = alignment_issue is None
        response["alignment_issue"] = alignment_issue

        response.update(
            {
                "tuck_angle": raw_tuck_angle,
                "smoothed_tuck_angle": self.smoothed_tuck_angle,
                "left_knee_angle": left_knee_angle,
                "right_knee_angle": right_knee_angle,
                "hip_rise": self.smoothed_hip_rise,
                "angle_velocity": angle_velocity,
                "stage": self.stage,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "no_jump_count": self.no_jump_count,
                "no_tuck_count": self.no_tuck_count,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_duration": rep_duration,
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "feedback": feedback,
            }
        )
        return response


class TuckJumpSession:
    """Full tuck-jump session: one shared pose model + one analyzer.

    Same `target_reps` / `target_sets` / `set_number` contract as
    `PushupSession` — the frontend supplies the coach-assigned plan via
    query params, and only this class decides `session_complete` (this
    set's reps are done) / `exercise_complete` (the whole plan is done).
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = TuckJumpAnalyzer(target_reps)
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
