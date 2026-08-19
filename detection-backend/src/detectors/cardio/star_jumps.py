"""
Star Jacks (aka Star Jump) detector.

A rep-based, whole-body plyometric exercise — not a hold/timer. Canonical
form (confirmed against MasterClass, RazFit, Motra, Steel Supplements, and
Aspira Fitness coaching guides, which agree on this precisely): start
standing with feet together/close and arms at the sides, optionally dipping
into a shallow quarter-squat. Explosively jump — both feet leave the ground
— while simultaneously spreading the legs wide AND raising both arms out
and up, so the body forms an "X"/star shape at the peak of the jump. Land
softly back to the compact starting stance and repeat.

A rep counts ONLY when all three physically-required things genuinely
happened together in the same continuous attempt:

  1. A REAL JUMP — both feet actually left the ground (hip-height rise
     relative to a calibrated standing baseline, normalized by the
     person's own leg length). Without this gate, someone could just do a
     standing "jack" with their feet sliding apart and arms raised — no
     jump at all — and it would look identical to a lazy eye. This is the
     same technique validated in tuck_jump.py.
  2. LEGS SPREAD WIDE — ankle-to-ankle distance, normalized by that same
     calibrated leg length, reaching a real spread rather than a token
     shuffle.
  3. ARMS RAISED OUT — both arms lifted well away from the sides (the
     "spread" is dimensionless: it doesn't matter if arms end up at
     shoulder height, in a wide V, or fully overhead — all are valid star
     shapes per every coaching source above — so this is a single lenient
     angle threshold, not a strict pose match).

Landing back to a compact stance (small leg spread, arms back down) closes
the rep. Two hard-won lessons from this app's other jump/limb detectors are
baked in from the start here, not bolted on after a bug report:

  - Rep VALIDITY is checked from the RAW, per-frame peak values during the
    attempt — never the smoothed/lagged ones. A star jack's open position
    only lasts a handful of frames; averaging that peak against slower
    neighbouring frames (as an early version of tuck_jump.py did, before a
    fix) systematically understates it and silently drops good reps.
    Smoothing is used ONLY to decide the stage transition (so single-frame
    jitter can't flip it back and forth), never to decide whether a
    genuinely good rep happened.
  - Every gating metric is either an ANGLE (arm raise, knee straightness,
    torso lean — all measured at a joint between two long, stable body
    segments) or a distance NORMALIZED against the person's own calibrated
    body scale (leg length) — never a raw pixel distance and never an
    angle computed across a short, easily-foreshortened segment (like an
    elbow-only angle judged from a 2D camera). arm_circles.py originally
    gated on 2-D elbow angle and that badly under-counted real reps because
    a straight arm can still project as "bent" in 2-D depending on which
    way it's pointing relative to the camera; the fix there was exactly
    this — long, stable-segment angles and calibrated-scale distances.

Architecture conventions (sticky standing-calibration gate that doesn't
re-check per frame once set, since the correct airborne pose intentionally
does NOT look like standing; framing checks; attempt-validity window;
session/set-completion contract) mirror the other detectors in this app
(pushup.py, tuck_jump.py) so this detector, its route, and its frontend
behave the same way every other exercise does.
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    LEFT_WRIST,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)

# -------------------------------------------------------------------------
# Tunable constants
# -------------------------------------------------------------------------

MIN_LANDMARK_VISIBILITY = 0.4
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)

# ---- jump gate (hip rise), same technique as tuck_jump.py ----
JUMP_MIN_RISE = 0.08  # hip rise, normalized by calibrated leg length
RISE_SMOOTH_ALPHA = 0.75  # responsive — airborne phase is brief

# ---- leg-spread gate ----
# Ankle-to-ankle distance, normalized by calibrated leg length (hip-to-ankle
# while standing). Standing with feet together/hip-width is well under 1.0
# of a leg length; a real star-jack landing stance ("feet wider than
# shoulder-width apart" per coaching guides) comfortably clears it.
LEG_SPREAD_MIN = 0.55
LEG_SPREAD_CLOSE = 0.30  # must drop back below this to be considered "closed" again

# ---- arm-raise gate ----
# Angle at the shoulder between the "torso-down" direction (shoulder->hip)
# and the "arm" direction (shoulder->wrist). Hanging at the side reads
# close to 0; raised to a T reads ~90; overhead reads ~160-180. Deliberately
# a single lenient threshold rather than a target pose — every coaching
# source (arms at shoulder height, in a wide V, or fully overhead) is a
# valid star shape, and this app's job is to confirm a real, meaningful
# raise happened, not referee exactly how high.
ARM_RAISE_MIN_DEG = 55.0
ARM_RAISE_CLOSE_DEG = 30.0  # must drop back below this to be considered "closed" again
ANGLE_SMOOTH_ALPHA = 0.75  # responsive — matches the brief open phase

# ---- combined "openness" driver for the closed<->open stage machine ----
# Unitless: 0 at the CLOSE thresholds, 1.0 at the MIN (open) thresholds for
# each of the three gates (legs / arms / jump). Composed with MAX, not an
# average — an average lets one maxed-out dimension mask another that never
# moved at all (e.g. a huge arm raise with the legs completely together
# would still only average to ~0.75 and could never open the state machine,
# silently swallowing the attempt instead of correctly reporting "you
# didn't spread your legs"). MAX means ANY one dimension clearly starting
# to move is enough to open the attempt window, so peaks always get
# tracked and a specific, correct rejection reason can always be reported.
# This one number drives the rep state machine (same role `smoothed_angle`
# plays in pushup.py / `smoothed_tuck_angle` plays in tuck_jump.py); actual
# rep VALIDITY is decided separately, from the raw per-frame peaks of the
# three individual gates, never from this driver.
OPEN_ENTER = 0.6
CLOSE_ENTER = 0.25

MIN_REP_DURATION = 0.16  # seconds — faster than this is sensor noise, not a rep
MAX_REP_DURATION = 2.5  # seconds — slower than this means they paused, not jumped

# Soft, non-gating quality checks (affect rep_form_quality only, never
# whether the rep counts)
LEG_ASYMMETRY_ALERT_RATIO = 0.35  # |L-R ankle offset from center| / leg length
ARM_ASYMMETRY_ALERT_DEG = 30.0  # |left arm raise - right arm raise| at peak
TORSO_LEAN_ALERT_DEG = 45.0  # torso incline dropping below this while airborne
BENT_ELBOW_ALERT_DEG = 145.0  # avg elbow angle at peak dropping below this

# ---- standing calibration (the `ready` gate) ----
# Unlike the airborne "star" pose, the calibration pose (standing, legs
# together-ish, arms down) IS how the exercise starts, so a brief hold is
# expected. The streak tolerates the occasional bad/noisy frame instead of
# resetting to zero on a single miss (a "leaky bucket": one bad frame only
# costs two frames of progress, not the whole streak) — real webcam
# landmark jitter shouldn't be able to indefinitely stall calibration.
STANDING_KNEE_ANGLE_MIN = 155.0
STANDING_ARM_MAX_DEG = 40.0  # arms roughly down at the sides
STANDING_LEG_SPREAD_MAX = 0.5  # feet together-to-hip-width, not already spread
TORSO_UPRIGHT_MIN_DEG = 60.0
STABLE_STANDING_FRAMES = 5
STANDING_STREAK_PENALTY = 2  # cost of a single bad frame, in the leaky bucket
LOST_GRACE_FRAMES = 20
BASELINE_EMA_ALPHA = 0.03  # slow adaptive refresh of the standing baseline, once set

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
    single side is visible (camera angle / partial occlusion tolerant)."""
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
        return "You're too close to the camera — back up so your whole body fits with room to spread out."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class StarJacksAnalyzer:
    """Stateful star-jack rep counter with a sticky standing calibration
    gate (rather than a per-frame position gate, since the correct in-air
    pose intentionally does NOT look like the calibration pose — same
    design as tuck_jump.py, for the same reason)."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        # Rep state machine. "closed" = standing/landed (compact), "open" =
        # star shape mid-air.
        self.stage = "closed"
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.no_jump_count = 0  # opened the shape but never left the ground
        self.no_leg_spread_count = 0  # jumped, but legs never spread wide enough
        self.no_arm_raise_count = 0  # jumped + legs spread, but arms never came up

        self.smoothed_openness: Optional[float] = None
        self.smoothed_hip_rise: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None
        self.rep_start_time: Optional[float] = None

        self.session_start_time: Optional[float] = None

        # Standing calibration (the `ready` gate)
        self._standing_streak = 0
        self._lost_streak = 0
        self.ready = False
        self.baseline_hip_y: Optional[float] = None
        self.baseline_leg_length: Optional[float] = None

        # Per-attempt extremes, captured (from RAW per-frame values) while
        # stage == "open"
        self._attempt_max_hip_rise: float = 0.0
        self._attempt_max_leg_spread_ratio: float = 0.0
        self._attempt_max_arm_raise_deg: float = 0.0
        self._attempt_max_left_arm_deg: float = 0.0
        self._attempt_max_right_arm_deg: float = 0.0
        self._attempt_max_left_ankle_offset: float = 0.0
        self._attempt_max_right_ankle_offset: float = 0.0
        self._attempt_min_torso_incline: Optional[float] = None
        self._attempt_elbow_angles: list[float] = []

    # ---------------------------------------------------------------
    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 1.6:
            return "too_slow"
        if duration >= 1.0:
            return "slow"
        if duration >= 0.4:
            return "good"
        if duration >= 0.16:
            return "fast"
        return "too_fast"

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _reset_attempt(self):
        self._attempt_max_hip_rise = 0.0
        self._attempt_max_leg_spread_ratio = 0.0
        self._attempt_max_arm_raise_deg = 0.0
        self._attempt_max_left_arm_deg = 0.0
        self._attempt_max_right_arm_deg = 0.0
        self._attempt_max_left_ankle_offset = 0.0
        self._attempt_max_right_ankle_offset = 0.0
        self._attempt_min_torso_incline = None
        self._attempt_elbow_angles = []

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
            "openness": None,
            "smoothed_openness": None,
            "hip_rise": None,
            "leg_spread_ratio": None,
            "arm_raise_deg": None,
            "left_arm_raise_deg": None,
            "right_arm_raise_deg": None,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "no_jump_count": self.no_jump_count,
            "no_leg_spread_count": self.no_leg_spread_count,
            "no_arm_raise_count": self.no_arm_raise_count,
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
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]

        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
        left_leg_ok = _visible((l_hip, l_knee, l_ankle))
        right_leg_ok = _visible((r_hip, r_knee, r_ankle))
        left_arm_ok = _visible((l_shoulder, l_wrist))
        right_arm_ok = _visible((r_shoulder, r_wrist))

        if (
            not torso_visible
            or (not left_leg_ok and not right_leg_ok)
            or (not left_arm_ok and not right_arm_ok)
        ):
            self._lost_streak += 1
            if self._lost_streak >= LOST_GRACE_FRAMES:
                self.ready = False
                self._standing_streak = 0
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your whole body — make sure your shoulders, hips, "
                "knees, ankles, and arms are all in frame."
            )
            return response

        response["pose_detected"] = True
        self._lost_streak = 0

        mid_shoulder = _pair_mid(l_shoulder, r_shoulder)
        mid_hip = _pair_mid(l_hip, r_hip)
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
                l_wrist,
                r_wrist,
            )
            if _visible((p,))
        ]
        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        # ---- knee straightness (calibration only) ----
        left_knee_angle = _angle_deg(l_hip, l_knee, l_ankle) if left_leg_ok else None
        right_knee_angle = _angle_deg(r_hip, r_knee, r_ankle) if right_leg_ok else None
        knee_angles = [a for a in (left_knee_angle, right_knee_angle) if a is not None]
        avg_knee_angle = sum(knee_angles) / len(knee_angles) if knee_angles else None

        # ---- arm raise angle: shoulder->hip (down) vs shoulder->wrist (arm) ----
        # A long-segment angle at a joint with two stable reference points —
        # doesn't suffer the foreshortening problem a short elbow-only angle
        # does (see module docstring).
        left_arm_deg = _angle_deg(l_hip, l_shoulder, l_wrist) if left_arm_ok else None
        right_arm_deg = _angle_deg(r_hip, r_shoulder, r_wrist) if right_arm_ok else None
        arm_degs = [a for a in (left_arm_deg, right_arm_deg) if a is not None]
        avg_arm_deg = sum(arm_degs) / len(arm_degs) if arm_degs else 0.0

        # ---- leg spread: ankle-to-ankle distance ----
        ankle_distance = (
            _dist(l_ankle, r_ankle) if (left_leg_ok and right_leg_ok) else None
        )

        torso_incline = (
            _torso_incline_deg(mid_shoulder, mid_hip)
            if (mid_shoulder and mid_hip)
            else None
        )

        # ---- standing calibration (the `ready` gate) — leaky-bucket streak ----
        leg_length_now = _dist(mid_hip, mid_ankle) if (mid_hip and mid_ankle) else None

        standing_candidate = (
            avg_knee_angle is not None
            and avg_knee_angle >= STANDING_KNEE_ANGLE_MIN
            and avg_arm_deg <= STANDING_ARM_MAX_DEG
            and torso_incline is not None
            and torso_incline >= TORSO_UPRIGHT_MIN_DEG
            and framing_message is None
            and leg_length_now is not None
            and leg_length_now > 1e-4
            and (
                ankle_distance is None
                or ankle_distance / leg_length_now <= STANDING_LEG_SPREAD_MAX
            )
        )

        if standing_candidate:
            self._standing_streak = min(
                STABLE_STANDING_FRAMES, self._standing_streak + 1
            )
        else:
            self._standing_streak = max(
                0, self._standing_streak - STANDING_STREAK_PENALTY
            )

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
            and self.stage == "closed"
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
        response["left_arm_raise_deg"] = left_arm_deg
        response["right_arm_raise_deg"] = right_arm_deg
        response["arm_raise_deg"] = avg_arm_deg

        if not self.ready or not self.baseline_leg_length:
            response["feedback"] = framing_message or (
                f"Stand tall, feet together, arms at your sides, whole body "
                f"in frame — hold still to calibrate "
                f"({self._standing_streak}/{STABLE_STANDING_FRAMES})."
            )
            return response

        # ---- hip rise (jump height), normalized by calibrated leg length ----
        hip_rise = (self.baseline_hip_y - mid_hip.y) / self.baseline_leg_length
        leg_spread_ratio = (
            (ankle_distance / self.baseline_leg_length)
            if ankle_distance is not None
            else 0.0
        )

        response["hip_rise"] = hip_rise
        response["leg_spread_ratio"] = leg_spread_ratio

        # ---- smoothing (used ONLY to drive the stage transition) ----
        if self.smoothed_hip_rise is None:
            self.smoothed_hip_rise = hip_rise
        else:
            self.smoothed_hip_rise = (
                RISE_SMOOTH_ALPHA * hip_rise
                + (1 - RISE_SMOOTH_ALPHA) * self.smoothed_hip_rise
            )

        leg_progress = _clamp(
            (leg_spread_ratio - LEG_SPREAD_CLOSE)
            / max(LEG_SPREAD_MIN - LEG_SPREAD_CLOSE, 1e-6),
            0.0,
            1.5,
        )
        arm_progress = _clamp(
            (avg_arm_deg - ARM_RAISE_CLOSE_DEG)
            / max(ARM_RAISE_MIN_DEG - ARM_RAISE_CLOSE_DEG, 1e-6),
            0.0,
            1.5,
        )
        jump_progress = _clamp(hip_rise / max(JUMP_MIN_RISE, 1e-6), 0.0, 1.5)
        raw_openness = max(leg_progress, arm_progress, jump_progress)
        response["openness"] = raw_openness

        if self.smoothed_openness is None:
            self.smoothed_openness = raw_openness
        else:
            self.smoothed_openness = (
                ANGLE_SMOOTH_ALPHA * raw_openness
                + (1 - ANGLE_SMOOTH_ALPHA) * self.smoothed_openness
            )
        response["smoothed_openness"] = self.smoothed_openness

        response["airborne"] = bool(
            self.smoothed_hip_rise is not None
            and self.smoothed_hip_rise >= JUMP_MIN_RISE
        )

        feedback = framing_message

        # ---- rep state machine ----
        rep_completed = False
        rep_duration = rep_class = rep_form_quality = None

        if self.stage == "closed" and self.smoothed_openness > OPEN_ENTER:
            self.rep_start_time = t
            self.stage = "open"
            self._reset_attempt()
        elif self.stage == "open" and self.smoothed_openness < CLOSE_ENTER:
            self.stage = "closed"
            rep_completed = True

        if self.stage == "open":
            # Peaks are captured from RAW per-frame values, not the smoothed
            # ones — a real star jack only spends a couple of frames at its
            # actual peak, and averaging that against slower neighbouring
            # frames would understate it (see module docstring). Smoothing
            # above is only used to decide the stage transition.
            self._attempt_max_hip_rise = max(self._attempt_max_hip_rise, hip_rise)
            self._attempt_max_leg_spread_ratio = max(
                self._attempt_max_leg_spread_ratio, leg_spread_ratio
            )
            self._attempt_max_arm_raise_deg = max(
                self._attempt_max_arm_raise_deg, avg_arm_deg
            )
            if left_arm_deg is not None:
                self._attempt_max_left_arm_deg = max(
                    self._attempt_max_left_arm_deg, left_arm_deg
                )
            if right_arm_deg is not None:
                self._attempt_max_right_arm_deg = max(
                    self._attempt_max_right_arm_deg, right_arm_deg
                )
            if mid_hip is not None:
                if left_leg_ok:
                    self._attempt_max_left_ankle_offset = max(
                        self._attempt_max_left_ankle_offset, abs(mid_hip.x - l_ankle.x)
                    )
                if right_leg_ok:
                    self._attempt_max_right_ankle_offset = max(
                        self._attempt_max_right_ankle_offset, abs(r_ankle.x - mid_hip.x)
                    )
            if torso_incline is not None and (
                self._attempt_min_torso_incline is None
                or torso_incline < self._attempt_min_torso_incline
            ):
                self._attempt_min_torso_incline = torso_incline
            if left_arm_ok and right_arm_ok:
                elbow_angle = (
                    _angle_deg(l_shoulder, l_elbow, l_wrist)
                    + _angle_deg(r_shoulder, r_elbow, r_wrist)
                ) / 2.0
                self._attempt_elbow_angles.append(elbow_angle)

        if rep_completed:
            rep_duration = (
                (t - self.rep_start_time) if self.rep_start_time is not None else None
            )

            jumped = self._attempt_max_hip_rise >= JUMP_MIN_RISE
            legs_spread = self._attempt_max_leg_spread_ratio >= LEG_SPREAD_MIN
            arms_raised = self._attempt_max_arm_raise_deg >= ARM_RAISE_MIN_DEG
            duration_ok = (
                rep_duration is not None
                and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
            )

            valid = jumped and legs_spread and arms_raised and duration_ok

            if valid:
                self.rep_count += 1
                rep_class = self._classify_tempo(rep_duration)

                issues = set()
                if (
                    self._attempt_max_left_ankle_offset > 0
                    and self._attempt_max_right_ankle_offset > 0
                    and abs(
                        self._attempt_max_left_ankle_offset
                        - self._attempt_max_right_ankle_offset
                    )
                    / self.baseline_leg_length
                    > LEG_ASYMMETRY_ALERT_RATIO
                ):
                    issues.add("uneven_leg_spread")
                if (
                    abs(
                        self._attempt_max_left_arm_deg - self._attempt_max_right_arm_deg
                    )
                    > ARM_ASYMMETRY_ALERT_DEG
                ):
                    issues.add("uneven_arm_raise")
                if (
                    self._attempt_min_torso_incline is not None
                    and self._attempt_min_torso_incline < TORSO_LEAN_ALERT_DEG
                ):
                    issues.add("leaning_forward")
                if (
                    self._attempt_elbow_angles
                    and (
                        sum(self._attempt_elbow_angles)
                        / len(self._attempt_elbow_angles)
                    )
                    < BENT_ELBOW_ALERT_DEG
                ):
                    issues.add("bent_arms")

                if issues:
                    rep_form_quality = "needs_improvement"
                    self.flawed_reps += 1
                    issue_text = ", ".join(i.replace("_", " ") for i in sorted(issues))
                    feedback = f"Rep {self.rep_count} counted, but watch your form ({issue_text})."
                else:
                    rep_form_quality = "good"
                    self.good_reps += 1
                    feedback = f"Clean star jack — full spread ({rep_duration:.2f}s)."
            else:
                rep_completed = False
                if not jumped:
                    self.no_jump_count += 1
                    feedback = (
                        "You spread out but didn't leave the ground — jump! "
                        "A standing jack doesn't count."
                    )
                elif not legs_spread:
                    self.no_leg_spread_count += 1
                    feedback = "Jumped, but spread your legs wider at the top."
                elif not arms_raised:
                    self.no_arm_raise_count += 1
                    feedback = (
                        "Jumped and spread your legs, but raise your arms out too."
                    )
                elif rep_duration is not None and rep_duration < MIN_REP_DURATION:
                    feedback = "Too fast to be a real rep — not counted."
                else:
                    feedback = "Took too long — not counted. Land and reset."

            self.rep_start_time = None
            self._reset_attempt()

        if feedback is None:
            feedback = "Good form — keep going."

        self.last_timestamp_s = t

        alignment_issue = None
        if rep_form_quality == "needs_improvement":
            alignment_issue = "form_flagged_on_last_rep"
        response["alignment_ok"] = alignment_issue is None
        response["alignment_issue"] = alignment_issue

        response.update(
            {
                "stage": self.stage,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "no_jump_count": self.no_jump_count,
                "no_leg_spread_count": self.no_leg_spread_count,
                "no_arm_raise_count": self.no_arm_raise_count,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_duration": rep_duration,
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "feedback": feedback,
            }
        )
        return response


class StarJacksSession:
    """Full star-jacks session: one shared pose model + one analyzer. Same
    `target_reps` / `target_sets` / `set_number` contract as every other
    exercise session class in this app."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = StarJacksAnalyzer(target_reps)
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
