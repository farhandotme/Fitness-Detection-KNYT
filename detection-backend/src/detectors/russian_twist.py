"""
Russian Twist tracker — alternating torso-rotation rep counter.

Design
------
A Russian twist has no up/down limb angle to drive a state machine off of
(that's the push-up / bicep-curl shape). What actually defines a rep here
is rotation: the torso turns to one side, comes back through center, then
turns to the other side. So instead of a two-state "up/down" machine, this
runs a **three-state rotation machine** — `center` / `left` / `right` —
and only ever counts a side when it was reached by passing back through a
confirmed center first. That's the literal implementation of "rotates to
one side, returns through center, then rotates to the other side."

Signal
------
Earlier revisions tried to read torso rotation straight out of an angle
(first the shoulder/hip line angle in the image plane, then the same
thing using MediaPipe's `z` depth estimate). Both turned out to be the
wrong shape of signal to depend on for counting: the image-plane version
barely moves for a rotation about a vertical axis facing the camera, and
`z` on its own is too noisy/inconsistently scaled across setups to trust
as an absolute angle. This version splits the signal into two parts that
are each individually more robust:

  * **Magnitude — self-calibrating, 2D only, no `z` needed.** As the
    torso twists and the hips stay anchored (the whole point of the
    seated base), the shoulder line foreshortens in the image while the
    hip line doesn't. So `shoulder_width / hip_width` shrinks as the
    twist gets bigger, regardless of camera distance/zoom (it's a ratio
    of two things in the same frame, so it's scale-invariant). The
    analyzer tracks a running `baseline_ratio` — effectively "what does
    this ratio look like when facing forward" — as the highest ratio
    it's seen while **confirmed at center** (facing forward is, by
    construction, the widest the shoulder line ever gets relative to the
    hips), then converts however compressed the *current* ratio is back
    into a magnitude in degrees via `acos(ratio / baseline_ratio)` (a
    simple foreshortening model: apparent width ≈ true width *
    cos(twist angle)). No absolute calibration or body-proportion
    assumption required — it adapts to whoever is in frame. Critically,
    the baseline only ever updates while genuinely at a confirmed
    center, never mid-twist — otherwise a twist that's *held* rather
    than quickly flicked through would slowly get absorbed into "this is
    just what forward looks like," eroding its own measured magnitude
    toward zero the longer it's held.
  * **Direction — still needs `z`, but only its sign.** Which shoulder is
    nearer the camera than the other tells you which way the torso
    turned; `z`'s noisiness is mostly a magnitude problem, not a sign
    problem, so this only ever asks "is the left shoulder closer or the
    right," not "by how many degrees." As a second, `z`-independent vote
    on the same question, it also folds in which way the shoulder
    midpoint has drifted relative to the hip midpoint (a secondary,
    purely-2D cue) — the two are weighted-summed and only the sign of
    that sum is used.

`torso_rotation_deg = magnitude_deg * sign(direction_vote)`. Positive =
torso turned to the wearer's left, negative = right (if this comes out
mirrored for a given setup, flip the one-line `DIRECTION_SIGN` constant
below rather than anything structural).

On top of that, the enter/exit rotation thresholds that drive the phase
machine (below) are themselves relative to a **running envelope** of how
much rotation this specific person/setup has actually been producing
(`_envelope_deg`), not fixed absolute degrees — so however the geometry
above happens to scale in a given room/camera/body, "you need to get
back to roughly half of your best recent twist" stays the standard,
rather than a hardcoded number that might not match reality.

Two counting modes, one event stream
-------------------------------------
Every confirmed, valid center->side transition is a single "side touch."
Both requested modes read off the *same* underlying event, they just
report it differently:

  1. Independent per-side counts: `left_count` / `right_count` — a side
     touch increments its own side's counter.
  2. Combined full reps: `rep_count` — incremented whenever a side touch
     lands on the *opposite* side from the last counted touch, i.e. a
     genuine left-then-right (or right-then-left) pair completes. A
     repeated touch on the same side without visiting the other side in
     between does not advance `rep_count` (and also does not increment
     that side's own counter — see `_current_rep_issues`-style handling
     below) since the exercise definition requires alternation, not just
     "went to a side."

Gates (checked every frame, independent of the rotation angle itself)
-----------------------------------------------------------------------
  * **Framing** — full torso in frame, not too close/far. Same style as
    the push-up's `_framing_feedback`.
  * **Both shoulders + both hips visible** — hard requirement. Without
    all four points neither the ratio nor the direction vote is
    trustworthy, so detection simply refuses to start (mirrors the
    push-up's "can't see your torso" bail-out).
  * **Seated base** — a loose geometric check that only rules out the two
    failure modes that are actually detectable from a front camera:
    standing up, or lying flat. It does **not** try to hard-require a
    measurable backward lean — from a front-on camera a backward lean is
    mostly a depth change, and gating `ready` on an image-plane lean
    angle that rarely shows up would block counting almost permanently.
    "Sit back slightly" is still shown as a coaching tip, just not as a
    hard gate. Debounced by a stability streak the same way the push-up
    gates its floor-position check (`STABLE_SEATED_FRAMES` / `GRACE_FRAMES`).
  * **Leg stability** — a *counting* gate only, per the spec: legs are
    tracked (knee, falling back to ankle — knees read as more stable than
    ankles in a seated, bent-knee pose) over a short rolling time window,
    and if they've moved more than a normalized threshold recently,
    `legs_stable` goes false. Rotation is still tracked and displayed
    while this is false, but a side touch that lands while legs are
    unstable is discarded rather than counted — same idea as the push-up
    discarding an in-flight rep when the plank breaks.

Hysteresis
----------
Two angle bands (`rot_enter` to leave center, smaller `rot_exit` to
re-enter center — both derived from the adaptive envelope above, not
fixed constants) plus a consecutive-frame dwell requirement
(`STABLE_FRAMES`) before a phase change is actually committed. This is
the same two-part hysteresis pattern `SidePlankAnalyzer` uses for its
`ALIGN_BROKEN` / `ALIGN_RESUME` band, just applied on both sides of
center instead of one break threshold.
"""

import math
from collections import deque
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
# Hard requirement from the spec: both shoulders and both hips visible.
REQUIRED_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)
CORE_VISIBILITY_MIN = 0.4

# ---- direction sign convention ----
# Flip to -1 in one place if left/right come out mirrored for a given
# camera/mirroring setup, rather than touching anything structural.
DIRECTION_SIGN = 1

# ---- magnitude: self-calibrating shoulder/hip width-ratio model ----
BASELINE_RATIO_DECAY = 0.999  # slow decay so the "facing forward" baseline can drift
BASELINE_RATIO_FLOOR = 0.3  # sanity floor so a bad first frame can't wreck the ratio
LATERAL_SHIFT_WEIGHT = 0.35  # secondary, purely-2D direction vote weight vs. z's

# ---- rotation hysteresis: relative to a running envelope of THIS
# person/setup's observed motion, not fixed absolute degrees, so it
# self-tunes regardless of how the geometry above happens to scale in a
# given room/camera/body. Floors keep it from getting noise-sensitive
# before the envelope has built up.
ENVELOPE_DECAY = 0.985  # per-frame decay toward the floor when motion quiets down
ENVELOPE_MIN_DEG = 10.0
ENVELOPE_MAX_DEG = 75.0
ENTER_FRACTION = 0.45  # must exceed this fraction of the envelope to enter a side
EXIT_FRACTION = 0.18  # must fall back below this fraction to be considered at center
PARTIAL_FRACTION = 0.14  # engaged enough to be a real attempt, not noise
ROT_ENTER_FLOOR_DEG = 6.0
ROT_EXIT_FLOOR_DEG = 2.5
ROT_PARTIAL_FLOOR_DEG = 2.0

STABLE_FRAMES = 3  # consecutive frames required to commit a phase change
ANGLE_SMOOTH_ALPHA = 0.5

# ---- timing validity for a side touch (center -> side) ----
MIN_TOUCH_DURATION = 0.10  # seconds — faster than this = tracking glitch
MAX_TOUCH_DURATION = 6.0  # seconds — slower than this = a pause, not a fluid rep

# ---- seated base-position gate ----
# Only the two failure modes that are actually detectable from a front
# camera are hard gates — see module docstring for why a lean-angle
# requirement isn't one of them.
LEAN_LYING_DOWN_MAX_DEG = 55.0  # beyond this it reads as lying flat, not seated
SEATED_LEAN_TIP_MIN_DEG = 6.0  # below this, show "Sit back slightly." (advisory only)
LEG_VERTICAL_STANDING_MIN = 0.85  # same ratio push-up uses to detect "standing"
STABLE_SEATED_FRAMES = 4
GRACE_FRAMES = 10

# ---- leg stability gate (counting gate only, per spec) ----
LEG_STABILITY_WINDOW_SECONDS = 0.7
LEG_SWING_THRESHOLD = 0.4  # normalized (by torso length) positional range

# ---- camera framing ----
FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.95
BBOX_TOO_FAR = 0.12


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


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _shoulder_hip_ratio(l_shoulder, r_shoulder, l_hip, r_hip) -> float:
    """2D shoulder width / hip width. Scale-invariant (both shrink/grow
    together with camera distance), and shrinks specifically as the
    shoulder line foreshortens relative to the (anchored) hip line during
    a twist — see module docstring."""
    shoulder_width = _dist(l_shoulder, r_shoulder)
    hip_width = max(_dist(l_hip, r_hip), 1e-6)
    return shoulder_width / hip_width


def _direction_vote(
    l_shoulder, r_shoulder, mid_shoulder, mid_hip, shoulder_width
) -> float:
    """Signed, unitless vote for which way the torso is twisted — used
    only for its sign. Combines two independent cues (see docstring):
    which shoulder is nearer the camera (from `z`), and which way the
    shoulder midpoint has drifted relative to the hip midpoint (2D
    only). Neither is trusted for magnitude, only for sign, and only
    when the torso rotation magnitude clears a noise floor anyway."""
    z_vote = l_shoulder.z - r_shoulder.z
    lateral_vote = (mid_shoulder.x - mid_hip.x) / max(shoulder_width, 1e-6)
    return z_vote + LATERAL_SHIFT_WEIGHT * lateral_vote


def _torso_lean_deg(mid_shoulder, mid_hip) -> float:
    """0 = perfectly vertical torso, 90 = perfectly horizontal (lying down)."""
    dx = abs(mid_hip.x - mid_shoulder.x)
    dy = abs(mid_hip.y - mid_shoulder.y)
    return math.degrees(math.atan2(dx, max(dy, 1e-9)))


def _leg_extension_point(l_ankle, r_ankle, l_knee, r_knee) -> Optional[_Point]:
    """Prefers ankles — used for the "standing" check, which needs the
    full hip-to-foot leg length to distinguish standing (legs extended
    far below the hips) from seated (legs bent, feet much closer)."""
    ankles = [p for p in (l_ankle, r_ankle) if _visible((p,))]
    if len(ankles) == 2:
        return _midpoint(*ankles)
    if len(ankles) == 1:
        return _Point(ankles[0].x, ankles[0].y)
    knees = [p for p in (l_knee, r_knee) if _visible((p,))]
    if len(knees) == 2:
        return _midpoint(*knees)
    if len(knees) == 1:
        return _Point(knees[0].x, knees[0].y)
    return None


def _leg_stability_point(l_ankle, r_ankle, l_knee, r_knee) -> Optional[_Point]:
    """Prefers knees — for a seated, bent-knee pose the knees read as
    more reliably visible and less jittery than ankles, which can be
    partly tucked or occluded. Used only for the swing/stability gate."""
    knees = [p for p in (l_knee, r_knee) if _visible((p,))]
    if len(knees) == 2:
        return _midpoint(*knees)
    if len(knees) == 1:
        return _Point(knees[0].x, knees[0].y)
    ankles = [p for p in (l_ankle, r_ankle) if _visible((p,))]
    if len(ankles) == 2:
        return _midpoint(*ankles)
    if len(ankles) == 1:
        return _Point(ankles[0].x, ankles[0].y)
    return None


def _bbox_points(points: list[_Point]) -> Optional[tuple[float, float, float, float]]:
    if not points:
        return None
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    return min(xs), max(xs), min(ys), max(ys)


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

    box = _bbox_points(points)
    if box is None:
        return None
    min_x, max_x, min_y, max_y = box
    width, height = max_x - min_x, max_y - min_y

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return (
            "You're too close to the camera — back up so your whole body fits in frame."
        )
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."
    return None


class RussianTwistAnalyzer:
    """Stateful Russian twist alternating-rotation counter.

    No rep up/down state machine — see module docstring. Rep progress is
    driven entirely by the three-state `center` / `left` / `right`
    rotation phase machine below.
    """

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        # Rotation phase machine
        self.phase = "center"  # "center" | "left" | "right"
        self._candidate_phase = "center"
        self._candidate_streak = 0

        self.smoothed_rotation: Optional[float] = None
        self._last_phase_change_time: Optional[float] = None

        # Self-calibrating magnitude model (see module docstring) — the
        # highest shoulder/hip width ratio seen recently, standing in for
        # "what does facing-forward look like for this person/camera."
        self._baseline_ratio: Optional[float] = None
        # Running envelope of observed |rotation| — the enter/exit
        # thresholds are a fraction of this, not fixed absolute degrees.
        self._envelope_deg = ENVELOPE_MIN_DEG

        # Counting
        self.left_count = 0
        self.right_count = 0
        self.rep_count = 0
        self._last_counted_side: Optional[str] = None
        # Every valid alternating touch increments this; a full rep (one
        # left + one right) is complete every *second* touch, not every
        # touch — otherwise every direction change would double-count.
        self._touch_count = 0

        # "Rotate further left/right" partial-attempt detection
        self._attempt_peak_deg = 0.0
        self._attempt_flagged = False

        # Seated base-position gating
        self._seated_streak = 0
        self._bad_seated_streak = 0
        self.ready = False

        # Leg-stability gate
        self._leg_history: deque[tuple[float, float, float]] = deque()

        self.session_start_time: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None

    # ---------------------------------------------------------------
    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _assess_leg_stability(
        self, leg_point: Optional[_Point], torso_length: float, t: float
    ):
        if leg_point is None:
            return True, False  # can't verify — don't block on what we can't see

        self._leg_history.append((t, leg_point.x, leg_point.y))
        while (
            self._leg_history
            and t - self._leg_history[0][0] > LEG_STABILITY_WINDOW_SECONDS
        ):
            self._leg_history.popleft()

        if len(self._leg_history) < 2:
            return True, True

        xs = [p[1] for p in self._leg_history]
        ys = [p[2] for p in self._leg_history]
        spread = max(max(xs) - min(xs), max(ys) - min(ys))
        normalized = spread / max(torso_length, 1e-6)
        return normalized <= LEG_SWING_THRESHOLD, True

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "seated_ok": False,
            "seated_message": None,
            "ready": self.ready,
            "framing_ok": True,
            "framing_message": None,
            "torso_rotation_deg": None,
            "raw_rotation_deg": None,
            "shoulder_hip_ratio": None,
            "baseline_ratio": None,
            "rotation_envelope_deg": None,
            "phase": self.phase,
            "left_count": self.left_count,
            "right_count": self.right_count,
            "rep_count": self.rep_count,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "side_completed": False,
            "side_completed_which": None,
            "legs_stable": True,
            "legs_visible": False,
            "leg_message": None,
            "low_visibility": False,
            "feedback": None,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None:
            response["feedback"] = "No person detected — step into frame."
            return response

        required_ok = all(
            landmarks[i].visibility is not None
            and landmarks[i].visibility > CORE_VISIBILITY_MIN
            for i in REQUIRED_LANDMARKS
        )
        if not required_ok:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see both shoulders and both hips clearly — adjust the "
                "camera so your full torso is in frame."
            )
            return response

        response["pose_detected"] = True

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)

        bbox_candidates = [
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
        framing_message = _framing_feedback(bbox_candidates)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        # ---- seated base-position gate ----
        # Only "standing" and "lying flat" are hard-gated here — both are
        # reliably detectable from a front camera. A backward-lean
        # requirement is deliberately NOT a hard gate (see module
        # docstring): it's shown as a coaching tip only.
        lean_deg = _torso_lean_deg(mid_shoulder, mid_hip)
        leg_extension = _leg_extension_point(l_ankle, r_ankle, l_knee, r_knee)
        leg_vertical_ratio = (
            abs(mid_hip.y - leg_extension.y) / torso_length
            if leg_extension is not None
            else None
        )
        is_standing = (
            leg_vertical_ratio is not None
            and leg_vertical_ratio >= LEG_VERTICAL_STANDING_MIN
            and lean_deg < LEAN_LYING_DOWN_MAX_DEG
        )
        is_lying_down = lean_deg > LEAN_LYING_DOWN_MAX_DEG

        if is_standing:
            seated_candidate_ok = False
            seated_block_message = (
                "Sit down on the floor or a mat to start your Russian twists."
            )
            lean_tip = None
        elif is_lying_down:
            seated_candidate_ok = False
            seated_block_message = (
                "Sit up into position — torso upright with a slight backward lean."
            )
            lean_tip = None
        else:
            seated_candidate_ok = True
            seated_block_message = None
            lean_tip = (
                "Sit back slightly." if lean_deg < SEATED_LEAN_TIP_MIN_DEG else None
            )

        if seated_candidate_ok:
            self._seated_streak += 1
            self._bad_seated_streak = 0
        else:
            self._seated_streak = 0
            self._bad_seated_streak += 1

        if self._seated_streak >= STABLE_SEATED_FRAMES:
            self.ready = True
        elif self._bad_seated_streak >= GRACE_FRAMES:
            self.ready = False

        seated_ok = self.ready
        response["seated_ok"] = seated_ok
        response["ready"] = self.ready
        # The block message only makes sense while not ready; the lean tip
        # is advisory and can surface either way (folded into `feedback`
        # below, at low priority, whether or not counting has started).
        response["seated_message"] = (
            None if seated_ok else (seated_block_message or lean_tip)
        )

        # ---- leg stability (counting gate only) ----
        leg_stability_point = _leg_stability_point(l_ankle, r_ankle, l_knee, r_knee)
        legs_stable, legs_visible = self._assess_leg_stability(
            leg_stability_point, torso_length, t
        )
        response["legs_stable"] = legs_stable
        response["legs_visible"] = legs_visible
        response["leg_message"] = None if legs_stable else "Keep your legs still."

        # ---- rotation magnitude: self-calibrating shoulder/hip ratio ----
        shoulder_width = _dist(l_shoulder, r_shoulder)
        ratio = _shoulder_hip_ratio(l_shoulder, r_shoulder, l_hip, r_hip)

        # Only recalibrate the baseline while the phase machine is at a
        # CONFIRMED center (self.phase reflects last frame's committed
        # state, not yet updated for this frame) — never while mid-twist.
        # A naive "always decay toward whatever we're currently seeing"
        # approach would slowly absorb a *held* twist into the baseline,
        # eroding the signal to zero the longer a side is held — this is
        # what stops that.
        if self._baseline_ratio is None:
            self._baseline_ratio = max(ratio, BASELINE_RATIO_FLOOR)
        elif self.phase == "center":
            self._baseline_ratio = max(
                ratio, self._baseline_ratio * BASELINE_RATIO_DECAY, BASELINE_RATIO_FLOOR
            )

        ratio_frac = max(0.0, min(1.0, ratio / self._baseline_ratio))
        magnitude_deg = math.degrees(math.acos(ratio_frac))

        # ---- rotation direction: sign only, from two weak-but-cheap votes ----
        direction_vote = _direction_vote(
            l_shoulder, r_shoulder, mid_shoulder, mid_hip, shoulder_width
        )
        sign = 1.0 if direction_vote >= 0 else -1.0
        raw_rotation = DIRECTION_SIGN * sign * magnitude_deg

        if self.smoothed_rotation is None:
            self.smoothed_rotation = raw_rotation
        else:
            self.smoothed_rotation = (
                ANGLE_SMOOTH_ALPHA * raw_rotation
                + (1 - ANGLE_SMOOTH_ALPHA) * self.smoothed_rotation
            )
        response["raw_rotation_deg"] = round(raw_rotation, 1)
        response["torso_rotation_deg"] = round(self.smoothed_rotation, 1)
        response["shoulder_hip_ratio"] = round(ratio, 3)
        response["baseline_ratio"] = round(self._baseline_ratio, 3)

        # ---- adaptive envelope: thresholds scale to what THIS person/setup
        # actually produces, rather than a fixed absolute degree value ----
        self._envelope_deg = max(
            abs(self.smoothed_rotation),
            self._envelope_deg * ENVELOPE_DECAY,
        )
        self._envelope_deg = max(
            ENVELOPE_MIN_DEG, min(ENVELOPE_MAX_DEG, self._envelope_deg)
        )
        response["rotation_envelope_deg"] = round(self._envelope_deg, 1)

        rot_enter = max(ROT_ENTER_FLOOR_DEG, ENTER_FRACTION * self._envelope_deg)
        rot_exit = max(ROT_EXIT_FLOOR_DEG, EXIT_FRACTION * self._envelope_deg)
        rot_partial = max(ROT_PARTIAL_FLOOR_DEG, PARTIAL_FRACTION * self._envelope_deg)

        feedback = framing_message

        if not seated_ok:
            # Not in a valid seated base — track nothing, just coach position.
            if feedback is None:
                feedback = seated_block_message or lean_tip
            self.phase = "center"
            self._candidate_phase = "center"
            self._candidate_streak = 0
            self._attempt_peak_deg = 0.0
            self._attempt_flagged = False
        else:
            rot = self.smoothed_rotation

            # ---- hysteresis phase classification ----
            if self.phase == "center":
                if rot >= rot_enter:
                    target_phase = "left"
                elif rot <= -rot_enter:
                    target_phase = "right"
                else:
                    target_phase = "center"
            else:
                if abs(rot) <= rot_exit:
                    target_phase = "center"
                else:
                    target_phase = self.phase

            if target_phase == self._candidate_phase:
                self._candidate_streak += 1
            else:
                self._candidate_phase = target_phase
                self._candidate_streak = 1

            phase_changed = False
            if (
                self._candidate_streak >= STABLE_FRAMES
                and self._candidate_phase != self.phase
            ):
                previous_phase = self.phase
                self.phase = self._candidate_phase
                phase_changed = True

                if self.phase in ("left", "right"):
                    # ---- a side touch: validate timing + leg stability ----
                    duration = (
                        (t - self._last_phase_change_time)
                        if self._last_phase_change_time is not None
                        else None
                    )
                    self._last_phase_change_time = t

                    valid_timing = (
                        duration is None
                        or MIN_TOUCH_DURATION <= duration <= MAX_TOUCH_DURATION
                    )

                    if not legs_stable:
                        feedback = "Keep your legs still."
                    elif (
                        not valid_timing
                        and duration is not None
                        and duration < MIN_TOUCH_DURATION
                    ):
                        feedback = "Too fast — that twist wasn't counted, control the movement."
                    elif not valid_timing:
                        feedback = "That twist took too long — not counted. Keep the rotation flowing."
                    elif self.phase == self._last_counted_side:
                        feedback = f"Rotate to the other side to keep the rep going."
                    else:
                        side = self.phase
                        if side == "left":
                            self.left_count += 1
                        else:
                            self.right_count += 1
                        response["side_completed"] = True
                        response["side_completed_which"] = side

                        self._touch_count += 1
                        if self._touch_count % 2 == 0:
                            self.rep_count += 1
                            response["rep_completed"] = True
                            feedback = f"Rep {self.rep_count} — nice, keep alternating."
                        else:
                            feedback = f"{side.capitalize()} side — now rotate to the other side."

                        self._last_counted_side = side
                else:
                    self._last_phase_change_time = t

                self._attempt_peak_deg = 0.0
                self._attempt_flagged = False

            # ---- "Rotate further left/right" partial-attempt detection ----
            if not phase_changed and self.phase == "center":
                if abs(rot) > abs(self._attempt_peak_deg):
                    self._attempt_peak_deg = rot
                elif (
                    not self._attempt_flagged
                    and abs(self._attempt_peak_deg) >= rot_partial
                    and abs(self._attempt_peak_deg) < rot_enter
                    and abs(rot) < abs(self._attempt_peak_deg) - rot_exit / 2
                ):
                    self._attempt_flagged = True
                    direction = "left" if self._attempt_peak_deg > 0 else "right"
                    if feedback is None:
                        feedback = f"Rotate further {direction}."

                if abs(rot) < rot_exit / 2:
                    self._attempt_peak_deg = 0.0
                    self._attempt_flagged = False

        response["phase"] = self.phase

        if feedback is None and not seated_ok:
            feedback = (
                "Sit on the floor, lean back slightly with knees bent, and "
                "keep your feet together to start counting."
            )
        if feedback is None and seated_ok and lean_tip:
            feedback = lean_tip
        if feedback is None:
            feedback = "Keep your torso rotating."

        response["feedback"] = feedback
        response["session_complete"] = self._is_complete()
        self.last_timestamp_s = t
        return response


class RussianTwistSession:
    """Full Russian twist session: one shared pose model + one analyzer.

    Same convention as `PushupSession` / `SidePlankSession`: `target_reps`
    / `target_sets` / `set_number` are the coach-assigned plan, supplied
    by the caller from query params. `session_complete` /
    `exercise_complete` are computed here, not on the frontend.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = RussianTwistAnalyzer(target_reps)
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
