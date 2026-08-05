"""
Front Leg Swing — standing hip flexion/extension rep counter, judged from
a side-on view where forward/backward leg movement reads as clean
horizontal displacement.

This is the sagittal-plane sibling of `side_leg_swing.py` (which swings
the leg laterally and needs a FRONT/back-on view). Here the leg swings
forward and back instead of side to side, and that only reads cleanly
from the SIDE — a front-on camera would flatten forward/backward motion
into almost nothing, the exact mirror-image failure mode `view_mode`
guards against on the lateral version, just with the required view
flipped.

Same rep-counting shape as `side_leg_swing.py`: a hard gate decides
whether a rep is even eligible to count, soft flaws tag a counted rep as
`needs_improvement` without blocking it, and — carried over directly from
the accuracy fix made to the lateral version — a rep only counts if the
working foot actually left the ground, not just swung the hip. This is
NOT a hold timer, only reps, same family as push-ups / sumo squats /
side leg swings.

Why "active leg" is picked differently here than in side_leg_swing
----------------------------------------------------------------------
`side_leg_swing.py` picks the working leg by comparing which leg's swing
angle is currently bigger — that works from a front view because both
legs sit side by side in the frame with no occlusion. From a SIDE view,
though, one leg is physically in front of the other from the camera's
perspective for most of the movement, so the far leg's landmarks are
partly occluded and can be noisy/unreliable — the same left/right
ambiguity `side_plank.py` and `hollow_hold.py` already solve for a side-on
torso. So this detector borrows THEIR approach instead: `_pick_active_leg`
picks whichever leg is currently more visible (i.e. the one standing
closer to the camera, unobstructed), with hysteresis to stay on that leg
once picked, and only lets the other leg take over at a safe boundary —
current leg back at rest AND clearly more visible AND the other leg
clearly swinging. In practice this means: **stand side-on with the leg
you're swinging closest to the camera** for the most reliable tracking.

Rep state machine
------------------
Same shape as `side_leg_swing.py`: `stage` is "down" (leg hanging under
the hip, resting) at rest, flips to "out" once the working leg's swing
angle clears `SWING_ANGLE_MIN`, and the rep completes (only then
evaluated) when the leg drops back below `REST_ANGLE_MAX`. Forward swings
and backward swings are graded identically here — only the amplitude of
the swing away from vertical matters, not which direction it went.

Hard gate (must hold for a rep to count at all)
------------------------------------------------
  1. Genuinely side-on to the camera (`view_mode == "side"`) — a
     front-on or angled view is the wrong orientation for THIS exercise
     (opposite requirement from side_leg_swing) and the movement won't
     read reliably.
  2. Framing OK, whole body visible.
  3. The working foot actually left the ground at some point in the
     swing (`FOOT_LIFT_MIN_RATIO`, measured against the stance ankle as
     a live floor reference, exactly like the lateral version) — a leg
     that stays planted and just rocks the hip forward/back doesn't count
     no matter how far the ankle appears to travel.
  4. The working leg actually reached a real peak angle
     (`SWING_PEAK_MIN`) during its "out" phase — not just grazed the
     trigger threshold on landmark noise.
  5. Sane tempo (not a bounce, not a stall).

Soft flaws (rep still counts, tagged `needs_improvement`)
-----------------------------------------------------------
  - Stance-leg knee bending a lot (losing a stable post to swing from).
  - Working leg's knee bending a lot (turning a controlled swing into a
    kick).
  - Torso rocking too far forward/backward (using momentum instead of
    hip mobility/control).
  - Swinging past a sane range (`SWING_TOO_HIGH_DEG`) — usually means
    momentum has taken over from control.
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

# Landmarks used to score each leg's visibility for `_pick_active_leg`.
LEG_LANDMARKS = {
    "left": (LEFT_HIP, LEFT_KNEE, LEFT_ANKLE),
    "right": (RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE),
}

# How much more visible the other leg needs to be before a leg handoff is
# even considered (on top of the motion condition below) — stops a
# marginal visibility flicker from switching legs by itself.
LEG_VISIBILITY_SWITCH_MARGIN = 0.15


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 2  # a side-on view often only clearly shows 2-3


# ---- swing angle thresholds, degrees from vertical ----
REST_ANGLE_MAX = 15.0  # leg hanging under the hip — the "down"/rest stage
SWING_ANGLE_MIN = 25.0  # clears this to enter the "out" stage
SWING_PEAK_MIN = 30.0  # the out-phase must actually PEAK past this to count
SWING_TOO_HIGH_DEG = 65.0  # soft flaw beyond this — momentum, not control
# (higher than side_leg_swing's 55 — a controlled front swing / high-knee
# swing legitimately reaches a bigger angle than a lateral abduction swing)

MIN_REP_DURATION = 0.3  # seconds — faster than this = bouncing/kicking
MAX_REP_DURATION = 5.0  # seconds — slower than this = paused, not a swing

# ---- foot-off-the-ground check (identical idea to side_leg_swing.py) ----
# The stance ankle is resting on the floor for the whole rep, so it's a
# free live floor reference. The working ankle must rise above it by at
# least this fraction of leg length (hip-to-ankle distance) — normalized
# so it doesn't depend on how close the camera is — or the "swing" is
# actually just a hip rock / foot drag and shouldn't count.
FOOT_LIFT_MIN_RATIO = 0.06

# ---- form flaws (soft — counted but tagged) ----
STANCE_KNEE_STRAIGHT_MIN = 160.0
SWING_KNEE_STRAIGHT_MIN = 150.0
TORSO_LEAN_MAX_DEG = 20.0  # degrees from vertical before it's "using momentum"

# ---- view-mode classification ----
# Forward/backward movement needs a SIDE view here — the opposite
# requirement from side_leg_swing.py, which needs front/angled.
#
# BUG THIS FIXES: the first version of this classifier reused
# side_leg_swing.py's shoulder_width/hip_width ratio as-is. That ratio is
# fine for confirming "front" (both terms are large and stable — roughly
# comparable body measurements — so the ratio sits reliably near 1), but
# it's a bad way to confirm "side": in a true profile view BOTH the
# shoulder-to-shoulder distance AND the hip-to-hip distance collapse
# toward zero (the body's width, not its depth, is what a 2D projection
# sees), so the ratio of two small, noisy numbers swings wildly frame to
# frame. `ready` requires STABLE_FRAMES of consecutive "side" reads to
# latch — with a ratio that noisy, it essentially never did, even though
# the pose itself was tracking fine. That's why reps never counted.
#
# The fix: normalize shoulder/hip width against TORSO HEIGHT (the
# shoulder-to-hip vertical span) instead of against each other. Torso
# height barely changes with which way the person is facing — it's
# dominated by standing height, not orientation — so it stays a stable
# denominator. In front view this ratio sits roughly around 0.9-1.1
# (shoulder breadth and trunk length are comparable); turned side-on it
# drops to roughly 0.1-0.3 (only depth/noise remains), a wide, reliable
# gap to threshold on.
SIDE_VIEW_WIDTH_TORSO_MAX = 0.35
FRONT_VIEW_WIDTH_TORSO_MIN = 0.55

# Extra smoothing on top of the better metric — pose-landmark jitter
# alone can still bounce the raw ratio a bit frame to frame, and this is
# cheap insurance against that flickering the classification right at a
# threshold boundary.
VIEW_RATIO_SMOOTHING_ALPHA = 0.35

STABLE_FRAMES = 5  # consecutive good frames before counting turns on
GRACE_FRAMES = 8  # consecutive bad frames tolerated before counting turns off

# Camera framing
FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.97
BBOX_TOO_FAR = 0.12


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


def _leg_visibility(landmarks, side: str) -> float:
    """Lowest visibility score among that leg's hip/knee/ankle — a
    conservative "can we trust this leg's tracking at all" score, used to
    pick the working leg from a side-on view where the far leg is
    partially occluded."""
    scores = []
    for idx in LEG_LANDMARKS[side]:
        v = landmarks[idx].visibility
        scores.append(v if v is not None else 0.0)
    return min(scores) if scores else 0.0


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


def _swing_deg(hip, ankle) -> float:
    """Angle of the hip->ankle segment from straight-down vertical.
    ~0 = leg hanging under the hip; grows toward 90 as the leg swings
    forward or backward toward horizontal. Always positive/unsigned —
    this detector doesn't distinguish forward vs backward, only how far
    the leg swung from rest."""
    dx = abs(ankle.x - hip.x)
    dy = ankle.y - hip.y  # positive while the ankle is below the hip
    return math.degrees(math.atan2(dx, max(dy, 1e-6)))


def _foot_lift_ratio(stance_ankle, swing_ankle, leg_length: float) -> float:
    """How far the working ankle has risen above the stance ankle's
    height, as a fraction of leg length — proof the leg is actually in
    the air rather than rocking from the hip with the foot still down."""
    return (stance_ankle.y - swing_ankle.y) / max(leg_length, 1e-6)


def _torso_tilt_from_vertical_deg(mid_shoulder, mid_hip) -> float:
    dx = abs(mid_hip.x - mid_shoulder.x)
    dy = abs(mid_hip.y - mid_shoulder.y)
    return math.degrees(math.atan2(dx, max(dy, 1e-6)))


def _midpoint(a, b) -> _Point:
    return _Point((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)


def _bbox_aspect_points(points: list[_Point]) -> Optional[tuple[float, float]]:
    if len(points) < 4:
        return None
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    return (max(xs) - min(xs), max(ys) - min(ys))


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

    box = _bbox_aspect_points(points)
    if box is None:
        return None
    width, height = box

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return (
            "You're too close to the camera — back up so your whole body fits in frame."
        )
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


def _view_mode(width_signal: float, torso_height: float) -> str:
    """`width_signal` is the larger of shoulder-width/hip-width (whichever
    is currently more visible/reliable); `torso_height` is the
    shoulder-to-hip span, which stays stable regardless of which way the
    person is facing. See the constants block above for why this
    replaced a shoulder/hip-width ratio."""
    ratio = width_signal / max(torso_height, 1e-6)
    if ratio <= SIDE_VIEW_WIDTH_TORSO_MAX:
        return "side"
    if ratio >= FRONT_VIEW_WIDTH_TORSO_MIN:
        return "front"
    return "angled"


class FrontLegSwingAnalyzer:
    """Stateful front-leg-swing rep counter + visibility-based active-leg
    tracking (see module docstring for why this differs from
    `SideLegSwingAnalyzer`)."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.stage = "down"  # "down" = resting, "out" = mid-swing
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        # Which leg is currently doing the swinging — resolved by
        # visibility (side-on occlusion), see `_pick_active_leg`.
        self.active_leg: Optional[str] = None

        self.last_timestamp_s: Optional[float] = None
        self.rep_start_time: Optional[float] = None
        self.session_start_time: Optional[float] = None

        self._peak_angle: Optional[float] = None
        self._peak_foot_lift: Optional[float] = None
        self._current_rep_issues: set[str] = set()

        self._stance_streak = 0
        self._bad_streak = 0
        self.ready = False
        self._smoothed_view_ratio: Optional[float] = None

    # ---------------------------------------------------------------
    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 2.2:
            return "too_slow"
        if duration >= 1.2:
            return "slow"
        if duration >= 0.5:
            return "good"
        if duration >= 0.3:
            return "fast"
        return "too_fast"

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _pick_active_leg(
        self, landmarks, left_angle: float, right_angle: float
    ) -> None:
        """Pick the working leg primarily by visibility (side-on occlusion
        means the far leg is inherently less trustworthy), with hysteresis
        to avoid flicker, and a motion-gated handoff so switching legs
        between sets doesn't require anything explicit from the user.
        """
        vis = {
            "left": _leg_visibility(landmarks, "left"),
            "right": _leg_visibility(landmarks, "right"),
        }
        angle = {"left": left_angle, "right": right_angle}

        if self.active_leg is None:
            best = max(vis, key=lambda s: vis[s])
            if vis[best] >= MIN_LANDMARK_VISIBILITY:
                self.active_leg = best
            return

        current = self.active_leg
        other = "right" if current == "left" else "left"

        # Current leg still trustworthy and not clearly at-rest-while-the-
        # -other-swings — keep it.
        if vis[current] >= MIN_LANDMARK_VISIBILITY:
            safe_handoff = (
                angle[current] < REST_ANGLE_MAX
                and angle[other] > SWING_ANGLE_MIN
                and vis[other] >= vis[current] + LEG_VISIBILITY_SWITCH_MARGIN
            )
            if safe_handoff:
                self.active_leg = other
            return

        # Current leg lost visibility entirely — fail over to whichever is
        # trustworthy now, if any.
        if vis[other] >= MIN_LANDMARK_VISIBILITY:
            self.active_leg = other

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "view_mode": None,
            "position_ok": False,
            "position_message": None,
            "ready": self.ready,
            "active_leg": self.active_leg,
            "swing_angle": None,
            "left_swing_angle": None,
            "right_swing_angle": None,
            "stance_knee_angle": None,
            "swing_knee_angle": None,
            "foot_lift_ratio": None,
            "foot_lifted": False,
            "torso_tilt_deg": None,
            "torso_upright_ok": True,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_duration": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = (
                "No person detected — step into frame, side-on to the camera."
            )
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        legs_visible = _visible((l_hip, l_knee, l_ankle)) or _visible(
            (r_hip, r_knee, r_ankle)
        )
        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))

        if not legs_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see either leg clearly — step back, side-on to the "
                "camera, so your hips, knees, and ankles are in frame."
            )
            return response

        if not torso_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your torso — make sure your shoulders and hips "
                "are both in frame."
            )
            return response

        response["pose_detected"] = True

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        shoulder_width = _dist(l_shoulder, r_shoulder)
        hip_width = max(_dist(l_hip, r_hip), 1e-6)
        torso_height = _dist(mid_shoulder, mid_hip)

        raw_view_ratio = max(shoulder_width, hip_width) / max(torso_height, 1e-6)
        if self._smoothed_view_ratio is None:
            self._smoothed_view_ratio = raw_view_ratio
        else:
            self._smoothed_view_ratio = (
                VIEW_RATIO_SMOOTHING_ALPHA * raw_view_ratio
                + (1 - VIEW_RATIO_SMOOTHING_ALPHA) * self._smoothed_view_ratio
            )

        view_mode = _view_mode(self._smoothed_view_ratio, 1.0)
        response["view_mode"] = view_mode

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

        side_on = view_mode == "side"
        position_ok_this_frame = side_on and framing_message is None

        if position_ok_this_frame:
            self._stance_streak += 1
            self._bad_streak = 0
        else:
            self._stance_streak = 0
            self._bad_streak += 1

        if self._stance_streak >= STABLE_FRAMES:
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES:
            self.ready = False

        position_ok = self.ready
        response["position_ok"] = position_ok
        response["ready"] = self.ready

        if not side_on:
            position_message = (
                "Turn side-on to the camera — front leg swings need to be "
                "seen from the side to track forward/backward movement."
            )
        elif not position_ok:
            position_message = (
                "Stand side-on to the camera, whole body visible, before "
                "starting your reps."
            )
        else:
            position_message = None
        response["position_message"] = position_message

        # ---- swing angles for both legs ----
        left_swing = _swing_deg(l_hip, l_ankle)
        right_swing = _swing_deg(r_hip, r_ankle)
        response["left_swing_angle"] = round(left_swing, 1)
        response["right_swing_angle"] = round(right_swing, 1)

        self._pick_active_leg(landmarks, left_swing, right_swing)
        response["active_leg"] = self.active_leg

        swing_angle = None
        stance_knee_angle = None
        swing_knee_angle = None
        foot_lift_ratio = None
        if self.active_leg == "left":
            swing_angle = left_swing
            swing_knee_angle = _angle_deg(l_hip, l_knee, l_ankle)
            stance_knee_angle = _angle_deg(r_hip, r_knee, r_ankle)
            leg_length = max(_dist(r_hip, r_ankle), 1e-6)
            foot_lift_ratio = _foot_lift_ratio(r_ankle, l_ankle, leg_length)
        elif self.active_leg == "right":
            swing_angle = right_swing
            swing_knee_angle = _angle_deg(r_hip, r_knee, r_ankle)
            stance_knee_angle = _angle_deg(l_hip, l_knee, l_ankle)
            leg_length = max(_dist(l_hip, l_ankle), 1e-6)
            foot_lift_ratio = _foot_lift_ratio(l_ankle, r_ankle, leg_length)

        response["swing_angle"] = (
            round(swing_angle, 1) if swing_angle is not None else None
        )
        response["stance_knee_angle"] = (
            round(stance_knee_angle, 1) if stance_knee_angle is not None else None
        )
        response["swing_knee_angle"] = (
            round(swing_knee_angle, 1) if swing_knee_angle is not None else None
        )
        response["foot_lift_ratio"] = (
            round(foot_lift_ratio, 3) if foot_lift_ratio is not None else None
        )
        foot_lifted = (
            foot_lift_ratio is not None and foot_lift_ratio >= FOOT_LIFT_MIN_RATIO
        )
        response["foot_lifted"] = foot_lifted

        torso_tilt_deg = _torso_tilt_from_vertical_deg(mid_shoulder, mid_hip)
        response["torso_tilt_deg"] = round(torso_tilt_deg, 1)
        torso_upright_ok = torso_tilt_deg <= TORSO_LEAN_MAX_DEG
        response["torso_upright_ok"] = torso_upright_ok

        feedback = framing_message

        # ---- rep state machine — only progresses in a valid stance/view ----
        rep_completed = False
        rep_duration = rep_class = rep_form_quality = None

        if not position_ok or swing_angle is None:
            if self.rep_start_time is not None:
                self.rep_start_time = None
                self._peak_angle = None
                self._peak_foot_lift = None
                self._current_rep_issues = set()
                if feedback is None:
                    feedback = (
                        "Lost tracking mid-swing — not counted. Reset to "
                        "standing and try again."
                    )
            if feedback is None:
                feedback = (
                    position_message
                    or "Stand still, then swing one leg forward or back."
                )
        else:
            stance_knee_ok = (
                stance_knee_angle is None
                or stance_knee_angle >= STANCE_KNEE_STRAIGHT_MIN
            )
            swing_knee_ok = (
                swing_knee_angle is None or swing_knee_angle >= SWING_KNEE_STRAIGHT_MIN
            )

            if self.stage == "out":
                if self._peak_angle is None or swing_angle > self._peak_angle:
                    self._peak_angle = swing_angle
                if foot_lift_ratio is not None and (
                    self._peak_foot_lift is None
                    or foot_lift_ratio > self._peak_foot_lift
                ):
                    self._peak_foot_lift = foot_lift_ratio
                if not stance_knee_ok:
                    self._current_rep_issues.add("stance_knee_bent")
                if not swing_knee_ok:
                    self._current_rep_issues.add("swing_knee_bent")
                if not torso_upright_ok:
                    self._current_rep_issues.add("torso_lean")
                if swing_angle > SWING_TOO_HIGH_DEG:
                    self._current_rep_issues.add("swing_too_high")

            if self.stage == "down" and swing_angle > SWING_ANGLE_MIN:
                self.stage = "out"
                self.rep_start_time = t
                self._peak_angle = swing_angle
                self._peak_foot_lift = foot_lift_ratio
                self._current_rep_issues = set()
                if not stance_knee_ok:
                    self._current_rep_issues.add("stance_knee_bent")
                if not swing_knee_ok:
                    self._current_rep_issues.add("swing_knee_bent")
                if not torso_upright_ok:
                    self._current_rep_issues.add("torso_lean")
            elif self.stage == "out" and swing_angle < REST_ANGLE_MAX:
                self.stage = "down"
                rep_completed = True

            if feedback is None and self.stage == "out":
                if not foot_lifted:
                    feedback = "Lift your foot off the ground — swing the leg, don't drag or rock it."
                elif not stance_knee_ok:
                    feedback = "Keep your stance leg straight and stable."
                elif not swing_knee_ok:
                    feedback = (
                        "Keep the swinging leg straighter — control it, don't kick."
                    )
                elif not torso_upright_ok:
                    feedback = "Stay upright — don't rock forward or back for momentum."
                elif swing_angle > SWING_TOO_HIGH_DEG:
                    feedback = (
                        "That's a big swing — keep it controlled, not momentum-driven."
                    )

            if rep_completed:
                rep_duration = (
                    (t - self.rep_start_time)
                    if self.rep_start_time is not None
                    else None
                )

                range_reached = (
                    self._peak_angle is not None and self._peak_angle >= SWING_PEAK_MIN
                )
                foot_left_ground = (
                    self._peak_foot_lift is not None
                    and self._peak_foot_lift >= FOOT_LIFT_MIN_RATIO
                )
                valid = (
                    rep_duration is not None
                    and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                    and range_reached
                    and foot_left_ground
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
                        feedback = (
                            f"Clean swing on the {self.active_leg} leg — "
                            f"{rep_class} tempo ({rep_duration:.2f}s)."
                        )
                else:
                    rep_completed = False
                    if rep_duration is not None and rep_duration < MIN_REP_DURATION:
                        feedback = "Too fast — that swing wasn't counted, control the movement."
                    elif rep_duration is not None and rep_duration > MAX_REP_DURATION:
                        feedback = (
                            "That swing took too long — not counted. Keep it flowing."
                        )
                    elif not foot_left_ground:
                        feedback = (
                            "Your foot never left the ground — that reads as a rock, not a "
                            "swing, so it wasn't counted. Lift the leg clear of the floor."
                        )
                    else:
                        feedback = (
                            "Not enough swing height — not counted. Swing further."
                        )

                self.rep_start_time = None
                self._peak_angle = None
                self._peak_foot_lift = None
                self._current_rep_issues = set()

        self.last_timestamp_s = t

        if feedback is None and not self.ready:
            feedback = "Stand side-on to the camera to start counting reps."
        if feedback is None and self.active_leg is None:
            feedback = "Swing one leg forward or back to begin."
        if feedback is None:
            feedback = "Good form — keep going."

        response.update(
            {
                "stage": self.stage,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_duration": rep_duration,
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "feedback": feedback,
            }
        )
        return response


class FrontLegSwingSession:
    """Full front-leg-swing session: one shared pose model + one analyzer.

    `target_reps` / `target_sets` / `set_number` are the coach-assigned
    plan for this user, supplied by the caller (the websocket route, from
    query params) — same convention as `SideLegSwingSession`.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = FrontLegSwingAnalyzer(target_reps)
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
