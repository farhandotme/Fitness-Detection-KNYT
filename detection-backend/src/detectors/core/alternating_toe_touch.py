"""
Alternating Toe Touch — a supine core exercise. Lying on the back, legs
extended upward (roughly perpendicular to the floor) and slightly apart,
arms reaching overhead. Brace the abs, exhale, lift the shoulder blades
off the floor, and reach the RIGHT hand toward the LEFT foot (opposite
arm stays extended toward the ceiling). Lower back down under control,
then repeat reaching the LEFT hand toward the RIGHT foot. Continue
alternating sides.
(References: https://www.exerciselibrary.com/exercise/alternating-toe-touches/,
https://www.thegymgroup.com/exercises/abs-and-core-exercises/how-to-do-toe-touches/,
https://fitbod.me/exercises/opposite-leg-toe-touch)

Why this is a REP exercise, not a hold
------------------------------------------
Unlike battle rope waves (one unbroken motion with no rest point) or a
plank (a single static position held), this movement has a genuine,
described start/end per side: reach -> "lower yourself under control" ->
repeat on the other side. That's a rest position (arms overhead, legs
up, no reach) between every rep, same shape as every rep-based analyzer
in this codebase (sit-up, squat jacks, seated cable shrug) — a rep
completes on the return to rest, not continuously like the battle rope.

Why the signal is a hand-to-opposite-foot DISTANCE, not a direction
------------------------------------------------------------------------
Every other rep-based analyzer here assumes a known camera orientation
(standing, front-facing) because that's a safe assumption for a standing
exercise. A supine floor exercise has no such guarantee — the camera
could be positioned above the person's head, near their feet, angled
from the side, or overhead looking straight down, and "up" in the real
world does not reliably correspond to any single consistent direction in
image space across those setups. Rather than guess a camera angle and
risk the same "unreachable/wrong-direction threshold" mistake that broke
the seated cable shrug (see that analyzer's docstring), this analyzer
uses signals that stay meaningful regardless of camera placement:

  * Hand-to-opposite-foot distance, normalized by a robust body-scale
    reference (see below) — a PROXIMITY, not a "wrist is above/below
    shoulder" directional check. It shrinks toward zero at a genuine
    touch and is large at the "arms overhead, legs up" rest position,
    regardless of which way the camera happens to be pointed.
  * Joint angles (knee angle for the "keep your legs straight" flaw)
    are rotation-invariant by construction — the angle at a vertex
    between two rays doesn't change no matter how the whole body is
    oriented in the frame.

Scale reference: shoulder_width alone is NOT enough
---------------------------------------------------------
The first version normalized proximity by shoulder_width alone. That
broke down hard in a SIDE/PROFILE camera view — confirmed directly from
a production screenshot showing exactly this setup (camera to the side,
legs diagonal across the frame, torso along a single plane): in a
side-on 2D projection, the left and right shoulders nearly coincide, so
shoulder_width collapses toward a small, noisy value. Dividing by that
tiny number inflates every reach ratio, and a realistic (non-
mathematically-perfect) touch that would easily clear the threshold in a
front view instead measures many multiples over it — verified directly:
the same reach that should register a touch computed a ratio of 7.6
against a threshold of 1.6 once shoulder_width collapsed to ~0.014 in a
profile shot. That's what produced "only one side counts" — not a
threshold miscalibration, but the scale reference itself becoming
unreliable for whichever pairing happened to be more side-on in a given
setup.

The fix: use `max(shoulder_width, torso_length)` as the scale reference.
torso_length (mid-shoulder to mid-hip, a length along the body's main
axis) stays meaningful in a profile view where shoulder_width doesn't;
shoulder_width remains the better reference in a front-on/overhead view.
Taking the larger of the two adapts to whichever camera angle is
actually in use instead of assuming one.

This also means, deliberately, there is NO "must be lying down" /
"must be horizontal" gate here the way the plank analyzer requires a
horizontal torso — that check assumes image-y maps to real-world
vertical, which an overhead-mounted camera would violate outright, and
getting it wrong would silently block genuinely correct reps for a
buildable subset of real camera setups. Readiness instead depends only
on all the needed joints being visible and confidently tracked, which
holds regardless of camera placement.

Rep counting: like every other alternating exercise here (battle rope
waves before its own hold-timer rebuild, alternating lateral concepts),
the core signal is a single relative scalar rather than a joint
condition requiring both proximities to independently cross thresholds
on the same frame — that joint-AND mistake is exactly what made the
first cut of the battle rope analyzer nearly unreachable for a real rep.
Here the phase machine has three states instead of two (rest / reaching
right / reaching left), each with its own condition, debounced the same
way as every other phase machine in this codebase.

Cheat-form detection (per the exercise's own cues)
-----------------------------------------------------
* Shallow reach (never gets genuinely close to the opposite foot) ->
  flagged, still counted — a real, if imperfect, attempt is still a rep,
  same tiering as every analyzer here.
* "Bending the knees excessively" (exerciselibrary.com) instead of
  keeping the legs straight -> tracked via knee angle.
* Not alternating sides (same side touched twice in a row) -> flagged;
  the description is explicit that the exercise alternates.
* "Using momentum instead of control" (exerciselibrary.com) -> tracked
  via rep tempo, same MIN/MAX duration validity check used everywhere
  else, tuned to a controlled ab-exercise pace rather than a cardio one.
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    LEFT_WRIST,
    PoseEngine,
    RIGHT_ANKLE,
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


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 3


# ---- readiness gating ----
STABLE_READY_FRAMES = 5
GRACE_FRAMES = 20  # ~0.65s of tolerance for a brief tracking hiccup
# before dropping "ready" mid-rep — a lesson carried over from every
# other analyzer here: a hair-trigger grace period silently drops real
# reps on a real webcam.

# ---- reach-proximity thresholds, as a fraction of shoulder width ----
# proximity = dist(wrist, opposite ankle) / shoulder_width. Shoulder
# width is a stable scale reference that doesn't change during the reach
# itself, the same trick used by every other analyzer here (hip drift in
# the shrug, stance ratio in squat jacks / battle rope).
TOUCH_MAX_RATIO = 1.6  # hand must get within this many shoulder-widths
# of the opposite foot to register a touch at all — deliberately
# generous. The pose landmark sits at the ANKLE, not the toe, and a real
# reach (imperfect flexibility, a beginner's shorter range, ordinary
# landmark noise) rarely closes the distance as tightly as an idealized
# touch would; requiring near-zero residual distance here would repeat
# the exact "unreachable required threshold" mistake that silently
# zeroed out the seated cable shrug counter. A token half-hearted gesture
# toward the feet still doesn't clear this.
NEUTRAL_MIN_RATIO = 2.4  # both hand-to-opposite-foot distances must
# reach at least this far apart to confirm the rest position (arms
# overhead, legs up, no reach in progress) — kept with a clear margin
# above TOUCH_MAX_RATIO so the dead zone between them stays wide enough
# to debounce cleanly.
FULL_TOUCH_RATIO = 0.9  # rewards a genuinely close, real touch — counts
# either way, only affects the shallow_reach quality flag.

CONFIRM_FRAMES = 2  # consecutive agreeing frames before a phase change
# is confirmed.

MIN_REP_DURATION = 0.4  # seconds — this is controlled ab work ("using
# momentum instead of control" is explicitly called out as a mistake —
# exerciselibrary.com), not a cardio movement; too fast isn't valid form.
MAX_REP_DURATION = 4.0  # seconds — a slow, deliberate rep still counts.

# ---- cheat-form thresholds (quality flags, do not block counting) ----
KNEE_STRAIGHT_MIN_DEG = 150.0  # knees must stay at least this straight
# through the rep, or it reads as "bending the knees excessively"
# (exerciselibrary.com) rather than keeping the legs straight.

# ---- camera framing ----
FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_FAR = 0.12


class _Point:
    __slots__ = ("x", "y")

    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y


def _midpoint(a, b) -> _Point:
    return _Point((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _visible(points) -> bool:
    for p in points:
        if p is None:
            return False
        v = getattr(p, "visibility", None)
        if v is not None and v < MIN_LANDMARK_VISIBILITY:
            return False
    return True


def _angle_at(a, b, c) -> Optional[float]:
    """Angle at vertex b, between rays b->a and b->c, in degrees.
    Rotation-invariant by construction — unaffected by camera
    orientation, which matters a lot for a supine exercise (see module
    docstring)."""
    first = (a.x - b.x, a.y - b.y)
    second = (c.x - b.x, c.y - b.y)
    first_len = math.hypot(*first)
    second_len = math.hypot(*second)
    if first_len < 1e-7 or second_len < 1e-7:
        return None
    cosine = (first[0] * second[0] + first[1] * second[1]) / (first_len * second_len)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _framing_feedback(points: list) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — reposition so your whole "
                "body, hands to feet, stays visible."
            )

    # No "too close" bbox-span check here on purpose. This exercise
    # extends limbs in BOTH directions at once (arms reaching overhead,
    # legs extended straight up), so its natural in-frame span is much
    # larger than a standing exercise's — a genuinely well-framed setup
    # with real margin at both edges (nothing clipped) still measures a
    # span of ~0.95 out of 1.0, right against a 0.97 cutoff. That made
    # the check trip under completely normal, correct use and permanently
    # block readiness — the actual bug behind reps not counting at all.
    # The edge-margin check above already catches real clipping, which is
    # the signal that actually matters for trackability.
    if len(points) < 4:
        return None

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    span = max(width, height)

    if span < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class AlternatingToeTouchAnalyzer:
    """Stateful alternating-toe-touch rep counter. No auto-calibration
    and no assumed camera orientation — the reach signal (hand-to-
    opposite-foot distance over shoulder width) and the leg-straightness
    signal (a joint angle) are both meaningful regardless of how the
    camera is positioned relative to a person lying down, plus cheat-
    form flags for a shallow reach, bent knees, and not alternating
    sides."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        # "neutral" (rest — arms overhead, legs up) / "reaching_right"
        # (right hand toward left foot) / "reaching_left"
        self.phase = "neutral"
        self._pending_phase: Optional[str] = None
        self._pending_streak = 0

        self.rep_start_time: Optional[float] = None
        self.session_start_time: Optional[float] = None

        # Readiness gating
        self._ready_streak = 0
        self._bad_streak = 0
        self._visibility_bad_streak = 0
        self.ready = False

        # Per-rep quality tracking
        self._rep_closest_ratio: Optional[float] = None  # closest
        # hand-to-opposite-foot approach reached during the reach phase
        # currently in progress.
        self._rep_min_knee_angle: Optional[float] = None

        self._last_touched_side: Optional[str] = None  # for the
        # not_alternating flaw — which side the PREVIOUS completed rep
        # reached toward.

    # ---------------------------------------------------------------
    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 3.0:
            return "too_slow"
        if duration >= 1.6:
            return "slow"
        if duration >= 0.7:
            return "good"
        if duration >= MIN_REP_DURATION:
            return "fast"
        return "too_fast"

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _reset_rep_trackers(self) -> None:
        self._rep_closest_ratio = None
        self._rep_min_knee_angle = None

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "position_ok": False,
            "position_message": None,
            "ready": self.ready,
            "phase": self.phase,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_duration": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "rep_flaws": [],
            "right_reach_ratio": None,
            "left_reach_ratio": None,
            "knee_angle": None,
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            self._visibility_bad_streak += 1
            if self._visibility_bad_streak >= GRACE_FRAMES:
                self._invalidate_in_progress_rep()
                self.ready = False
            response["feedback"] = (
                "No person detected — lie in view of the camera with your "
                "whole body, hands to feet, visible."
            )
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
        if not torso_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._visibility_bad_streak += 1
            if self._visibility_bad_streak >= GRACE_FRAMES:
                self._invalidate_in_progress_rep()
                self.ready = False
            response["feedback"] = (
                "Can't see your torso clearly — make sure your shoulders "
                "and hips are both in frame."
            )
            return response

        limbs_visible = _visible((l_wrist, r_wrist, l_knee, r_knee, l_ankle, r_ankle))
        if not limbs_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._visibility_bad_streak += 1
            if self._visibility_bad_streak >= GRACE_FRAMES:
                self._invalidate_in_progress_rep()
                self.ready = False
            response["feedback"] = (
                "Can't see your hands and feet clearly — reposition so "
                "your whole body is in frame."
            )
            return response

        response["pose_detected"] = True
        self._visibility_bad_streak = 0

        # ---- scale reference: robust to camera angle ----
        # shoulder_width alone breaks down in a SIDE/PROFILE camera view
        # (confirmed as a real setup people use for this exercise): the
        # left and right shoulders nearly coincide in a side-on 2D
        # projection, so shoulder_width collapses toward a small, noisy
        # value there — which inflates every reach ratio computed from it
        # and can make one cross-body direction's touch threshold
        # effectively unreachable while the other still works, exactly
        # the "only one side counts" symptom. torso_length (shoulder to
        # hip, along the body's main axis) stays meaningful in a profile
        # view where shoulder_width doesn't, while shoulder_width remains
        # the better reference in a front-on/overhead view where torso
        # foreshortening can be more severe. Taking the larger of the two
        # gives a scale reference that stays reliable regardless of which
        # angle the camera actually is at.
        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        shoulder_width = _dist(l_shoulder, r_shoulder)
        torso_length = _dist(mid_shoulder, mid_hip)
        scale = max(shoulder_width, torso_length, 1e-6)

        # Right hand toward LEFT foot, and left hand toward RIGHT foot —
        # the described cross-body pattern.
        right_reach_ratio = _dist(r_wrist, l_ankle) / scale
        left_reach_ratio = _dist(l_wrist, r_ankle) / scale

        left_knee_angle = _angle_at(l_hip, l_knee, l_ankle)
        right_knee_angle = _angle_at(r_hip, r_knee, r_ankle)
        knee_angles = [a for a in (left_knee_angle, right_knee_angle) if a is not None]
        knee_angle = sum(knee_angles) / len(knee_angles) if knee_angles else None

        framing_points = [
            l_shoulder,
            r_shoulder,
            l_hip,
            r_hip,
            l_wrist,
            r_wrist,
            l_ankle,
            r_ankle,
        ]
        framing_message = _framing_feedback(framing_points)
        framing_ok = framing_message is None

        if framing_ok:
            self._ready_streak += 1
            self._bad_streak = 0
        else:
            self._ready_streak = 0
            self._bad_streak += 1

        if self._ready_streak >= STABLE_READY_FRAMES:
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES:
            if self.ready:
                self._invalidate_in_progress_rep()
            self.ready = False

        position_message: Optional[str] = None
        if not framing_ok:
            position_message = framing_message
        elif not self.ready:
            position_message = (
                "Get into position — lying down, in view of the camera, to begin."
            )

        position_ok = self.ready and framing_ok
        response.update(
            {
                "position_ok": position_ok,
                "position_message": position_message,
                "ready": self.ready,
                "right_reach_ratio": round(right_reach_ratio, 3),
                "left_reach_ratio": round(left_reach_ratio, 3),
                "knee_angle": round(knee_angle, 1) if knee_angle is not None else None,
                "framing_ok": framing_ok,
                "framing_message": framing_message,
            }
        )

        if not self.ready:
            response["feedback"] = position_message
            return response

        # ---- per-rep quality trackers: reset continuously while at rest
        # (phase == "neutral") so they're correctly primed the moment a
        # reach begins, and accumulate through the whole reach — the same
        # "reset only on return-to-rest, not on reach-confirmation" fix
        # already learned from the seated cable shrug analyzer.
        if self.phase == "neutral":
            self._rep_closest_ratio = None
            self._rep_min_knee_angle = None

        if self.phase in ("reaching_right", "reaching_left") or self._pending_phase in (
            "reaching_right",
            "reaching_left",
        ):
            active_ratio = (
                right_reach_ratio
                if (
                    self.phase == "reaching_right"
                    or self._pending_phase == "reaching_right"
                )
                else left_reach_ratio
            )
            self._rep_closest_ratio = (
                active_ratio
                if self._rep_closest_ratio is None
                else min(self._rep_closest_ratio, active_ratio)
            )
            if knee_angle is not None:
                self._rep_min_knee_angle = (
                    knee_angle
                    if self._rep_min_knee_angle is None
                    else min(self._rep_min_knee_angle, knee_angle)
                )

        # ---- phase candidate ----
        # Which candidate makes sense depends on where we currently are:
        # from "neutral", either side reaching independently starts a rep.
        # From an active reach, only THAT side's return to its own resting
        # ratio should confirm "neutral" again -- the other arm never
        # moved, so its absolute position is irrelevant to whether the
        # active side has come back to rest. Requiring BOTH sides to
        # independently clear NEUTRAL_MIN_RATIO at once (the previous
        # design) meant one arm's natural resting extension coming in
        # slightly short (a shorter reach, a camera angle, simply not
        # extending as far overhead) could permanently block "neutral"
        # from ever being confirmed after a reach on the OTHER, perfectly
        # fine side -- silently zeroing out that side's count entirely.
        if self.phase == "reaching_right":
            if right_reach_ratio >= NEUTRAL_MIN_RATIO:
                candidate_phase = "neutral"
            elif right_reach_ratio <= TOUCH_MAX_RATIO:
                candidate_phase = "reaching_right"
            else:
                candidate_phase = None  # dead zone — mid-return, don't force a flip
        elif self.phase == "reaching_left":
            if left_reach_ratio >= NEUTRAL_MIN_RATIO:
                candidate_phase = "neutral"
            elif left_reach_ratio <= TOUCH_MAX_RATIO:
                candidate_phase = "reaching_left"
            else:
                candidate_phase = None
        else:  # self.phase == "neutral"
            right_touch = right_reach_ratio <= TOUCH_MAX_RATIO
            left_touch = left_reach_ratio <= TOUCH_MAX_RATIO
            if right_touch and left_touch:
                # Both happen to qualify on the same frame (e.g. a brief
                # mid-transition where the hands cross paths) — go with
                # whichever is genuinely closer, rather than always
                # defaulting to one side.
                candidate_phase = (
                    "reaching_right"
                    if right_reach_ratio <= left_reach_ratio
                    else "reaching_left"
                )
            elif right_touch:
                candidate_phase = "reaching_right"
            elif left_touch:
                candidate_phase = "reaching_left"
            else:
                candidate_phase = None  # dead zone — mid-transition, don't force a flip

        feedback = framing_message
        rep_completed = False
        rep_duration = rep_class = rep_form_quality = None
        rep_flaws: list[str] = []

        if candidate_phase is not None and candidate_phase == self._pending_phase:
            self._pending_streak += 1
        elif candidate_phase is not None:
            self._pending_phase = candidate_phase
            self._pending_streak = 1
        else:
            self._pending_phase = None
            self._pending_streak = 0

        if (
            candidate_phase is not None
            and self._pending_streak >= CONFIRM_FRAMES
            and candidate_phase != self.phase
        ):
            if candidate_phase in ("reaching_right", "reaching_left"):
                self.phase = candidate_phase
                if self.rep_start_time is None:
                    self.rep_start_time = t
                side = "right" if candidate_phase == "reaching_right" else "left"
                feedback = f"Reaching {side} — now lower back down with control."

            else:  # candidate_phase == "neutral": completes a rep if we came from a reach
                if self.phase in ("reaching_right", "reaching_left"):
                    touched_side = "right" if self.phase == "reaching_right" else "left"
                    duration = (
                        (t - self.rep_start_time)
                        if self.rep_start_time is not None
                        else None
                    )
                    valid = (
                        duration is not None
                        and MIN_REP_DURATION <= duration <= MAX_REP_DURATION
                    )

                    if valid:
                        self.rep_count += 1
                        rep_completed = True
                        rep_duration = duration
                        rep_class = self._classify_tempo(duration)

                        if (
                            self._rep_closest_ratio is None
                            or self._rep_closest_ratio > FULL_TOUCH_RATIO
                        ):
                            rep_flaws.append("shallow_reach")
                        if (
                            self._rep_min_knee_angle is not None
                            and self._rep_min_knee_angle < KNEE_STRAIGHT_MIN_DEG
                        ):
                            rep_flaws.append("legs_bending")
                        if (
                            self._last_touched_side is not None
                            and self._last_touched_side == touched_side
                        ):
                            rep_flaws.append("not_alternating")

                        self._last_touched_side = touched_side

                        if rep_flaws:
                            rep_form_quality = "needs_improvement"
                            self.flawed_reps += 1
                            flaw_text = {
                                "shallow_reach": "reach further — really try to get your hand to your foot",
                                "legs_bending": "keep your legs straighter, don't let your knees bend",
                                "not_alternating": "alternate sides — reach the opposite hand next rep",
                            }
                            feedback = (
                                f"Rep {self.rep_count} counted, but "
                                f"{flaw_text[rep_flaws[0]]}."
                            )
                        else:
                            rep_form_quality = "good"
                            self.good_reps += 1
                            feedback = (
                                f"Clean rep — {rep_class} tempo "
                                f"({duration:.2f}s). Rep {self.rep_count}."
                            )
                    else:
                        feedback = (
                            "Too fast — that rep wasn't counted, control the movement."
                            if duration is not None and duration < MIN_REP_DURATION
                            else "Not counted — keep the reach and return continuous."
                        )

                    self.rep_start_time = None

                self.phase = "neutral"
                self._reset_rep_trackers()

        if feedback is None:
            if self.phase != "neutral":
                feedback = "Lower back down with control."
            elif self._is_complete():
                feedback = f"Target reached — {self.target_reps} reps completed."
            else:
                feedback = "Reach one hand toward the opposite foot to begin."

        response.update(
            {
                "phase": self.phase,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_duration": rep_duration,
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "rep_flaws": rep_flaws,
                "feedback": feedback,
            }
        )
        return response

    # ---------------------------------------------------------------
    def _invalidate_in_progress_rep(self):
        """Tracking broke (or person left frame) mid-rep — don't silently
        resume and count a rep that spanned an invalid stretch."""
        self._pending_phase = None
        self._pending_streak = 0
        self.rep_start_time = None
        self._reset_rep_trackers()
        self.phase = "neutral"


class AlternatingToeTouchSession:
    """Full alternating-toe-touch session: one shared pose model + one
    analyzer. Same convention as `SitUpSession` / `SquatJacksSession` /
    `SeatedCableShrugSession` — the coach-assigned plan (`target_reps` /
    `target_sets` / `set_number`) is supplied by the caller (the
    websocket route, from query params), and `session_complete` /
    `exercise_complete` are computed here, not on the frontend.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = AlternatingToeTouchAnalyzer(target_reps)
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
