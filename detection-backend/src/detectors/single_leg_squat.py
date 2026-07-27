"""
Single-leg squat — per-side rep counter with support-mode-aware depth.

Design
------
Same "angle at a joint drives a down/up hysteresis state machine" pattern
as `pushup.py` and `leg_raise.py`, applied to the stance-leg knee:

    stance_knee_angle = angle(STANCE_HIP, STANCE_KNEE, STANCE_ANKLE)

Standing tall this reads close to 180°; squatting down on that one leg
drives it toward 90° or below depending on how deep the selected
progression asks for.

Side assignment
----------------
Unlike leg-raise (both legs move together) or pushup (symmetric), a
single-leg squat only has one true working leg per rep, and guessing
which leg is "the stance leg" from pose alone is exactly the kind of
fragile heuristic that caused the leg-raise position-gate bug (a plausible-
looking signal that quietly breaks on real footage). So `current_side` is
not inferred — it's assigned explicitly by the caller via the `side`
query param on the websocket route, the same way `target_reps` /
`target_sets` / `set_number` already are. One connection = one side; the
frontend runs a left session then a right session, same shape as it
already runs set 1 then set 2.

Support mode
------------
`support_mode` ("assisted" / "standard" / "deep") only changes
`BOTTOM_ANGLE` (how much knee bend counts as "reached depth") and, for
"assisted", relaxes the free-leg-touching-down rule. Nothing else about
the state machine changes between modes — this keeps the same
progression logic usable end to end instead of branching the whole
analyzer per mode.

False-negative aversion (lesson carried over from the leg-raise fix)
----------------------------------------------------------------------
The standing/ready gate learned the hard way on leg-raise: a gate that
requires *positive proof* of the correct position flickers on real
footage shot at slightly-off angles, and every flicker silently discards
whatever rep was in progress. So, same as `leg_raise.py`'s
`_assess_standing_position` below, the gate here only disqualifies a
frame on clear evidence of NOT standing (torso folded near-horizontal, or
a bbox shaped like someone crouched/lying rather than standing) — it does
not require proof of a perfect upright stance. Balance wobble, a slightly
rotated camera, or a deep forward hinge on the "deep" progression must
never by themselves zero out `position_ok`.

Balance is inherently noisy for this exercise, so:
    * stance-knee angle and hip position are both smoothed (`_smooth`),
    * a rep only needs `BOTTOM_HOLD_FRAMES` consecutive frames at depth
      to "settle" (not a timed pause), and
    * small-radius stance-foot jitter is treated as normal wobble; only a
      large, sudden displacement counts as a hop.
"""

import math
from collections import deque
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

# Stance-knee angle (hip-knee-ankle) thresholds.
#
# IMPORTANT: these are NOT fixed absolute angles. A hardcoded "standing =
# 160 degrees" assumes pose estimation reads a near-perfect straight leg
# as ~180 — but the front-on camera this exercise recommends is exactly
# the view where that's least true: foreshortening bends the projected
# 2D hip-knee-ankle angle even when the 3D leg is dead straight, and how
# much depends on the person's exact stance and camera placement. A fixed
# threshold that happens to sit above a given user's real standing
# reading means the rep can *start* (easy to bend below a high bar) but
# can never *complete* (returning to "standing" requires clearing that
# same bar) — a correctly performed squat then never counts, no matter
# how many times it's repeated. Same class of bug as the leg-raise
# position-gate fix: replace the fixed threshold with a per-session
# calibrated baseline (see `_run_calibration` below) and measure
# everything as a relative drop from that baseline instead.
DEFAULT_TOP_ANGLE_HINT = (
    160.0  # fallback baseline only, used before calibration finishes
)
TOP_RETURN_MARGIN_DEG = (
    12.0  # how far below baseline still counts as "back to standing"
)
ENTER_DESCENT_MARGIN_DEG = 18.0  # how far below baseline counts as "started squatting"
REQUIRED_DROP_BY_MODE = {
    "assisted": 25.0,  # shallow, balance-assisted depth
    "standard": 45.0,  # a normal single-leg squat
    "deep": 70.0,  # pistol-style depth
}
MIN_EFFECTIVE_BOTTOM_ANGLE = 40.0  # safety floor regardless of baseline
DEFAULT_MODE = "standard"

CALIBRATION_FRAMES = 8  # ~0.25s of stable standing at 30fps
CALIBRATION_MAX_JITTER_DEG = (
    10.0  # a bigger frame-to-frame jump restarts the sample window
)
CALIBRATION_TIMEOUT_S = (
    3.0  # force-calibrate on whatever we have rather than stall forever
)

MIN_ANGLE_DELTA_BY_MODE = {
    "assisted": 15.0,
    "standard": 30.0,
    "deep": 50.0,
}

MIN_REP_DURATION = (
    0.5  # seconds — balance-heavy movement, genuinely slower than a pushup
)
MAX_REP_DURATION = 15.0

BOTTOM_HOLD_FRAMES = (
    2  # consecutive frames at depth needed to "settle" — not a timed pause
)

# Knee-tracking-over-foot (soft note): horizontal knee drift past the foot's
# centerline, normalized by stance-leg length.
KNEE_TRACK_TOLERANCE = 0.18

# Pelvis level (soft note): hip-height difference between sides, normalized
# by shoulder width.
PELVIS_LEVEL_TOLERANCE = 0.12

# Torso forward lean (soft note, mode-aware — "standard" and "deep" both
# expect some natural forward hinge; only excessive folding is flagged).
TORSO_LEAN_TOLERANCE_DEG = 45.0

# Free leg shouldn't come down to the floor and take weight. The stance
# ankle barely moves during a single-leg squat (the foot stays planted),
# so it doubles as a live floor-level reference.
FREE_LEG_FLOOR_TOLERANCE = 0.12

# Hop / balance-loss: a sudden stance-foot displacement between frames,
# normalized by stance-leg length, well beyond ordinary wobble.
HOP_DISPLACEMENT_THRESHOLD = 0.10
WOBBLE_HISTORY_FRAMES = 12

# Standing-position gate — see module docstring for why this is
# "guilty until proven not-standing" rather than the reverse.
TORSO_INCLINE_NOT_STANDING_MAX_DEG = 40.0
BBOX_ASPECT_NOT_STANDING_MIN = 1.15
GROUNDED_HIP_GAP_MIN = (
    1.0  # hip must sit at least ~1x torso-length above the stance ankle
)
STABLE_FRAMES = 3
GRACE_FRAMES = 24  # ~0.8s at 30fps

# Camera framing
FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.95
BBOX_TOO_FAR = 0.15

VALID_MODES = ("assisted", "standard", "deep")
VALID_SIDES = ("left", "right")


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


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 3


def _torso_incline_deg(mid_shoulder, mid_hip) -> Optional[float]:
    """0deg = torso lying flat/horizontal, 90deg = torso perfectly vertical."""
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
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    if height <= 1e-6:
        return None
    return width / height


def _assess_standing_position(
    torso_incline_deg: Optional[float],
    bbox_aspect: Optional[float],
) -> tuple[bool, bool]:
    """(is_acceptable, is_clearly_not_standing).

    Deliberately asymmetric, same reasoning as `leg_raise.py`'s gate:
    only disqualify a frame on clear evidence of NOT standing (folded
    over near-horizontal, or a bbox shaped like a seated/prone person)
    rather than requiring proof of a picture-perfect upright stance.
    """
    not_standing = False

    if (
        torso_incline_deg is not None
        and torso_incline_deg <= TORSO_INCLINE_NOT_STANDING_MAX_DEG
    ):
        not_standing = True
    if bbox_aspect is not None and bbox_aspect >= BBOX_ASPECT_NOT_STANDING_MIN:
        not_standing = True

    return (not not_standing), not_standing


def _framing_feedback(points: list[_Point]) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — step back so your whole body is visible."
            )

    if len(points) < 4:
        return None

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "You're too close to the camera — step back so your whole body fits in frame."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class SingleLegSquatAnalyzer:
    """Stateful single-leg-squat rep counter for one side + one connection."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        side: str = "left",
        mode: str = DEFAULT_MODE,
    ):
        self.target_reps = target_reps
        self.side = side if side in VALID_SIDES else "left"
        self.mode = mode if mode in VALID_MODES else DEFAULT_MODE
        self.required_drop = REQUIRED_DROP_BY_MODE[self.mode]
        self.min_angle_delta = MIN_ANGLE_DELTA_BY_MODE[self.mode]

        # Per-session calibrated "standing" baseline — see the constants
        # block above for why this replaced a fixed absolute angle.
        self.baseline_angle: Optional[float] = None
        self._calib_samples: list[float] = []
        self._calib_start_time: Optional[float] = None

        self.stage = "standing"  # "standing" | "descending" | "bottom" | "rising"
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        self.smoothed_angle: Optional[float] = None
        self.last_angle: Optional[float] = None
        self.angle_smooth_alpha = 0.5

        self.rep_start_time: Optional[float] = None
        self._rep_angle_acc = 0.0
        self._current_rep_issues: set[str] = set()
        self._bottom_streak = 0
        self._free_leg_down_streak = 0
        self._rep_had_free_leg_down = False
        self._rep_had_hop = False

        self.session_start_time: Optional[float] = None

        self._floor_streak = 0
        self._bad_streak = 0
        self.ready = False

        self._stance_ankle_history: deque = deque(maxlen=WOBBLE_HISTORY_FRAMES)
        self._last_stance_ankle: Optional[_Point] = None

    # ---------------------------------------------------------------
    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 6.0:
            return "too_slow"
        if duration >= 3.0:
            return "slow"
        if duration >= 1.0:
            return "good"
        if duration >= 0.5:
            return "fast"
        return "too_fast"

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _run_calibration(self, angle: float, t: float, position_ok: bool) -> None:
        """Collect a short window of stable standing readings and lock in
        `self.baseline_angle`. Only runs until calibrated once per
        connection (i.e. once per set) — see the constants block above
        for why a fixed absolute angle doesn't work here.

        False-negative aversion: if the person doesn't hold still long
        enough for a clean sample window, `CALIBRATION_TIMEOUT_S` forces
        a baseline from whatever's been collected rather than stalling
        rep-counting indefinitely.
        """
        if self.baseline_angle is not None:
            return

        if not position_ok:
            self._calib_samples = []
            self._calib_start_time = None
            return

        if self._calib_start_time is None:
            self._calib_start_time = t

        if (
            self._calib_samples
            and abs(angle - self._calib_samples[-1]) > CALIBRATION_MAX_JITTER_DEG
        ):
            # A real movement, not sensor noise — they're not holding
            # still yet, restart the sample window.
            self._calib_samples = [angle]
            self._calib_start_time = t
        else:
            self._calib_samples.append(angle)

        timed_out = (t - self._calib_start_time) >= CALIBRATION_TIMEOUT_S
        if len(self._calib_samples) >= CALIBRATION_FRAMES or (
            timed_out and self._calib_samples
        ):
            self.baseline_angle = sum(self._calib_samples) / len(self._calib_samples)

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "ready": self.ready,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "left_reps": self.rep_count if self.side == "left" else 0,
            "right_reps": self.rep_count if self.side == "right" else 0,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "rep_completed": False,
            "rep_classification": None,
            "rep_form_quality": None,
            "current_side": self.side,
            "position_ok": False,
            "position_message": None,
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
            # extra fields
            "stance_knee_angle": None,
            "hip_depth_ratio": None,
            "torso_angle": None,
            "knee_tracking_ok": True,
            "pelvis_level": True,
            "balance_confidence": None,
            "support_mode": self.mode,
            "bottom_lock": False,
            "top_lock": False,
            "calibrated": False,
            "baseline_angle": None,
            "top_angle_threshold": None,
            "bottom_angle_threshold": None,
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = "No person detected — step into frame."
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]
        l_heel, r_heel = landmarks[LEFT_HEEL], landmarks[RIGHT_HEEL]
        l_foot, r_foot = landmarks[LEFT_FOOT_INDEX], landmarks[RIGHT_FOOT_INDEX]

        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
        if not torso_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your torso — make sure your shoulders and hips "
                "are both in frame."
            )
            return response

        response["pose_detected"] = True

        stance_hip = l_hip if self.side == "left" else r_hip
        stance_knee = l_knee if self.side == "left" else r_knee
        stance_ankle = l_ankle if self.side == "left" else r_ankle
        stance_heel = l_heel if self.side == "left" else r_heel
        stance_foot = l_foot if self.side == "left" else r_foot
        free_ankle = r_ankle if self.side == "left" else l_ankle

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)
        shoulder_width = max(_dist(l_shoulder, r_shoulder), 1e-6)

        torso_incline = _torso_incline_deg(mid_shoulder, mid_hip)
        response["torso_angle"] = (
            round(90.0 - torso_incline, 1) if torso_incline is not None else None
        )

        bbox_candidates = [
            p
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
        bbox_points = [_Point(p.x, p.y) for p in bbox_candidates]
        bbox_aspect = _bbox_aspect(bbox_points)

        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        # Torso incline and bbox shape alone can both look "plausible" for
        # a seated, rig-assisted pose (leaning forward on the ground still
        # reads as a moderate incline, and a compact seated bbox can slip
        # under the aspect-ratio check) — so also check that the hip is
        # actually elevated well above the stance ankle, the way a
        # standing person's is. This only applies while resting between
        # reps (`self.stage == "standing"`): during a real deep-squat
        # bottom, the hip legitimately drops close to ankle height, and
        # this must not fight that.
        grounded = False
        if self.stage == "standing" and _visible((stance_ankle,)):
            hip_ankle_gap = (stance_ankle.y - mid_hip.y) / torso_length
            grounded = hip_ankle_gap < GROUNDED_HIP_GAP_MIN

        is_acceptable, not_standing = _assess_standing_position(
            torso_incline, bbox_aspect
        )
        if grounded:
            is_acceptable = False
            not_standing = True

        if is_acceptable:
            self._floor_streak += 1
            self._bad_streak = 0
        else:
            self._floor_streak = 0
            self._bad_streak += 1

        if self._floor_streak >= STABLE_FRAMES:
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES:
            self.ready = False

        position_ok = self.ready
        response["position_ok"] = position_ok
        response["ready"] = self.ready

        if not_standing and not position_ok:
            position_message = (
                "Get up onto your standing leg — this needs a standing "
                "position (assisted mode still means standing with light "
                "support, not seated). Camera should see your full body, "
                "front-on or slightly angled."
            )
        elif not position_ok:
            position_message = "Get into a standing position on one leg to begin."
        else:
            position_message = None
        response["position_message"] = position_message

        # ---- stance leg tracking ----
        # A transient occlusion (free leg briefly crossing in front, a
        # single bad frame) must not blow away an in-progress rep — same
        # lesson as leg-raise's occlusion fallback. Only bail out entirely
        # if we've never gotten a usable reading at all yet.
        stance_ok = _visible((stance_hip, stance_knee, stance_ankle))
        if not stance_ok and self.smoothed_angle is None:
            response["low_visibility"] = True
            response["feedback"] = (
                f"Can't see your {self.side} leg clearly — adjust the "
                "camera so your hip, knee, and ankle are all in frame."
            )
            return response

        if stance_ok:
            raw_angle = _angle_deg(stance_hip, stance_knee, stance_ankle)
            self.smoothed_angle = (
                raw_angle
                if self.smoothed_angle is None
                else self.angle_smooth_alpha * raw_angle
                + (1 - self.angle_smooth_alpha) * self.smoothed_angle
            )
        else:
            # Coast on the last known angle rather than dropping the frame.
            response["low_visibility"] = True
        response["stance_knee_angle"] = round(self.smoothed_angle, 1)

        # ---- calibrate the personal "standing" baseline (see constants) ----
        self._run_calibration(self.smoothed_angle, t, position_ok)
        response["calibrated"] = self.baseline_angle is not None
        response["baseline_angle"] = (
            round(self.baseline_angle, 1) if self.baseline_angle is not None else None
        )
        baseline_for_calc = (
            self.baseline_angle
            if self.baseline_angle is not None
            else DEFAULT_TOP_ANGLE_HINT
        )
        effective_top_angle = baseline_for_calc - TOP_RETURN_MARGIN_DEG
        effective_enter_angle = baseline_for_calc - ENTER_DESCENT_MARGIN_DEG
        effective_bottom_angle = max(
            MIN_EFFECTIVE_BOTTOM_ANGLE, baseline_for_calc - self.required_drop
        )
        response["top_angle_threshold"] = round(effective_top_angle, 1)
        response["bottom_angle_threshold"] = round(effective_bottom_angle, 1)

        # Depth as a fraction of the knee-angle's calibrated top..bottom
        # range — more stable across camera placements than a raw
        # hip-drop distance, and now scaled to this person's own baseline
        # rather than a one-size-fits-all number.
        leg_length = max(_dist(stance_hip, stance_ankle), 1e-6)
        angle_span = max(effective_top_angle - effective_bottom_angle, 1e-6)
        hip_depth_ratio = max(
            0.0, min(1.0, (effective_top_angle - self.smoothed_angle) / angle_span)
        )
        response["hip_depth_ratio"] = round(hip_depth_ratio, 2)

        response["top_lock"] = self.smoothed_angle >= effective_top_angle
        bottom_reached_now = self.smoothed_angle <= effective_bottom_angle
        if bottom_reached_now:
            self._bottom_streak += 1
        else:
            self._bottom_streak = 0
        response["bottom_lock"] = self._bottom_streak >= BOTTOM_HOLD_FRAMES

        # ---- knee tracking over foot (soft note) ----
        knee_tracking_ok = True
        if _visible((stance_foot,)) or _visible((stance_heel,)):
            foot_ref = stance_foot if _visible((stance_foot,)) else stance_heel
            drift = abs(stance_knee.x - foot_ref.x) / leg_length
            if drift > KNEE_TRACK_TOLERANCE:
                knee_tracking_ok = False
        response["knee_tracking_ok"] = knee_tracking_ok

        # ---- pelvis level (soft note) ----
        pelvis_level = abs(l_hip.y - r_hip.y) / shoulder_width <= PELVIS_LEVEL_TOLERANCE
        response["pelvis_level"] = pelvis_level

        # ---- torso folding too far forward (soft note) ----
        torso_ok = True
        if (
            response["torso_angle"] is not None
            and response["torso_angle"] > TORSO_LEAN_TOLERANCE_DEG
        ):
            torso_ok = False

        # ---- free leg touching down / taking weight ----
        free_leg_down = False
        if _visible((free_ankle,)) and _visible((stance_ankle,)):
            free_leg_down = (
                abs(free_ankle.y - stance_ankle.y) / leg_length
                <= FREE_LEG_FLOOR_TOLERANCE
            )
        if free_leg_down:
            self._free_leg_down_streak += 1
        else:
            self._free_leg_down_streak = 0

        # ---- hop / balance-loss detection off the stance ankle ----
        hop_detected = False
        if _visible((stance_ankle,)):
            current_pt = _Point(stance_ankle.x, stance_ankle.y)
            if self._last_stance_ankle is not None:
                displacement = _dist(current_pt, self._last_stance_ankle) / leg_length
                if displacement > HOP_DISPLACEMENT_THRESHOLD:
                    hop_detected = True
                self._stance_ankle_history.append(displacement)
            self._last_stance_ankle = current_pt

        recent_wobble = (
            sum(self._stance_ankle_history) / len(self._stance_ankle_history)
            if self._stance_ankle_history
            else 0.0
        )
        balance_confidence = max(
            0.0, min(1.0, 1.0 - (recent_wobble / HOP_DISPLACEMENT_THRESHOLD))
        )
        response["balance_confidence"] = round(balance_confidence, 2)

        feedback = framing_message

        # ---- rep state machine — only progresses while standing-gate is ok ----
        rep_completed = False
        rep_duration = rep_class = rep_form_quality = None

        if not position_ok:
            if self.rep_start_time is not None:
                self.rep_start_time = None
                self._rep_angle_acc = 0.0
                self._current_rep_issues = set()
                self._rep_had_free_leg_down = False
                self._rep_had_hop = False
                if feedback is None:
                    feedback = (
                        "Lost standing position mid-rep — not counted. "
                        "Reset and try again."
                    )
            if feedback is None:
                feedback = position_message
        elif self.baseline_angle is None:
            # Still calibrating this connection's standing baseline — no
            # rep progress yet, but this should resolve in well under a
            # second of holding still (or be force-calibrated by the
            # timeout), not block the exercise.
            feedback = "Hold still, standing on your working leg, to calibrate…"
        else:
            entering_descent = (
                self.stage == "standing" and self.smoothed_angle < effective_enter_angle
            )
            if entering_descent:
                self.rep_start_time = t
                self._rep_angle_acc = 0.0
                self._current_rep_issues = set()
                self._rep_had_free_leg_down = False
                self._rep_had_hop = False
                self.stage = "descending"

            if self.last_angle is not None:
                self._rep_angle_acc += abs(self.smoothed_angle - self.last_angle)

            if self.stage in ("descending", "bottom", "rising"):
                if hop_detected:
                    self._rep_had_hop = True
                    self._current_rep_issues.add("balance_lost")
                if self._free_leg_down_streak >= 2 and self.mode != "assisted":
                    self._rep_had_free_leg_down = True
                    self._current_rep_issues.add("free_leg_down")
                if not knee_tracking_ok:
                    self._current_rep_issues.add("knee_collapsing")
                if not pelvis_level:
                    self._current_rep_issues.add("hip_dropping")
                if not torso_ok:
                    self._current_rep_issues.add("torso_folding")

            if self.stage == "descending" and response["bottom_lock"]:
                self.stage = "bottom"
            elif (
                self.stage in ("descending", "bottom")
                and self.smoothed_angle > effective_bottom_angle
            ):
                # left depth zone heading back up (whether or not it locked)
                self.stage = "rising"
            elif self.stage == "rising" and self.smoothed_angle >= effective_top_angle:
                self.stage = "standing"
                rep_completed = True

            if feedback is None and not knee_tracking_ok:
                feedback = "Keep the knee tracking over your foot."
            if feedback is None and not pelvis_level:
                feedback = "Keep the pelvis level — don't let the hip drop."
            if feedback is None and not torso_ok:
                feedback = "Keep the chest tall — you're folding too far forward."
            if feedback is None and self._rep_had_free_leg_down:
                feedback = "Free leg touched down — keep it lifted and controlled."

            if rep_completed:
                rep_duration = (
                    (t - self.rep_start_time)
                    if self.rep_start_time is not None
                    else None
                )

                depth_reached = self._rep_angle_acc >= self.min_angle_delta
                unusable = self._rep_had_hop or (
                    self._rep_had_free_leg_down and self.mode != "assisted"
                )

                valid = (
                    not unusable
                    and rep_duration is not None
                    and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                    and depth_reached
                )

                if valid:
                    self.rep_count += 1
                    rep_class = self._classify_tempo(rep_duration)

                    if self._current_rep_issues:
                        rep_form_quality = "needs_improvement"
                        self.flawed_reps += 1
                        issue_text = ", ".join(
                            i.replace("_", " ")
                            for i in sorted(self._current_rep_issues)
                        )
                        feedback = f"Rep {self.rep_count} counted, but watch your form ({issue_text})."
                    else:
                        rep_form_quality = "good"
                        self.good_reps += 1
                        if rep_class in ("good", "fast"):
                            feedback = f"Clean rep — controlled all the way down and up ({rep_duration:.2f}s)."
                        else:
                            feedback = (
                                f"Good rep, nice and controlled ({rep_duration:.2f}s)."
                            )
                elif not depth_reached:
                    rep_completed = False
                    rep_form_quality = "partial"
                    feedback = "Partial depth — that one wasn't counted, sit back and down further."
                else:
                    rep_completed = False
                    if unusable:
                        feedback = "That rep used the free leg or a hop for balance — not counted."
                    elif rep_duration is not None and rep_duration < MIN_REP_DURATION:
                        feedback = (
                            "Too fast — that one wasn't counted, control the movement."
                        )
                    else:
                        feedback = "That rep took too long — not counted. Keep moving."

                self.rep_start_time = None
                self._rep_angle_acc = 0.0
                self._current_rep_issues = set()
                self._rep_had_free_leg_down = False
                self._rep_had_hop = False

        self.last_angle = self.smoothed_angle

        if feedback is None and not self.ready:
            feedback = "Stand on one leg, working leg under you, to start counting."
        if feedback is None:
            feedback = "Good form — keep going."

        response.update(
            {
                "stage": self.stage,
                "rep_count": self.rep_count,
                "left_reps": self.rep_count if self.side == "left" else 0,
                "right_reps": self.rep_count if self.side == "right" else 0,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "feedback": feedback,
            }
        )
        return response


class SingleLegSquatSession:
    """Full single-leg-squat session: one shared pose model + one analyzer.

    Same convention as `LegRaiseSession` / `PushupSession` — `target_reps`
    / `target_sets` / `set_number` are the coach-assigned plan, and `side`
    / `mode` pin down which leg and which progression this connection is
    grading. The frontend never decides completion on its own;
    `session_complete` / `exercise_complete` are computed here.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
        side: str = "left",
        mode: str = DEFAULT_MODE,
    ):
        self.engine = PoseEngine()
        self.analyzer = SingleLegSquatAnalyzer(target_reps, side=side, mode=mode)
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
