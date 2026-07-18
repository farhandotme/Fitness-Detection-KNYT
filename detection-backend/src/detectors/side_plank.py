"""
Side plank hold timing + posture correction.

Design
------
Same idea as `plank_hold.py`: a side plank has no reps, it's a single
continuous timed position, so `SidePlankAnalyzer` runs a **hold timer that
only advances while the person is genuinely in a side plank**. The timer
never loses time it already earned — it *pauses* the instant the position
breaks (or the camera loses them) and *resumes* the instant it's good
again. `hold_seconds` only ever goes up; `current_streak_seconds` is the
only thing that resets, so the person always knows how their current
attempt is going without being punished for the whole session.

Why a side plank is filmed differently than a forearm plank
-------------------------------------------------------------
A forearm plank is judged from a profile (side-on) view, because that's
the only angle a straight body-line can be checked from — and that view
only ever shows *one* side of the body clearly.

A side plank is the opposite: the person is lying on their side, so the
camera needs to face the *front* (or back) of their body to see the whole
shape of the pose — both shoulders, both hips, both ankles are usually
visible at once, just at different heights (the "top" arm/hip/leg sits
higher on screen than the "bottom" one that's carrying the weight). So
instead of picking one visible side like the forearm plank does, this
analyzer builds the straight-line check from the **midpoint** of each
left/right pair (shoulder, hip, ankle) — that midpoint is a stable stand-in
for the body's centerline no matter which side is down, and it doesn't
flicker if one side briefly reads a little less clearly than the other.

Kept deliberately simple
-------------------------
Earlier feedback on this app was that exercises were flagging too many
"flaws" and missing valid positions too often. So this analyzer keeps only
ONE thing that can pause the timer — the body not forming a reasonably
straight line (`alignment_angle`, shoulder→hip→ankle) — plus basic camera
framing. Everything else (which elbow is supporting, whether the hips are
sagging vs. piking) is reported as a lighter-weight coaching tip that
affects the form score but never stops the clock, and is only ever raised
when it can be measured with confidence. Bent knees are allowed — that's a
normal, easier variation of the exercise, not a mistake.
"""

import math
from collections import deque
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
)

# -------------------------------------------------------------------------
# Tunable constants
# -------------------------------------------------------------------------

MIN_LANDMARK_VISIBILITY = 0.35

CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)

# ---- body-alignment angle (shoulder-hip-ankle), degrees ----
# Hysteresis band, same pattern as the forearm plank: once holding, only a
# drop below ALIGN_BROKEN pauses the timer; to start (or resume) it has to
# climb back above the higher ALIGN_RESUME. Thresholds are deliberately a
# little looser than the forearm plank's, because a side plank is judged
# from a front-on camera rather than a true profile view, which reads
# slightly less "ruler straight" even with perfect form.
ALIGN_BROKEN = 128.0
ALIGN_RESUME = 145.0
ALIGN_IDEAL = 160.0  # at/above this, hip alignment is "good" tier (no flaw)

# Per-issue form_score penalty (applied per frame while holding). These are
# coaching notes only — they never pause the timer.
MISTAKE_PENALTY = {
    "hip_sag": 18,
    "hip_pike": 14,
    "support_arm": 8,
}

# form_score is sampled into this rolling window roughly once a second so
# `avg_form_score` reflects the last ~SCORE_HISTORY seconds, not the frame
# rate.
SCORE_HISTORY = 30
SCORE_SAMPLE_INTERVAL = 1.0  # seconds

# -------------------------------------------------------------------------
# Camera framing / orientation thresholds — body should read as roughly
# horizontal (lying down) rather than upright (standing).
# -------------------------------------------------------------------------
FRAME_EDGE_MARGIN = 0.03
BODY_SPAN_TOO_CLOSE = 0.92  # shoulder-to-ankle span as a fraction of frame width
BODY_SPAN_TOO_FAR = 0.30
MAX_STANDING_RATIO = 0.85  # |dy|/|dx| of shoulder->ankle above this reads as "standing"


class _Point:
    __slots__ = ("x", "y")

    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y


def _midpoint(a, b) -> _Point:
    return _Point((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)


def _visible(points, min_vis: float = MIN_LANDMARK_VISIBILITY) -> bool:
    for p in points:
        if p is None:
            return False
        v = getattr(p, "visibility", None)
        if v is not None and v < min_vis:
            return False
    return True


def _vis_score(p) -> float:
    v = getattr(p, "visibility", None)
    return v if v is not None else 0.0


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(1 for i in CORE_LANDMARKS if _vis_score(landmarks[i]) > 0.5)
    return visible_core >= 3


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


def _hip_deviation(shoulder, hip, ankle) -> float:
    """Signed vertical deviation of the hip from the straight
    shoulder-ankle line, normalized by body length. Positive = hip sits
    below the line (sagging toward the floor); negative = hip sits above
    it (piking up)."""
    body_len = max(_dist(shoulder, ankle), 1e-6)
    dx = ankle.x - shoulder.x
    if abs(dx) < 1e-6:
        return 0.0
    frac = (hip.x - shoulder.x) / dx
    line_y_at_hip = shoulder.y + frac * (ankle.y - shoulder.y)
    return (hip.y - line_y_at_hip) / body_len


def _ankle_or_knee_midpoint(landmarks) -> Optional[_Point]:
    """Midpoint of both ankles, preferred; falls back to knees if the feet
    are cropped out of frame — same "don't refuse to detect just because
    one point is missing" spirit as the push-up detector."""
    l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]
    if _visible((l_ankle, r_ankle)):
        return _midpoint(l_ankle, r_ankle)
    l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
    if _visible((l_knee, r_knee)):
        return _midpoint(l_knee, r_knee)
    # Last resort: whichever single ankle/knee is visible.
    for p in (l_ankle, r_ankle, l_knee, r_knee):
        if _visible((p,)):
            return _Point(p.x, p.y)
    return None


def _framing_feedback(mid_shoulder, mid_hip, ankle_point) -> Optional[str]:
    """Plain-language camera positioning checks — independent of side
    plank form, since bad framing is why the form math might be unreliable
    in the first place."""
    for p in (mid_shoulder, mid_hip, ankle_point):
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return "Part of you is out of frame — make sure your whole body fits in the shot."

    dx = abs(ankle_point.x - mid_shoulder.x)
    dy = abs(ankle_point.y - mid_shoulder.y)
    if dx > 1e-6 and (dy / dx) > MAX_STANDING_RATIO:
        return (
            "Lie down on your side facing the camera, propped up on your "
            "forearm or hand, so I can see your whole body."
        )

    body_span = math.hypot(dx, dy)
    if body_span > BODY_SPAN_TOO_CLOSE:
        return "You're too close to the camera — move back so your whole body fits in frame."
    if body_span < BODY_SPAN_TOO_FAR:
        return "You're too far from the camera — move a bit closer."

    return None


class SidePlankAnalyzer:
    """Stateful side-plank timer + light posture checker.

    Mirrors `PlankHoldAnalyzer`'s hold-timer contract exactly
    (`hold_seconds` / `session_complete` / etc.) so it slots into the same
    kind of session-and-route wiring as every other timed exercise here.
    """

    def __init__(self, target_seconds: Optional[int] = None):
        self.target_seconds = target_seconds

        self.active_side: Optional[str] = None  # which side is on the ground

        self.hold_active = False
        self.started = False
        self.hold_seconds = 0.0
        self.good_seconds = 0.0
        self.flawed_seconds = 0.0
        self.current_streak_seconds = 0.0
        self.best_streak_seconds = 0.0
        self.break_count = 0

        self.last_timestamp_s: Optional[float] = None
        self.session_start_time: Optional[float] = None

        self._was_complete = False

        self.form_scores: deque[int] = deque(maxlen=SCORE_HISTORY)
        self._last_score_sample_time: Optional[float] = None

    # ---------------------------------------------------------------
    def _is_complete(self) -> bool:
        return (
            self.target_seconds is not None and self.hold_seconds >= self.target_seconds
        )

    def _pick_down_side(self, landmarks) -> Optional[str]:
        """Which side is loaded (touching/near the ground) — read off
        whichever shoulder sits lower on screen (larger y). Sticky toward
        the current side so it doesn't flicker on near-tie frames."""
        l_sh, r_sh = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        if not _visible((l_sh, r_sh), min_vis=0.3):
            return self.active_side
        diff = l_sh.y - r_sh.y  # positive => left is lower on screen
        if abs(diff) < 0.02:
            return self.active_side or ("left" if diff >= 0 else "right")
        return "left" if diff > 0 else "right"

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "active_side": self.active_side,
            "alignment_angle": None,
            "hold_state": (
                "holding"
                if self.started and self.hold_active
                else ("broken" if self.started else "not_started")
            ),
            "is_holding": False,
            "hold_seconds": round(self.hold_seconds, 2),
            "good_seconds": round(self.good_seconds, 2),
            "flawed_seconds": round(self.flawed_seconds, 2),
            "current_streak_seconds": round(self.current_streak_seconds, 2),
            "best_streak_seconds": round(self.best_streak_seconds, 2),
            "break_count": self.break_count,
            "target_seconds": self.target_seconds,
            "session_complete": self._is_complete(),
            "target_reached": False,
            "hold_quality": None,
            "posture_ok": True,
            "posture_issues": [],
            "posture_messages": [],
            "framing_ok": True,
            "framing_message": None,
            "form_score": None,
            "avg_form_score": self._avg(self.form_scores),
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        dt = 0.0
        if self.last_timestamp_s is not None:
            dt = max(0.0, min(t - self.last_timestamp_s, 0.5))
        self.last_timestamp_s = t

        if landmarks is None or not _looks_like_a_person(landmarks):
            self._register_broken_frame()
            response["feedback"] = (
                "I can't see you — step into frame, lying on your side facing the camera."
            )
            response.update(self._progress_fields())
            return response

        response["pose_detected"] = True

        mid_shoulder = _midpoint(landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER])
        mid_hip = _midpoint(landmarks[LEFT_HIP], landmarks[RIGHT_HIP])
        ankle_point = _ankle_or_knee_midpoint(landmarks)

        if ankle_point is None:
            response["low_visibility"] = True
            self._register_broken_frame()
            response["feedback"] = (
                "I can't see your legs clearly — step back so your whole body is in frame."
            )
            response.update(self._progress_fields())
            return response

        self.active_side = self._pick_down_side(landmarks)

        framing_message = _framing_feedback(mid_shoulder, mid_hip, ankle_point)
        alignment_angle = _angle_deg(mid_shoulder, mid_hip, ankle_point)

        align_broken = alignment_angle < (
            ALIGN_BROKEN if self.hold_active else ALIGN_RESUME
        )
        holding_now = framing_message is None and not align_broken

        # ---- lightweight coaching (never pauses the timer) ----
        issues: list[str] = []
        messages: list[str] = []
        if holding_now and alignment_angle < ALIGN_IDEAL:
            deviation = _hip_deviation(mid_shoulder, mid_hip, ankle_point)
            if deviation > 0:
                issues.append("hip_sag")
                messages.append(
                    "Lift your hips a little higher — keep your body in one straight line."
                )
            else:
                issues.append("hip_pike")
                messages.append("Lower your hips slightly — you're piking up too high.")

        if holding_now:
            support_message = self._check_support_arm(landmarks)
            if support_message:
                issues.append("support_arm")
                messages.append(support_message)

        # ---- advance / pause the timer ----
        form_score = None
        hold_quality = None
        if holding_now:
            if not self.hold_active:
                self.current_streak_seconds = 0.0
            self.hold_active = True
            self.started = True

            self.hold_seconds += dt
            self.current_streak_seconds += dt
            if self.current_streak_seconds > self.best_streak_seconds:
                self.best_streak_seconds = self.current_streak_seconds

            if issues:
                self.flawed_seconds += dt
                hold_quality = "needs_improvement"
            else:
                self.good_seconds += dt
                hold_quality = "good"

            form_score = 100
            for issue in issues:
                form_score -= MISTAKE_PENALTY.get(issue, 10)
            form_score = max(0, form_score)

            if (
                self._last_score_sample_time is None
                or t - self._last_score_sample_time >= SCORE_SAMPLE_INTERVAL
            ):
                self.form_scores.append(form_score)
                self._last_score_sample_time = t
        else:
            self._register_broken_frame()

        is_complete = self._is_complete()
        target_reached = is_complete and not self._was_complete
        self._was_complete = is_complete

        # ---- feedback priority: framing > not-in-position > form tips > praise ----
        feedback = framing_message
        if feedback is None and align_broken:
            feedback = (
                "Get into side plank — lie on your side, prop yourself up, "
                "and keep your body in one straight line from shoulders to feet."
            )
        if feedback is None and messages:
            feedback = messages[0]
        if feedback is None and target_reached:
            feedback = f"Target reached — {self.target_seconds}s held, nice work!"
        if feedback is None and holding_now:
            feedback = "Great side plank — keep holding!"
        if feedback is None:
            feedback = "Get back into side plank position to keep the timer going."

        response.update(
            {
                "active_side": self.active_side,
                "alignment_angle": round(alignment_angle, 1),
                "hold_state": "holding" if holding_now else "broken",
                "is_holding": holding_now,
                "target_reached": target_reached,
                "hold_quality": hold_quality,
                "posture_ok": len(issues) == 0,
                "posture_issues": issues,
                "posture_messages": messages,
                "framing_ok": framing_message is None,
                "framing_message": framing_message,
                "form_score": form_score,
                "avg_form_score": self._avg(self.form_scores),
                "feedback": feedback,
            }
        )
        response.update(self._progress_fields())
        return response

    # ---------------------------------------------------------------
    def _check_support_arm(self, landmarks) -> Optional[str]:
        """Soft, best-effort check that the supporting (down-side) elbow
        sits roughly under the shoulder rather than way out or way in.
        Only raised when both points are confidently visible — anything
        uncertain is simply skipped rather than guessed at, so a partly
        hidden arm never gets flagged as wrong."""
        if self.active_side == "left":
            shoulder, elbow = landmarks[LEFT_SHOULDER], landmarks[LEFT_ELBOW]
        elif self.active_side == "right":
            shoulder, elbow = landmarks[RIGHT_SHOULDER], landmarks[RIGHT_ELBOW]
        else:
            return None

        if not _visible((shoulder, elbow), min_vis=0.5):
            return None

        shoulder_width = _dist(landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER])
        if shoulder_width < 1e-6:
            return None

        horizontal_offset = abs(elbow.x - shoulder.x) / shoulder_width
        if horizontal_offset > 0.65:
            return "Bring your supporting elbow in, roughly under your shoulder."
        return None

    def _register_broken_frame(self):
        if self.hold_active:
            self.break_count += 1
        self.hold_active = False
        self.current_streak_seconds = 0.0

    def _progress_fields(self) -> dict[str, Any]:
        return {
            "hold_seconds": round(self.hold_seconds, 2),
            "good_seconds": round(self.good_seconds, 2),
            "flawed_seconds": round(self.flawed_seconds, 2),
            "current_streak_seconds": round(self.current_streak_seconds, 2),
            "best_streak_seconds": round(self.best_streak_seconds, 2),
            "break_count": self.break_count,
            "session_complete": self._is_complete(),
        }

    @staticmethod
    def _avg(values: "deque[int]") -> Optional[int]:
        if not values:
            return None
        return round(sum(values) / len(values))


class SidePlankSession:
    """Full side-plank session: one shared pose model + one analyzer.

    Same `target_seconds` / `target_sets` / `set_number` contract as
    `PlankHoldSession` — the coach-assigned plan is supplied by the caller
    (the websocket route, from query params), and `session_complete` /
    `exercise_complete` are both computed here, never on the frontend.
    """

    def __init__(
        self,
        target_seconds: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = SidePlankAnalyzer(target_seconds)
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
