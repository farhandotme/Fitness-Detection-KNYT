"""
Side Leg Swing — standing hip-abduction rep counter, judged from a
front-on (or back-on) view where lateral leg movement reads as clean
horizontal displacement.

Like `sumo_squat.py`, this is a rep counter with a hard gate deciding
whether a rep is even eligible to count, plus soft flaws that tag a
counted rep as `needs_improvement` without blocking it. It is NOT a hold
timer — there's no target duration here, only reps, exactly like
push-ups and sumo squats.

What's different from sumo squat: there is no single fixed pair of
landmarks driving the rep angle. One leg plants and stays (mostly) still
while the OTHER leg swings out to the side and back — and which leg is
"the working leg" is decided by the movement itself, not fixed in
advance, because a normal session does a set on one leg, switches, then
does a set on the other. See `_resolve_active_leg` for exactly how that
handoff is decided and why it only happens at safe moments (not
mid-swing).

Rep state machine
------------------
`stage` is "down" (leg hanging near the body, resting) at rest, flips to
"out" once the working leg's lateral swing angle clears `SWING_ANGLE_MIN`,
and the rep completes (only then evaluated) when the leg drops back below
`REST_ANGLE_MAX`. Same down-phase-tracks-the-peak / edge-triggered-on-
return shape as every other rep counter in this codebase — nothing counts
from a single good-looking frame, only from a full swing-out-and-back
cycle that actually reached real amplitude.

Hard gate (must hold for a rep to count at all)
------------------------------------------------
  1. Standing upright, camera angle actually shows lateral movement
     (front/angled view — a hard side-on view compresses ab/adduction
     to near nothing, exactly the failure mode `view_mode` exists to
     catch on every detector in this codebase).
  2. Framing OK, whole body visible.
  3. The working leg's foot actually left the ground. Lateral angle
     alone isn't proof of that — a hip sway or a foot dragged sideways
     along the floor can move the ankle sideways without ever lifting
     it, and would otherwise read as a "swing". The stance leg's ankle
     is (by definition of standing on it) resting on the floor for the
     whole rep, so it doubles as a live floor reference: the working
     ankle has to rise measurably above the stance ankle's height
     (`FOOT_LIFT_MIN_RATIO`, normalized by leg length so it doesn't
     depend on camera distance) at some point in the swing, or the rep
     doesn't count no matter how wide the lateral angle got.
  4. The working leg actually reached a real peak angle
     (`SWING_PEAK_MIN`) during its "out" phase — not just grazed the
     trigger threshold on landmark noise.
  4. Sane tempo (not a bounce, not a stall).

Soft flaws (rep still counts, tagged `needs_improvement`)
-----------------------------------------------------------
  - Stance-leg knee bending a lot (losing a stable base to swing from).
  - Working leg's knee bending a lot (turning a controlled swing into a
    kick).
  - Torso leaning too far sideways (using body momentum instead of hip
    abduction strength).
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


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 3


# ---- lateral swing angle thresholds, degrees from vertical ----
REST_ANGLE_MAX = 15.0  # leg hanging near the body — the "down"/rest stage
SWING_ANGLE_MIN = 25.0  # clears this to enter the "out" stage
SWING_PEAK_MIN = 30.0  # the out-phase must actually PEAK past this to count
SWING_TOO_HIGH_DEG = 55.0  # soft flaw beyond this — momentum, not control

MIN_REP_DURATION = 0.3  # seconds — faster than this = bouncing/kicking
MAX_REP_DURATION = 5.0  # seconds — slower than this = paused, not a swing

# ---- foot-off-the-ground check ----
# The stance ankle is resting on the floor for the whole rep, so it's a
# free live floor reference. The working ankle must rise above it by at
# least this fraction of leg length (hip-to-ankle distance) — normalized
# so it doesn't depend on how close the camera is — or the "swing" is
# actually just a hip sway / foot drag and shouldn't count.
FOOT_LIFT_MIN_RATIO = 0.06

# ---- form flaws (soft — counted but tagged) ----
STANCE_KNEE_STRAIGHT_MIN = 160.0  # stance leg should stay a stable, straight post
SWING_KNEE_STRAIGHT_MIN = 150.0  # working leg should swing fairly straight
TORSO_LEAN_MAX_DEG = 20.0  # degrees from vertical before it's "using momentum"

# ---- view-mode classification (shoulder width / hip width) — lateral ----
# movement needs a front-or-back view; a hard side-on view flattens it.
SIDE_VIEW_SHOULDER_HIP_MAX = 0.55
FRONT_VIEW_SHOULDER_HIP_MIN = 0.8

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


def _lateral_swing_deg(hip, ankle) -> float:
    """Angle of the hip->ankle segment from straight-down vertical.
    ~0 = leg hanging by the body; grows toward 90 as the leg swings out
    to horizontal. Always positive/unsigned — direction (left vs right)
    doesn't matter for judging the exercise, only how far out it went."""
    dx = abs(ankle.x - hip.x)
    dy = ankle.y - hip.y  # positive while the ankle is below the hip
    return math.degrees(math.atan2(dx, max(dy, 1e-6)))


def _foot_lift_ratio(stance_ankle, swing_ankle, leg_length: float) -> float:
    """How far the working ankle has risen above the stance ankle's
    height, as a fraction of leg length. Positive = working foot is
    higher off the floor than the (planted) stance foot; ~0 or negative
    = still on (or dragging along) the ground. This is what actually
    proves the leg is "in the air" rather than just swinging sideways
    from the hip while the foot stays down."""
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


def _view_mode(shoulder_width: float, hip_width: float) -> str:
    ratio = shoulder_width / max(hip_width, 1e-6)
    if ratio <= SIDE_VIEW_SHOULDER_HIP_MAX:
        return "side"
    if ratio >= FRONT_VIEW_SHOULDER_HIP_MIN:
        return "front"
    return "angled"


class SideLegSwingAnalyzer:
    """Stateful side-leg-swing rep counter + dynamic active-leg tracking."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.stage = "down"  # "down" = resting, "out" = mid-swing
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        # Which leg is currently doing the swinging — resolved dynamically,
        # see `_resolve_active_leg`. None until the first swing is seen.
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

    def _resolve_active_leg(self, left_angle: float, right_angle: float) -> None:
        """Decide which leg is "the working leg" this frame.

        No leg is committed yet (`active_leg is None`) until one clearly
        swings past rest — this is the calm starting state before the
        first rep. Once a leg is committed, it stays committed (so a run
        of reps on the same leg doesn't jitter between legs on noise)
        UNLESS the current leg is back at rest AND the other leg has
        clearly started swinging — i.e. the handoff only ever happens at
        a safe boundary between reps, never mid-swing.
        """
        if self.active_leg is None:
            if left_angle > right_angle and left_angle > REST_ANGLE_MAX:
                self.active_leg = "left"
            elif right_angle > left_angle and right_angle > REST_ANGLE_MAX:
                self.active_leg = "right"
            return

        if self.active_leg == "left":
            current, other, other_side = left_angle, right_angle, "right"
        else:
            current, other, other_side = right_angle, left_angle, "left"

        if current < REST_ANGLE_MAX and other > SWING_ANGLE_MIN:
            self.active_leg = other_side

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
            response["feedback"] = "No person detected — step into frame."
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        legs_visible = _visible((l_hip, l_knee, l_ankle)) and _visible(
            (r_hip, r_knee, r_ankle)
        )
        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))

        if not legs_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see both legs clearly — step back so your hips, "
                "knees, and ankles are all in frame."
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

        view_mode = _view_mode(shoulder_width, hip_width)
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

        facing_camera = view_mode in ("front", "angled")
        position_ok_this_frame = facing_camera and framing_message is None

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

        if not facing_camera:
            position_message = (
                "Turn to face the camera (front or back-on) — side leg "
                "swings need to be seen from the front to track the "
                "sideways movement."
            )
        elif not position_ok:
            position_message = (
                "Stand facing the camera, whole body visible, before "
                "starting your reps."
            )
        else:
            position_message = None
        response["position_message"] = position_message

        # ---- lateral swing angles for both legs ----
        left_swing = _lateral_swing_deg(l_hip, l_ankle)
        right_swing = _lateral_swing_deg(r_hip, r_ankle)
        response["left_swing_angle"] = round(left_swing, 1)
        response["right_swing_angle"] = round(right_swing, 1)

        self._resolve_active_leg(left_swing, right_swing)
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
                    or "Stand still, then swing one leg out to the side."
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
                    feedback = "Lift your foot off the ground — swing the leg up, don't drag or lean it out."
                elif not stance_knee_ok:
                    feedback = "Keep your stance leg straight and stable."
                elif not swing_knee_ok:
                    feedback = (
                        "Keep the swinging leg straighter — control it, don't kick."
                    )
                elif not torso_upright_ok:
                    feedback = "Stay upright — don't lean away from the swinging leg."
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
                            "Your foot never left the ground — that reads as a lean, not a "
                            "swing, so it wasn't counted. Lift the leg clear of the floor."
                        )
                    else:
                        feedback = (
                            "Not enough swing height — not counted. Swing out further."
                        )

                self.rep_start_time = None
                self._peak_angle = None
                self._peak_foot_lift = None
                self._current_rep_issues = set()

        self.last_timestamp_s = t

        if feedback is None and not self.ready:
            feedback = "Stand facing the camera to start counting reps."
        if feedback is None and self.active_leg is None:
            feedback = "Swing one leg out to the side to begin."
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


class SideLegSwingSession:
    """Full side-leg-swing session: one shared pose model + one analyzer.

    `target_reps` / `target_sets` / `set_number` are the coach-assigned
    plan for this user, supplied by the caller (the websocket route, from
    query params) — same convention as `SumoSquatSession`.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = SideLegSwingAnalyzer(target_reps)
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
