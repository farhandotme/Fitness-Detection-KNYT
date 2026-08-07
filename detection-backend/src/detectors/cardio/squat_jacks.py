"""
Squat Jacks — a plyometric cardio movement combining a squat with a
jumping jack. Starting position: standing tall, feet together (or close),
arms at the sides. Rep: jump the feet out wider than shoulder-width while
sinking into a shallow-to-moderate squat and raising the arms out/overhead
(the body forms an "X" at the top), then jump back to feet-together,
standing tall with arms back down. That full out-and-back cycle is 1 rep.
(References: https://www.bodi.com/blog/squat-jacks,
https://www.zing.coach/exercises/squat-jacks,
https://fitwill.app/exercise/0785/squat-jacks/)

Why this exercise needs no auto-calibration
--------------------------------------------
Unlike the seated cable shrug, this movement doesn't need a per-person
calibrated baseline at all: both signals that define a rep are already
scale-invariant on their own, the same way the sit-up analyzer's torso
and knee angles are —

  * Squat depth: a knee angle (hip-knee-ankle). 150 degrees means the
    same thing regardless of camera distance or how tall the person is.
  * Stance width: ankle-to-ankle distance normalized by shoulder width
    (a length that doesn't change as the feet move apart) — a ratio of
    1.0 means "feet as wide as the shoulders", consistent across body
    types and camera setups.

So there's no calibration step here, which sidesteps the failure mode
that broke the seated cable shrug analyzer: forced recalibration wiping
an in-progress rep every time tracking briefly hiccupped. The thresholds
below are fixed, biomechanically-grounded fractions from the start.

Threshold reasoning (avoiding the "unreachable threshold" mistake)
---------------------------------------------------------------------
Sources disagree on squat depth for this exercise — some describe a
shallow "quarter squat" (sworkit.com), others a full 90-degree bend
(bodi.com). Because squat jacks are performed at cardio pace ("aim to
move as fast as you can" — fitnessvolt.com), most real reps land
somewhere in between and would be wrongly rejected by requiring textbook
depth on every rep — the same over-strict-threshold mistake that
silently zeroed out the seated cable shrug counter (confirmed there by
simulating a realistic rep and finding it could never cross the
threshold). Here, the REQUIRED depth to count a rep at all is a
generous, clearly-visible bend; genuinely deeper form is rewarded
separately via a non-blocking quality flag instead of gating the count.

Cheat-form detection (per the exercise's own cues)
-----------------------------------------------------
* Shallow, barely-there knee bend at the wide stance -> flagged (but
  still counted) if the deepest point of the rep never passed a
  meaningfully deeper knee-angle threshold than what's required to count.
* Arms not raised overhead at the wide stance -> every source describes
  the "jack" component as raising the arms out/overhead to form an X;
  wrist height relative to the shoulders is tracked through the wide
  phase and flagged if the arms never came up.
* Folding the torso forward over the thighs instead of staying upright
  -> ("keep the chest open ... so the torso does not fold over the
  thighs" — fitwill.app) tracked via torso lean from vertical during
  the squat.

None of these cheat flags block a genuine rep from counting — same
tiering as every other analyzer in this codebase: a rep that reaches a
real wide stance and a real knee bend and returns to standing still
counts, just tagged "needs_improvement" instead of "good" if one of the
above shows up.
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
LEG_LANDMARKS = (LEFT_KNEE, RIGHT_KNEE, LEFT_ANKLE, RIGHT_ANKLE)


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 3


# ---- readiness gating ----
STABLE_READY_FRAMES = 5
GRACE_FRAMES = 25  # ~0.8s of tolerance for a brief tracking hiccup before
# dropping "ready" mid-rep. This is MORE forgiving than the seated cable
# shrug's already-relaxed 20 frames because a jumping, plyometric movement
# causes more motion blur and brief low-confidence frames than a controlled
# seated one, and — per the lesson learned there — a hair-trigger grace
# period silently drops real reps on a real webcam.
MIN_STANDING_INCLINE_DEG = 20.0  # loose sanity check (not the depth gate)
# that the person is roughly upright/standing at all, not lying down or a
# false detection — deliberately loose since forward lean during the squat
# itself is normal and expected.

# ---- squat-depth thresholds (knee angle, hip-knee-ankle) ----
SQUAT_KNEE_MAX_DEG = 155.0  # knee angle must drop to <= this to register
# the wide/squat phase at all — a generous, clearly-visible bend.
SHALLOW_SQUAT_FLAW_ABOVE_DEG = 140.0  # rep still counts, but flagged if the
# deepest point of the rep never got below this (i.e. barely bent at all).
STANDING_KNEE_MIN_DEG = 165.0  # knees must straighten back out to at least
# this to re-arm "standing".

# ---- stance-width thresholds, as a ratio of ankle distance to shoulder
# width. Shoulder width is already a stable, camera-distance-invariant
# scale reference (the same trick the seated cable shrug analyzer uses for
# hip drift), so no calibration is needed here at all.
WIDE_STANCE_MIN_RATIO = 1.05  # ankles must spread to roughly shoulder width
# or beyond, per "jump your feet out to the sides, wider than
# shoulder-width" (zing.coach) / "aim for about 150% of your shoulder
# width" (hitmymacros.com, a related lateral-step variant).
NARROW_STANCE_MAX_RATIO = 0.65  # feet must come back in close together to
# re-arm "standing", per "feet together" (bodi.com, zing.coach).

CONFIRM_FRAMES = 2  # consecutive agreeing frames before a phase change is
# confirmed — lower than the seated cable shrug's 3, because this is a
# fast, plyometric movement where a single rep can be well under a
# second; requiring more confirm frames risks missing real jumps entirely.

MIN_REP_DURATION = 0.25  # seconds — a fast, cardio-pace jump can be this
# quick ("aim to move as fast as you can" — fitnessvolt.com).
MAX_REP_DURATION = 6.0  # seconds — a slow, controlled/beginner-pace rep
# still counts ("keep the tempo slow ... as you build your fitness" —
# puregym.com).

# ---- cheat-form thresholds (quality flags, do not block counting) ----
ARMS_RAISED_MAX_GAP = 0.05  # a wrist must get within this much of shoulder
# height (image-normalized, y grows downward — 0 means level with the
# shoulder, negative means above it) at some point during the wide phase,
# i.e. "raising your arms overhead" (bodi.com, zing.coach).
TORSO_LEAN_FLAW_MAX_DEG = 45.0  # torso incline from vertical must not drop
# below this during the squat, or it reads as folding forward over the
# thighs rather than staying upright ("torso does not fold over the
# thighs" — fitwill.app).

# ---- camera framing ----
FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.97
BBOX_TOO_FAR = 0.10  # lower than the seated/upper-body analyzers' 0.15 —
# this exercise needs the WHOLE body (including feet) in frame with room
# to spread the stance, so the natural framing is already wider/further
# back than a seated close-up shot.


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
    """Angle at vertex b, between rays b->a and b->c, in degrees."""
    first = (a.x - b.x, a.y - b.y)
    second = (c.x - b.x, c.y - b.y)
    first_len = math.hypot(*first)
    second_len = math.hypot(*second)
    if first_len < 1e-7 or second_len < 1e-7:
        return None
    cosine = (first[0] * second[0] + first[1] * second[1]) / (first_len * second_len)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _torso_vertical_incline_deg(mid_shoulder, mid_hip) -> Optional[float]:
    """Degrees from horizontal (90 = perfectly upright, 0 = lying flat)."""
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
                "You're partly out of frame — back up so your whole body, "
                "including your feet, stays visible when you jump wide."
            )

    if len(points) < 4:
        return None

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if height > BBOX_TOO_CLOSE:
        return (
            "You're too close to the camera — back up so your full body fits in frame."
        )
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class SquatJacksAnalyzer:
    """Stateful squat-jacks rep counter. No auto-calibration is needed —
    both the squat-depth (knee angle) and stance-width (ankle distance
    over shoulder width) signals are already scale-invariant — plus
    cheat-form flags for shallow depth, arms not raised, and folding
    forward instead of staying upright."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        # Phase state machine: "narrow_stand" (feet together, top/rest) or
        # "wide_squat" (feet wide + knees bent, bottom/effort)
        self.phase = "narrow_stand"
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
        self._rep_min_knee_angle: Optional[float] = None
        self._rep_min_wrist_gap: Optional[float] = None
        self._rep_min_torso_incline: Optional[float] = None

    # ---------------------------------------------------------------
    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 3.0:
            return "too_slow"
        if duration >= 1.5:
            return "slow"
        if duration >= 0.4:
            return "good"
        if duration >= MIN_REP_DURATION:
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
            "knee_angle": None,
            "left_knee_angle": None,
            "right_knee_angle": None,
            "stance_ratio": None,
            "torso_incline": None,
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
                "No person detected — stand facing the camera with your "
                "whole body, including your feet, visible."
            )
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]

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

        legs_visible = _visible((l_knee, r_knee, l_ankle, r_ankle))
        if not legs_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._visibility_bad_streak += 1
            if self._visibility_bad_streak >= GRACE_FRAMES:
                self._invalidate_in_progress_rep()
                self.ready = False
            response["feedback"] = (
                "Can't see your legs clearly — step back so your knees "
                "and feet are both visible."
            )
            return response

        response["pose_detected"] = True
        self._visibility_bad_streak = 0

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        shoulder_width = max(_dist(l_shoulder, r_shoulder), 1e-6)
        ankle_dist = _dist(l_ankle, r_ankle)
        stance_ratio = ankle_dist / shoulder_width

        left_knee_angle = _angle_at(l_hip, l_knee, l_ankle)
        right_knee_angle = _angle_at(r_hip, r_knee, r_ankle)
        knee_angles = [a for a in (left_knee_angle, right_knee_angle) if a is not None]
        knee_angle = sum(knee_angles) / len(knee_angles) if knee_angles else None

        torso_incline = _torso_vertical_incline_deg(mid_shoulder, mid_hip)

        framing_points = [
            l_shoulder,
            r_shoulder,
            l_hip,
            r_hip,
            l_knee,
            r_knee,
            l_ankle,
            r_ankle,
        ]
        framing_message = _framing_feedback(framing_points)
        framing_ok = framing_message is None

        is_sane = (
            framing_ok
            and torso_incline is not None
            and torso_incline >= MIN_STANDING_INCLINE_DEG
        )
        if is_sane:
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
            position_message = "Stand tall, facing the camera, to begin."

        position_ok = self.ready and framing_ok
        response.update(
            {
                "position_ok": position_ok,
                "position_message": position_message,
                "ready": self.ready,
                "knee_angle": round(knee_angle, 1) if knee_angle is not None else None,
                "left_knee_angle": (
                    round(left_knee_angle, 1) if left_knee_angle is not None else None
                ),
                "right_knee_angle": (
                    round(right_knee_angle, 1) if right_knee_angle is not None else None
                ),
                "stance_ratio": round(stance_ratio, 3),
                "torso_incline": (
                    round(torso_incline, 1) if torso_incline is not None else None
                ),
                "framing_ok": framing_ok,
                "framing_message": framing_message,
            }
        )

        if not self.ready:
            response["feedback"] = position_message
            return response

        # ---- per-rep quality trackers: reset continuously while at rest
        # (phase == "narrow_stand") so they're correctly primed the moment
        # the jump into the squat begins, and accumulate through the whole
        # wide phase — NOT reset only once "wide_squat" is confirmed, which
        # would silently discard the ascent data the cheat flags actually
        # need (this is the fix that had to be retrofitted onto the seated
        # cable shrug analyzer; built in correctly here from the start).
        if self.phase == "narrow_stand":
            self._rep_min_knee_angle = None
            self._rep_min_wrist_gap = None
            self._rep_min_torso_incline = None

        if self.phase == "wide_squat" or self._pending_phase == "wide_squat":
            if knee_angle is not None:
                self._rep_min_knee_angle = (
                    knee_angle
                    if self._rep_min_knee_angle is None
                    else min(self._rep_min_knee_angle, knee_angle)
                )
            wrist_gaps = []
            if _visible((l_wrist,)):
                wrist_gaps.append(l_wrist.y - l_shoulder.y)
            if _visible((r_wrist,)):
                wrist_gaps.append(r_wrist.y - r_shoulder.y)
            if wrist_gaps:
                best_gap = min(wrist_gaps)
                self._rep_min_wrist_gap = (
                    best_gap
                    if self._rep_min_wrist_gap is None
                    else min(self._rep_min_wrist_gap, best_gap)
                )
            if torso_incline is not None:
                self._rep_min_torso_incline = (
                    torso_incline
                    if self._rep_min_torso_incline is None
                    else min(self._rep_min_torso_incline, torso_incline)
                )

        # ---- phase candidate ----
        wide_ok = (
            stance_ratio >= WIDE_STANCE_MIN_RATIO
            and knee_angle is not None
            and knee_angle <= SQUAT_KNEE_MAX_DEG
        )
        narrow_ok = (
            stance_ratio <= NARROW_STANCE_MAX_RATIO
            and knee_angle is not None
            and knee_angle >= STANDING_KNEE_MIN_DEG
        )
        if wide_ok:
            candidate_phase = "wide_squat"
        elif narrow_ok:
            candidate_phase = "narrow_stand"
        else:
            candidate_phase = None  # dead zone — mid-jump, don't force a flip

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
            if candidate_phase == "wide_squat":
                self.phase = "wide_squat"
                if self.rep_start_time is None:
                    self.rep_start_time = t
                feedback = "Wide stance, knees bent — now jump back together."

            else:  # candidate_phase == "narrow_stand": completes a rep if we came from "wide_squat"
                if self.phase == "wide_squat":
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
                            self._rep_min_knee_angle is not None
                            and self._rep_min_knee_angle > SHALLOW_SQUAT_FLAW_ABOVE_DEG
                        ):
                            rep_flaws.append("shallow_squat")
                        if (
                            self._rep_min_wrist_gap is None
                            or self._rep_min_wrist_gap > ARMS_RAISED_MAX_GAP
                        ):
                            rep_flaws.append("arms_not_raised")
                        if (
                            self._rep_min_torso_incline is not None
                            and self._rep_min_torso_incline < TORSO_LEAN_FLAW_MAX_DEG
                        ):
                            rep_flaws.append("folding_forward")

                        if rep_flaws:
                            rep_form_quality = "needs_improvement"
                            self.flawed_reps += 1
                            flaw_text = {
                                "shallow_squat": "sink lower into the squat when your feet land wide",
                                "arms_not_raised": "raise your arms out overhead as your feet jump wide",
                                "folding_forward": "keep your chest up — don't fold forward over your thighs",
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
                            "Too fast — that jump wasn't counted, keep it controlled."
                            if duration is not None and duration < MIN_REP_DURATION
                            else "Not counted — keep the movement continuous."
                        )

                    self.rep_start_time = None

                self.phase = "narrow_stand"

        if feedback is None:
            if self.phase == "wide_squat":
                feedback = "Jump back to feet together, standing tall."
            elif self._is_complete():
                feedback = f"Target reached — {self.target_reps} squat jacks completed."
            else:
                feedback = "Jump your feet out wide into a squat, arms overhead."

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
        self._rep_min_knee_angle = None
        self._rep_min_wrist_gap = None
        self._rep_min_torso_incline = None
        self.phase = "narrow_stand"


class SquatJacksSession:
    """Full squat-jacks session: one shared pose model + one analyzer.
    Same convention as `SitUpSession` / `SeatedCableShrugSession` — the
    coach-assigned plan (`target_reps` / `target_sets` / `set_number`) is
    supplied by the caller (the websocket route, from query params), and
    `session_complete` / `exercise_complete` are computed here, not on
    the frontend.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = SquatJacksAnalyzer(target_reps)
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
