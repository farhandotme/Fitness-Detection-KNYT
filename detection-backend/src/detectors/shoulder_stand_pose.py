"""
Shoulder Stand (Sarvangasana) — inverted-hold timer.

What this exercise actually is
-------------------------------
Lying on the back, the hips and legs lift straight up overhead until the
body forms a vertical column resting on the shoulders/upper back, with
the hands typically supporting the lower back. Unlike every rep-counting
exercise in this codebase, there is no repetitive motion here at all —
the whole exercise IS the held position, so this follows the hold-timer
shape (`plank_hold.py` / `side_plank.py`'s pattern) rather than the
angle-hysteresis rep counters (`pushup.py` / `leg_raise.py` / etc.).

What's actually measured
--------------------------
Four things, all from shoulder/hip/knee/ankle — no face or hand
landmarks are used (see "What this can't check" below):

    1. Inversion — hips positioned clearly above the shoulders in frame.
       This is the single most distinctive, reliable signature of this
       pose vs. literally anything else a person could be doing lying
       on a mat, and it's camera-angle-tolerant since it's just a
       vertical ordering check.
    2. Legs raised — ankles positioned clearly above the hips.
    3. Legs straight — knee angle (hip-knee-ankle) close to a straight
       line, generous threshold, same non-strict-lockout philosophy as
       every other joint-angle check in this codebase.
    4. Body alignment — the ankle-hip-shoulder chain forms a roughly
       straight vertical column (the "candle" cue), not a collapsed or
       tilted-over shape.

Why the strictness is inverted from every other exercise here
-----------------------------------------------------------------
Every rep-counter in this codebase is deliberately permissive-by-default
— missing a correctly performed rep is treated as the worse failure than
occasionally counting a slightly-off one. That calculus flips for a
safety-relevant inverted hold: crediting "held time" to a form that's
actually collapsing (weight rolling onto the neck, legs falling forward)
is worse than being a little quick to pause the timer. So `form_ok` —
the flag that actually gates whether hold time accumulates — reacts
immediately to a real deviation rather than riding out a grace window
the way the other exercises' position gates do. `position_ok` (are they
even attempting the pose at all, used for readiness/UI) keeps the usual
permissive grace-window treatment; it's specifically the moment-to-moment
"is this safe to count as held right now" signal that doesn't.

Pause vs. reset
-----------------
A momentary form break (a knee dips, a small wobble) pauses hold-time
accumulation and gives corrective feedback, but doesn't zero out
progress — same as how a plank hold shouldn't lose the whole set over
one bad second. Only a genuine exit from the pose (hips drop back to
shoulder level or below — no longer inverted at all) resets `hold_time`
to zero and returns to `"not_in_pose"`, since at that point the "hold"
has actually ended, not just wobbled.

What this can't check
-----------------------
No face landmarks are used, so this cannot verify the chin-tuck /
neck-flexion detail (`jalandhara bandha`) that's part of doing this pose
safely — a 2D body-pose skeleton has no reliable signal for head/neck
angle beyond the shoulder line, and guessing at it would be exactly the
kind of overconfident claim this module should not make for something
safety-relevant. That's handled as static instructional copy in the
frontend instead of something graded here. This checks body alignment;
it is not a substitute for learning the pose from a qualified teacher.
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

# Inversion — hips must sit above the shoulders by at least this fraction
# of torso length. A small/ambiguous margin here would mean "barely
# lifted the hips off the floor" could misread as an inversion attempt.
HIP_ABOVE_SHOULDER_MARGIN = 0.15

# Legs raised — ankles above hips by at least this fraction of torso
# length. Distinguishes a real shoulder stand from, say, a bridge pose
# (hips lifted, knees still bent, feet still on the floor).
ANKLE_ABOVE_HIP_MARGIN = 0.30

# Knee straightness (hip-knee-ankle). Generous, not a strict lockout —
# same reasoning as every other joint-angle threshold in this codebase.
KNEE_STRAIGHT_MIN_DEG = 155.0

# Body alignment — deviation of the ankle-hip-shoulder chain from a
# straight vertical line, in degrees. Generous enough for normal body
# proportions and a slightly-off camera angle, tight enough to catch a
# genuinely collapsing/leaning hold.
BODY_ALIGNMENT_TOLERANCE_DEG = 20.0

# Hard exit — hips no longer above shoulders at all. This is not a "form
# is imperfect" signal, it's "the pose has ended"; reaching it resets
# hold_time rather than just pausing it.
HARD_EXIT_MARGIN = 0.0

# Readiness gate (are they even attempting the pose) — this one keeps the
# usual permissive grace window; it's only for UI/readiness, not for
# whether hold time counts. See module docstring.
STABLE_FRAMES = 3
GRACE_FRAMES = 15  # ~0.5s at 30fps

# A real form break should pause accumulation quickly (see module
# docstring for why), but a single noisy frame still shouldn't wipe out
# an otherwise-solid hold — a very short streak requirement absorbs that
# without meaningfully delaying a real pause.
FORM_BREAK_CONFIRM_FRAMES = 3
FORM_RESUME_CONFIRM_FRAMES = 3

# Camera framing. The ankle is deliberately excluded from the top-edge
# check — legs extending toward the top of frame is the entire point of
# this pose, not a framing problem.
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


def _midpoint(a, b) -> _Point:
    return _Point((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _angle_deg(a, b, c) -> float:
    """Angle at vertex `b`, between rays b->a and b->c, in degrees."""
    ang = math.degrees(
        math.atan2(c.y - b.y, c.x - b.x) - math.atan2(a.y - b.y, a.x - b.x)
    )
    ang = abs(ang)
    if ang > 180:
        ang = 360 - ang
    return ang


def _looks_like_a_person(landmarks) -> bool:
    return (
        landmarks[LEFT_SHOULDER].visibility is not None
        and landmarks[LEFT_SHOULDER].visibility > 0.6
        and landmarks[RIGHT_SHOULDER].visibility is not None
        and landmarks[RIGHT_SHOULDER].visibility > 0.6
    )


def _framing_feedback(
    core_points: list[_Point], ankle_points: list[_Point]
) -> Optional[str]:
    """Same edge/too-close/too-far check used elsewhere, except ankles
    skip the top-edge test — see the constants block for why."""
    for p in core_points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — step back so your whole body is visible."
            )

    for p in ankle_points:
        if p.x < FRAME_EDGE_MARGIN or p.x > 1 - FRAME_EDGE_MARGIN:
            return (
                "You're partly out of frame — step back so your whole body is visible."
            )

    all_points = core_points + ankle_points
    if len(all_points) < 4:
        return None

    xs = [p.x for p in all_points]
    ys = [p.y for p in all_points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "You're too close to the camera — step back so your whole body fits in frame."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


def _line_deviation_deg(bottom: _Point, top: _Point) -> float:
    """Angle between the bottom->top vector and straight-up vertical, in
    degrees. 0 = perfectly vertical."""
    dx = top.x - bottom.x
    dy = bottom.y - top.y  # image y is down-positive; "up" is negative dy
    if dx == 0 and dy == 0:
        return 0.0
    return math.degrees(math.atan2(abs(dx), max(dy, 1e-9)))


class ShoulderStandAnalyzer:
    """Stateful inverted-hold timer for Sarvangasana."""

    def __init__(self, target_hold_seconds: Optional[float] = None):
        self.target_hold_seconds = target_hold_seconds

        self.stage = "not_in_pose"  # "not_in_pose" | "adjusting" | "holding"
        self.hold_time = 0.0
        self.best_hold_time = 0.0
        self.interruption_count = 0

        self._last_update_time: Optional[float] = None
        self.session_start_time: Optional[float] = None

        self._attempt_floor_streak = 0
        self._attempt_bad_streak = 0
        self.ready = False  # "attempting the pose at all" — permissive gate

        self._form_ok_streak = 0
        self._form_bad_streak = 0
        self._form_ok_confirmed = False  # the actual gate hold-time accrual uses

    # ---------------------------------------------------------------
    def _is_complete(self) -> bool:
        return (
            self.target_hold_seconds is not None
            and self.hold_time >= self.target_hold_seconds
        )

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)
        dt = 0.0
        if self._last_update_time is not None:
            dt = max(
                0.0, min(t - self._last_update_time, 0.5)
            )  # clamp vs. long stalls/reconnects
        self._last_update_time = t

        response: dict[str, Any] = {
            "pose_detected": False,
            "ready": self.ready,
            "stage": self.stage,
            "hold_time": round(self.hold_time, 1),
            "best_hold_time": round(self.best_hold_time, 1),
            "target_hold_seconds": self.target_hold_seconds,
            "session_complete": self._is_complete(),
            "interruption_count": self.interruption_count,
            "position_ok": False,
            "position_message": None,
            "form_ok": False,
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
            # extra fields
            "hip_inversion_ok": False,
            "legs_raised_ok": False,
            "knee_straight_ok": False,
            "alignment_ok": False,
            "left_knee_angle": None,
            "right_knee_angle": None,
            "body_alignment_deg": None,
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = "No person detected — step into frame."
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        shoulders_visible = _visible((l_shoulder, r_shoulder))
        hips_visible = _visible((l_hip, r_hip))
        if not (shoulders_visible and hips_visible):
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your shoulders and hips clearly — adjust the "
                "camera so your whole body is in frame, filmed from the side."
            )
            return response

        response["pose_detected"] = True

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)

        ankles_visible = _visible((l_ankle, r_ankle))
        knees_visible = _visible((l_knee, r_knee))
        mid_ankle = _midpoint(l_ankle, r_ankle) if ankles_visible else None

        core_points = [
            _Point(p.x, p.y)
            for p in (l_shoulder, r_shoulder, l_hip, r_hip, l_knee, r_knee)
            if _visible((p,))
        ]
        ankle_points = [_Point(p.x, p.y) for p in (l_ankle, r_ankle) if _visible((p,))]
        framing_message = _framing_feedback(core_points, ankle_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        # ---- inversion: the core "is this even the pose" signal ----
        hip_shoulder_gap = (
            mid_shoulder.y - mid_hip.y
        ) / torso_length  # positive = hip above shoulder
        hip_inversion_ok = hip_shoulder_gap >= HIP_ABOVE_SHOULDER_MARGIN
        response["hip_inversion_ok"] = hip_inversion_ok

        is_attempting = hip_shoulder_gap > HARD_EXIT_MARGIN

        if is_attempting:
            self._attempt_floor_streak += 1
            self._attempt_bad_streak = 0
        else:
            self._attempt_floor_streak = 0
            self._attempt_bad_streak += 1

        if self._attempt_floor_streak >= STABLE_FRAMES:
            self.ready = True
        elif self._attempt_bad_streak >= GRACE_FRAMES:
            self.ready = False

        response["ready"] = self.ready
        response["position_ok"] = is_attempting

        if not is_attempting:
            # Genuine exit — the hold has ended, not just wobbled.
            if self.hold_time > self.best_hold_time:
                self.best_hold_time = self.hold_time
            if self.stage != "not_in_pose":
                self.stage = "not_in_pose"
            self.hold_time = 0.0
            self._form_ok_streak = 0
            self._form_bad_streak = 0
            self._form_ok_confirmed = False
            response["position_message"] = (
                "Lie on your back and lift your hips and legs straight "
                "up overhead to begin."
            )
            response["feedback"] = response["position_message"]
            response["stage"] = self.stage
            response["hold_time"] = round(self.hold_time, 1)
            return response

        # ---- legs raised ----
        legs_raised_ok = True
        if mid_ankle is not None:
            ankle_hip_gap = (mid_hip.y - mid_ankle.y) / torso_length
            legs_raised_ok = ankle_hip_gap >= ANKLE_ABOVE_HIP_MARGIN
        response["legs_raised_ok"] = legs_raised_ok

        # ---- knee straightness ----
        knee_straight_ok = True
        if knees_visible and ankles_visible:
            left_knee_angle = _angle_deg(l_hip, l_knee, l_ankle)
            right_knee_angle = _angle_deg(r_hip, r_knee, r_ankle)
            response["left_knee_angle"] = round(left_knee_angle, 1)
            response["right_knee_angle"] = round(right_knee_angle, 1)
            knee_straight_ok = (
                left_knee_angle >= KNEE_STRAIGHT_MIN_DEG
                and right_knee_angle >= KNEE_STRAIGHT_MIN_DEG
            )
        response["knee_straight_ok"] = knee_straight_ok

        # ---- body alignment ("candle" check) ----
        alignment_ok = True
        if mid_ankle is not None:
            deviation = _line_deviation_deg(mid_shoulder, mid_ankle)
            response["body_alignment_deg"] = round(deviation, 1)
            alignment_ok = deviation <= BODY_ALIGNMENT_TOLERANCE_DEG
        response["alignment_ok"] = alignment_ok

        form_ok_this_frame = (
            hip_inversion_ok and legs_raised_ok and knee_straight_ok and alignment_ok
        )

        # Fast-to-pause, slightly-debounced-to-resume — see module
        # docstring for why this exercise's strictness runs the opposite
        # direction from the rest of this codebase's rep counters.
        if form_ok_this_frame:
            self._form_ok_streak += 1
            self._form_bad_streak = 0
        else:
            self._form_bad_streak += 1
            self._form_ok_streak = 0

        was_confirmed = self._form_ok_confirmed
        if self._form_ok_streak >= FORM_RESUME_CONFIRM_FRAMES:
            self._form_ok_confirmed = True
        elif self._form_bad_streak >= FORM_BREAK_CONFIRM_FRAMES:
            self._form_ok_confirmed = False

        if was_confirmed and not self._form_ok_confirmed:
            self.interruption_count += 1

        response["form_ok"] = self._form_ok_confirmed

        feedback = framing_message

        if self._form_ok_confirmed:
            self.stage = "holding"
            self.hold_time += dt
            if feedback is None:
                if (
                    self.target_hold_seconds is not None
                    and self.hold_time >= self.target_hold_seconds
                ):
                    feedback = "Hold complete — great work, come down with control."
                else:
                    feedback = "Great form — hold steady."
        else:
            self.stage = "adjusting"
            if feedback is None:
                if not hip_inversion_ok:
                    feedback = "Lift your hips higher — get fully inverted over your shoulders."
                elif not legs_raised_ok:
                    feedback = (
                        "Raise your legs further — extend them straight up overhead."
                    )
                elif not knee_straight_ok:
                    feedback = "Straighten your knees — keep your legs fully extended."
                elif not alignment_ok:
                    feedback = "Keep your body in one straight vertical line — don't let your legs drift."
                else:
                    feedback = (
                        "Adjusting — hold steady in the full position to resume timing."
                    )

        response["stage"] = self.stage
        response["hold_time"] = round(self.hold_time, 1)
        response["best_hold_time"] = round(max(self.best_hold_time, self.hold_time), 1)
        response["session_complete"] = self._is_complete()
        response["interruption_count"] = self.interruption_count
        response["feedback"] = feedback

        return response


class ShoulderStandSession:
    """Full Shoulder Stand session: one shared pose model + one analyzer.

    Same convention as the other exercises — `target_hold_seconds` /
    `target_sets` / `set_number` are the coach-assigned plan, supplied by
    the websocket route from query params. The frontend never decides on
    its own whether a set/exercise is done; `session_complete` and
    `exercise_complete` are computed here.
    """

    def __init__(
        self,
        target_hold_seconds: Optional[float] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = ShoulderStandAnalyzer(target_hold_seconds)
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
