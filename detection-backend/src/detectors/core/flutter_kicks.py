"""
Flutter Kicks — a supine (lying-on-back) core exercise: one leg extends
straight and hovers just off the floor while the other lifts to roughly a
30-60° raise, then the legs swap, over and over. Filmed side-on, exactly
like the reference illustration (position A: right leg up / left leg low,
position B: legs swapped).

Design
------
This is a *rep* counter (no hold timer), but a "rep" here isn't a single
elbow-bend-and-extend like a push-up — it's an **alternation event**: the
leg that's elevated has to swap from one side to the other. That is the
one thing this whole module is built around, because it's exactly the
failure mode the user cares about:

  * If the person is doing real flutter kicks (legs genuinely swapping,
    each held reasonably straight, near the floor / raised at a sane
    height) it MUST count, every time, regardless of which leg they
    happened to start with.
  * If they fake it (same leg twitching, both legs moving together, knees
    tucking into a bicycle-crunch instead of staying straight, or the
    whole body rocking instead of a clean leg swap) it must NOT count.

Like the push-up analyzer's floor-position gate, counting is driven by a
state machine that only progresses while the person is confirmed lying on
their back — losing that position mid-swap invalidates the attempt rather
than silently continuing to count.

Per-leg "how elevated is this leg" signal
------------------------------------------
`thigh_angle` = angle(shoulder, hip, knee) — the angle at the hip between
the torso line and the thigh. Deliberately uses the KNEE as the far point,
not the ankle, so a bent knee doesn't distort the elevation reading (that
is instead its own, separate, straightness check via
angle(hip, knee, ankle)).

When the body is flat on the floor and a leg is fully extended along the
ground (continuing the torso's line), the torso-line and thigh-line point
in opposite directions from the hip, so this angle reads close to 180°.
As the leg lifts off the floor toward the ceiling, this angle shrinks
toward 90° and below. So:

  * near 180°  -> leg is down, extended along/near the floor
  * meaningfully smaller (<= UP_LEG_ANGLE_MAX) -> leg is raised

A leg is only ever classified "up" or "down" through a dead zone between
those two thresholds — a leg mid-swing (neither clearly up nor clearly
down) doesn't force a premature state change, so a single noisy frame
can't flip the count.

Alternation state machine
--------------------------
`self.confirmed_leg` holds whichever leg was last confirmed elevated
("left" / "right" / None before the first swap is ever seen). Every frame
computes a `candidate` — "left" if left is up & right is down, "right" if
right is up & left is down, otherwise None (ambiguous: both up, both
down, or either leg in the dead zone). A candidate only overwrites
`confirmed_leg` after `CONFIRM_FRAMES` consecutive frames agreeing on it,
which absorbs single-frame tracking jitter without needing the user to
pause at either end.

A rep is counted the instant `confirmed_leg` changes to a *different*
non-None value than before — i.e. an actual swap — subject to a realistic
timing window (too fast is a tracking glitch, too slow means the legs
were just resting, not fluttering). Crucially, if the same leg comes back
up again without an intervening swap to the other side, `confirmed_leg`
doesn't change, so nothing is counted — this is what enforces genuine
left-right-left alternation regardless of which side the person started
on, exactly as requested, with no special-casing for which leg goes first.
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


# ---- lying-on-back gate (torso reads horizontal in the side-on frame) ----
# Same idea as the push-up analyzer's floor-position gate, minus the leg
# vertical-ratio vote (legs are *supposed* to move constantly here).
TORSO_INCLINE_LYING_MAX_DEG = 40.0
BBOX_ASPECT_LYING_MIN = 1.05  # width/height of visible-landmark bbox

STABLE_LYING_FRAMES = 5  # consecutive good frames before counting turns on
GRACE_FRAMES = 10  # consecutive bad frames tolerated before counting turns off

# View-mode classification (shoulder width / torso length) — purely
# informational/coaching here, not a hard gate, since the lying + thigh
# angle checks already do the real work.
SIDE_VIEW_RATIO_MAX = 0.45
FRONT_VIEW_RATIO_MIN = 0.85

# ---- thigh-elevation thresholds (angle at hip: shoulder-hip-knee) ----
# NOTE: earlier version required the "down" leg to independently clear an
# absolute ~160 degrees AND the "up" leg to independently clear ~145
# degrees before a candidate would resolve at all. In practice a real
# flutter kick's "down" leg hovers just off the floor rather than lying
# perfectly flat/in-line with the torso, so it often never reached that
# 160 degree bar — the two absolute thresholds could each land in a
# state neither counted as "up" nor "down", leaving `candidate` stuck at
# None (and the displayed `elevated_leg` stuck on stale state) even
# though the kick was genuinely happening. Fixed by judging elevation
# *relative to the other leg* instead: one leg only has to be clearly
# raised AND meaningfully more raised than its partner — it doesn't also
# need the other leg to hit its own separate absolute floor-contact bar.
UP_LEG_ANGLE_MAX = 158.0  # the raised leg must be at least this bent from straight
MIN_LEG_SEPARATION_DEG = 16.0  # and clearly more raised than the other leg

# ---- knee-straightness (form check, angle at knee: hip-knee-ankle) ----
KNEE_STRAIGHT_GOOD = 155.0  # no flaw at/above this
KNEE_BEND_FLAW_BELOW = 120.0  # below this the "kick" reads as a bent-knee
# tuck (bicycle crunch / mountain climber) rather than a flutter kick —
# still counted (it's still a genuine alternation) but flagged as flawed,
# same tiering the push-up analyzer uses for hip sag.

CONFIRM_FRAMES = 2  # consecutive agreeing frames before a candidate side
# becomes the confirmed elevated leg — absorbs jitter without requiring
# the user to pause at either end of the kick.

MIN_SWITCH_DURATION = 0.12  # seconds — faster than this = tracking glitch
MAX_SWITCH_DURATION = 4.0  # seconds — slower than this = legs were just
# resting, not fluttering; still not "wrong", just not a counted rep.

# ---- camera framing ----
FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.95
BBOX_TOO_FAR = 0.15


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


def _torso_incline_deg(mid_shoulder, mid_hip) -> Optional[float]:
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


def _view_mode(shoulder_width: float, torso_length: float) -> str:
    ratio = shoulder_width / max(torso_length, 1e-6)
    if ratio <= SIDE_VIEW_RATIO_MAX:
        return "side"
    if ratio >= FRONT_VIEW_RATIO_MIN:
        return "front"
    return "angled"


def _framing_feedback(points: list[_Point]) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — reposition so your whole body, "
                "shoulders to feet, is visible from the side."
            )

    if len(points) < 4:
        return None

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return (
            "You're too close to the camera — back up so your whole body fits in frame."
        )
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


def _assess_lying(
    torso_incline_deg: Optional[float], bbox_aspect: Optional[float]
) -> bool:
    """Two independent, camera-agnostic votes for 'lying flat on the back,
    read side-on'. Requires agreement (or the only available signal) —
    same conservative voting spirit as the push-up floor-position gate."""
    votes = 0
    total = 0

    if torso_incline_deg is not None:
        total += 1
        if torso_incline_deg <= TORSO_INCLINE_LYING_MAX_DEG:
            votes += 1

    if bbox_aspect is not None:
        total += 1
        if bbox_aspect >= BBOX_ASPECT_LYING_MIN:
            votes += 1

    if total == 0:
        return False
    return votes == total


class FlutterKicksAnalyzer:
    """Stateful flutter-kicks rep counter (rep = one confirmed left<->right
    leg swap) + strict lying-on-back position gate."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        # Alternation state machine
        self.confirmed_leg: Optional[str] = None  # "left" / "right" / None
        self._pending_candidate: Optional[str] = None
        self._pending_streak = 0

        self.rep_count = 0
        self.cycle_count = 0  # rep_count // 2 — full left+right pairs
        self.good_reps = 0
        self.flawed_reps = 0
        self.left_reps = 0  # times a swap landed on "left up"
        self.right_reps = 0

        self.last_switch_time: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None
        self.session_start_time: Optional[float] = None

        # Tracks the worst (most-bent) knee angle of the currently-up leg,
        # to grade the *next* rep's straightness the instant it lands.
        self._current_min_knee_angle: Optional[float] = None

        # Lying-position gating
        self._lying_streak = 0
        self._bad_streak = 0
        self.ready = False

    # ---------------------------------------------------------------
    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 2.0:
            return "too_slow"
        if duration >= 1.0:
            return "slow"
        if duration >= 0.25:
            return "good"
        if duration >= MIN_SWITCH_DURATION:
            return "fast"
        return "too_fast"

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

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
            "left_thigh_angle": None,
            "right_thigh_angle": None,
            "left_knee_angle": None,
            "right_knee_angle": None,
            "left_leg_up": False,
            "right_leg_up": False,
            "elevated_leg": self.confirmed_leg,
            "stage": self.confirmed_leg or "neutral",
            "rep_count": self.rep_count,
            "cycle_count": self.cycle_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "left_reps": self.left_reps,
            "right_reps": self.right_reps,
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
            self._invalidate_in_progress_switch()
            response["feedback"] = (
                "No person detected — lie down in frame, facing the camera from the side."
            )
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
        left_leg_ok = _visible((l_hip, l_knee, l_ankle))
        right_leg_ok = _visible((r_hip, r_knee, r_ankle))

        if not torso_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._invalidate_in_progress_switch()
            response["feedback"] = (
                "Can't see your torso clearly — make sure your shoulders "
                "and hips are both in frame."
            )
            return response

        response["pose_detected"] = True

        if not left_leg_ok or not right_leg_ok:
            response["low_visibility"] = True
            self._invalidate_in_progress_switch()
            response["feedback"] = (
                "Can't see both legs clearly — reposition side-on to the "
                "camera so both legs (hip, knee, ankle) are visible."
            )
            return response

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)
        shoulder_width = _dist(l_shoulder, r_shoulder)

        view_mode = _view_mode(shoulder_width, torso_length)
        response["view_mode"] = view_mode

        torso_incline = _torso_incline_deg(mid_shoulder, mid_hip)

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

        is_lying = _assess_lying(torso_incline, bbox_aspect)

        if is_lying:
            self._lying_streak += 1
            self._bad_streak = 0
        else:
            self._lying_streak = 0
            self._bad_streak += 1

        if self._lying_streak >= STABLE_LYING_FRAMES:
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES:
            self.ready = False
        # else: keep previous `ready` state — short grace period for noise.

        position_ok = self.ready
        response["position_ok"] = position_ok
        response["ready"] = self.ready

        if not position_ok:
            position_message = (
                "Lie flat on your back, filmed from the side — shoulders "
                "and hips level on the floor, legs extended out to the "
                "side of frame."
            )
        else:
            position_message = None
        response["position_message"] = position_message

        # ---- per-leg angles ----
        left_thigh_angle = _angle_deg(l_shoulder, l_hip, l_knee)
        right_thigh_angle = _angle_deg(r_shoulder, r_hip, r_knee)
        left_knee_angle = _angle_deg(l_hip, l_knee, l_ankle)
        right_knee_angle = _angle_deg(r_hip, r_knee, r_ankle)

        response.update(
            {
                "left_thigh_angle": round(left_thigh_angle, 1),
                "right_thigh_angle": round(right_thigh_angle, 1),
                "left_knee_angle": round(left_knee_angle, 1),
                "right_knee_angle": round(right_knee_angle, 1),
            }
        )

        feedback = framing_message

        rep_completed = False
        rep_duration = rep_class = rep_form_quality = None

        if not position_ok:
            self._invalidate_in_progress_switch()
            if feedback is None:
                feedback = position_message
        else:
            # Relative comparison: a leg is "the elevated one" if it's
            # clearly bent from straight AND clearly more raised than its
            # partner by a solid margin — it does NOT also require the
            # other leg to independently clear its own absolute
            # floor-contact angle, which is what let real kicks get stuck
            # in an unresolved state (see note by UP_LEG_ANGLE_MAX above).
            separation = right_thigh_angle - left_thigh_angle  # >0: left more raised

            left_up = (
                left_thigh_angle <= UP_LEG_ANGLE_MAX
                and separation >= MIN_LEG_SEPARATION_DEG
            )
            right_up = (
                right_thigh_angle <= UP_LEG_ANGLE_MAX
                and -separation >= MIN_LEG_SEPARATION_DEG
            )

            if left_up:
                candidate = "left"
            elif right_up:
                candidate = "right"
            else:
                candidate = None

            # ---- track worst knee bend of whichever leg is currently up,
            # so the rep about to land can be graded on it ----
            if candidate == "left":
                if self._current_min_knee_angle is None:
                    self._current_min_knee_angle = left_knee_angle
                else:
                    self._current_min_knee_angle = min(
                        self._current_min_knee_angle, left_knee_angle
                    )
            elif candidate == "right":
                if self._current_min_knee_angle is None:
                    self._current_min_knee_angle = right_knee_angle
                else:
                    self._current_min_knee_angle = min(
                        self._current_min_knee_angle, right_knee_angle
                    )

            # ---- debounce candidate -> confirmed_leg ----
            if candidate is not None and candidate == self._pending_candidate:
                self._pending_streak += 1
            elif candidate is not None:
                self._pending_candidate = candidate
                self._pending_streak = 1
            else:
                self._pending_candidate = None
                self._pending_streak = 0

            if (
                candidate is not None
                and self._pending_streak >= CONFIRM_FRAMES
                and candidate != self.confirmed_leg
            ):
                previous_leg = self.confirmed_leg
                now = t

                if previous_leg is None:
                    # First time we've ever confirmed a side — establishes
                    # the baseline. Not a rep (nothing to alternate from
                    # yet), matches whichever leg the user started with.
                    self.confirmed_leg = candidate
                    self.last_switch_time = now
                    self._current_min_knee_angle = None
                    feedback = (
                        f"Starting position confirmed — {candidate} leg up. "
                        "Now flutter: swap legs to start counting."
                    )
                else:
                    duration = (
                        (now - self.last_switch_time)
                        if self.last_switch_time is not None
                        else None
                    )
                    valid = (
                        duration is not None
                        and MIN_SWITCH_DURATION <= duration <= MAX_SWITCH_DURATION
                    )

                    if valid:
                        self.confirmed_leg = candidate
                        self.last_switch_time = now
                        self.rep_count += 1
                        self.cycle_count = self.rep_count // 2
                        rep_completed = True
                        rep_duration = duration
                        rep_class = self._classify_tempo(duration)

                        if candidate == "left":
                            self.left_reps += 1
                        else:
                            self.right_reps += 1

                        min_knee = self._current_min_knee_angle
                        if min_knee is not None and min_knee < KNEE_BEND_FLAW_BELOW:
                            rep_form_quality = "needs_improvement"
                            self.flawed_reps += 1
                            feedback = (
                                f"Rep {self.rep_count} counted, but keep that leg "
                                f"straighter — it bent to about {min_knee:.0f}°."
                            )
                        else:
                            rep_form_quality = "good"
                            self.good_reps += 1
                            if rep_class in ("good", "fast"):
                                feedback = (
                                    f"Clean flutter — {rep_class} tempo "
                                    f"({duration:.2f}s). Rep {self.rep_count}."
                                )
                            else:
                                feedback = (
                                    f"Good swap, control the tempo "
                                    f"({duration:.2f}s). Rep {self.rep_count}."
                                )

                        self._current_min_knee_angle = None
                    else:
                        # Same side coming back up without a real swap, or
                        # the swap happened way too fast/slow to trust —
                        # not counted, and the "expected" side to alternate
                        # into doesn't change.
                        self.confirmed_leg = candidate
                        self.last_switch_time = now
                        self._current_min_knee_angle = None
                        if duration is not None and duration < MIN_SWITCH_DURATION:
                            feedback = "Too fast — that swap wasn't counted, control the movement."
                        else:
                            feedback = (
                                "Not counted — keep alternating legs continuously "
                                "without pausing too long between swaps."
                            )

            if feedback is None:
                other_leg = "right" if self.confirmed_leg == "left" else "left"
                if self.confirmed_leg is None:
                    feedback = (
                        "Lift one leg and keep the other extended just above "
                        "the floor to begin."
                    )
                else:
                    feedback = f"Keep fluttering — swap to your {other_leg} leg."

        self.last_timestamp_s = t

        response.update(
            {
                "elevated_leg": self.confirmed_leg,
                "stage": self.confirmed_leg or "neutral",
                "left_leg_up": left_up if position_ok else False,
                "right_leg_up": right_up if position_ok else False,
                "rep_count": self.rep_count,
                "cycle_count": self.cycle_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "left_reps": self.left_reps,
                "right_reps": self.right_reps,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_duration": rep_duration,
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "feedback": feedback,
            }
        )
        return response

    # ---------------------------------------------------------------
    def _invalidate_in_progress_switch(self):
        """Position broke (or person left frame) mid-swap — don't let a
        stale pending candidate silently resume and count later."""
        self._pending_candidate = None
        self._pending_streak = 0
        self._current_min_knee_angle = None


class FlutterKicksSession:
    """Full flutter-kicks session: one shared pose model + one analyzer.

    Same convention as `PushupSession` / `SidePlankSession` — the
    coach-assigned plan (`target_reps` / `target_sets` / `set_number`) is
    supplied by the caller (the websocket route, from query params), and
    `session_complete` / `exercise_complete` are computed here, not on the
    frontend.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = FlutterKicksAnalyzer(target_reps)
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
