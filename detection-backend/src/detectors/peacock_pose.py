"""
Peacock Pose (Mayurasana) hold timing + posture correction.

Same family as `PlankHoldAnalyzer` / `SidePlankAnalyzer` / the Standing
Forward Fold analyzer — no reps, a single continuous timed hold, judged
frame by frame, with a **monotonic timer that pauses on a broken frame
and resumes the instant form is correct again** (never resets to zero).

Correction from an earlier version of this file
--------------------------------------------------
An earlier version of this analyzer required the arms to be *straight*
(elbow angle near 180°). That was wrong: it was modeled off photos of a
straight-arm forward-lean hold that isn't actually this pose. Authentic
Mayurasana has the **elbows bent and pressed into the belly/lower ribs**
— roughly a right angle, forearms and hands flat on the floor pointing
back toward the feet — with the torso and legs balanced horizontally on
top of that elbow support. A textbook-correct rep of the real pose was
guaranteed to fail the old straight-arm gate. This version checks for
the real thing.

What the gates are actually checking
--------------------------------------
  * `elbow_angle` (shoulder-elbow-wrist) must sit in a bent range — not
    collapsed flat, not straightened out into a plank. ~90° is the
    archetype.
  * `elbow_tuck_ratio` — distance from elbow to hip, normalized by
    torso length (shoulder-to-hip distance) — must stay small. This is
    the "pressed into the belly" check: a bent elbow held way out to the
    side or way out in front isn't tucked, even if the angle happens to
    read right.
  * `body_line_angle` (shoulder-hip-ankle) must stay straight — the
    torso and legs need to read as one straight line, same alignment
    check plank/push-up already use.
  * `incline_ratio` — the body must be hovering roughly parallel to the
    floor, not steeply angled.

Combined, a bent AND tucked elbow supporting a straight, level body line
is what's actually load-bearing here: geometrically, you cannot rest a
straight torso-and-legs line horizontally on a tucked bent elbow without
the whole body being off the ground — so, same reasoning as the previous
version, there's no need for a separate "are the feet touching the
floor" check.

Only these four break the hold. Everything else is graded as a lighter
form note (deeper tuck / more textbook elbow angle = better
`hold_quality`) without pausing the timer.
"""

import math
from collections import deque
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_SHOULDER,
    LEFT_WRIST,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)

# -------------------------------------------------------------------------
# Tunable constants
# -------------------------------------------------------------------------

MIN_LANDMARK_VISIBILITY = 0.4

SIDE_LANDMARKS = {
    "left": (LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST, LEFT_HIP, LEFT_ANKLE),
    "right": (RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST, RIGHT_HIP, RIGHT_ANKLE),
}
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 2


# ---- elbow bend (shoulder-elbow-wrist), degrees ----
# A *band*, not a one-sided threshold: too straight (a plank) is wrong,
# but so is fully collapsed (elbow folded flat, no longer supporting the
# hover). Hysteresis on both edges, same convention as the other
# hold-based analyzers — only crossing the *_BROKEN_* edge while already
# holding pauses it; has to get back inside the *_RESUME_* edge to
# resume from a broken/not-started state.
ELBOW_BROKEN_LOW = 40.0
ELBOW_RESUME_LOW = 50.0
ELBOW_BROKEN_HIGH = 135.0
ELBOW_RESUME_HIGH = 120.0
ELBOW_IDEAL_LOW = 65.0
ELBOW_IDEAL_HIGH = 105.0  # ~90 degrees is the archetype

# ---- elbow tuck (elbow-to-hip distance / torso length) ----
TUCK_BROKEN_ABOVE = 0.75
TUCK_RESUME_BELOW = 0.60
TUCK_IDEAL_BELOW = 0.55

# ---- body line straightness (shoulder-hip-ankle), degrees ----
# Widened from an earlier version: a 150/160 broken/resume band (10°) was
# too tight for a genuine unassisted balance hold, where the body line
# naturally wobbles a couple of degrees moment to moment. That caused
# real, correctly-held reps to flicker paused/resumed rapidly right at
# the boundary instead of counting smoothly.
BODY_LINE_BROKEN_BELOW = 145.0
BODY_LINE_RESUME_ABOVE = 152.0
BODY_LINE_IDEAL_ABOVE = 165.0

# ---- how level/horizontal the hover is (vertical span / horizontal span) ----
MAX_INCLINE_RATIO = 0.55

MISTAKE_PENALTY = {
    "elbow_angle": 12,
    "not_tucked": 15,
    "body_line": 15,
}

SCORE_HISTORY = 30
SCORE_SAMPLE_INTERVAL = 1.0

# ---- framing (landscape, side-on — same convention as Plank Hold) ----
FRAME_EDGE_MARGIN = 0.03
BODY_SPAN_TOO_CLOSE = 0.95
BODY_SPAN_TOO_FAR = 0.28


def _visible(points) -> bool:
    for p in points:
        if p is None:
            return False
        v = getattr(p, "visibility", None)
        if v is not None and v < MIN_LANDMARK_VISIBILITY:
            return False
    return True


def _side_visibility(landmarks, side: str) -> float:
    scores = []
    for idx in SIDE_LANDMARKS[side]:
        v = landmarks[idx].visibility
        scores.append(v if v is not None else 0.0)
    return min(scores) if scores else 0.0


def _angle_deg(a, b, c) -> float:
    ang = math.degrees(
        math.atan2(c.y - b.y, c.x - b.x) - math.atan2(a.y - b.y, a.x - b.x)
    )
    ang = abs(ang)
    if ang > 180:
        ang = 360 - ang
    return ang


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _framing_feedback(shoulder, hip, ankle, wrist) -> Optional[str]:
    for p in (shoulder, hip, ankle, wrist):
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — step back so your whole body, "
                "hands to feet, fits in the shot."
            )

    dx = abs(ankle.x - shoulder.x)
    dy = abs(ankle.y - shoulder.y)
    body_span = math.hypot(dx, dy)

    if body_span > BODY_SPAN_TOO_CLOSE:
        return "You're too close to the camera — step back until your whole body fits in frame."
    if body_span < BODY_SPAN_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class PeacockPoseAnalyzer:
    """Stateful Peacock Pose hold timer + posture checker.

    No `target_reps` — the coach-assigned target is a duration,
    `target_seconds`. `session_complete` is `hold_seconds >= target_seconds`,
    exactly mirroring the other hold-based analyzers in this codebase.
    """

    def __init__(self, target_seconds: Optional[int] = None):
        self.target_seconds = target_seconds

        self.active_side: Optional[str] = None

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

    def _pick_active_side(self, landmarks) -> Optional[str]:
        vis = {side: _side_visibility(landmarks, side) for side in ("left", "right")}
        if (
            self.active_side is not None
            and vis[self.active_side] >= MIN_LANDMARK_VISIBILITY
        ):
            return self.active_side
        best_side = max(vis, key=lambda s: vis[s])
        return best_side if vis[best_side] >= MIN_LANDMARK_VISIBILITY else None

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "active_side": self.active_side,
            "elbow_angle": None,
            "elbow_tuck_ratio": None,
            "body_line_angle": None,
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
                "No person detected — get into frame, side-on to the camera."
            )
            response.update(self._progress_fields())
            return response

        self.active_side = self._pick_active_side(landmarks)
        if self.active_side is None:
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._register_broken_frame()
            response["feedback"] = (
                "Can't see your body clearly from either side — move so your "
                "elbows, shoulders, hips and feet are all visible, side-on."
            )
            response.update(self._progress_fields())
            return response

        s_idx, e_idx, w_idx, h_idx, a_idx = SIDE_LANDMARKS[self.active_side]
        shoulder, elbow, wrist, hip, ankle = (
            landmarks[s_idx],
            landmarks[e_idx],
            landmarks[w_idx],
            landmarks[h_idx],
            landmarks[a_idx],
        )

        elbow_angle = _angle_deg(shoulder, elbow, wrist)
        body_line_angle = _angle_deg(shoulder, hip, ankle)

        torso_length = max(_dist(shoulder, hip), 1e-6)
        elbow_tuck_ratio = _dist(elbow, hip) / torso_length

        incline_ratio = abs(ankle.y - shoulder.y) / max(abs(ankle.x - shoulder.x), 1e-6)

        framing_message = _framing_feedback(shoulder, hip, ankle, wrist)

        # ---- resolve hold-validity this frame (hysteresis on each gate) ----
        if self.hold_active:
            elbow_broken = elbow_angle < ELBOW_BROKEN_LOW or elbow_angle > ELBOW_BROKEN_HIGH
            tuck_broken = elbow_tuck_ratio > TUCK_BROKEN_ABOVE
            body_line_broken = body_line_angle < BODY_LINE_BROKEN_BELOW
        else:
            elbow_broken = elbow_angle < ELBOW_RESUME_LOW or elbow_angle > ELBOW_RESUME_HIGH
            tuck_broken = elbow_tuck_ratio > TUCK_RESUME_BELOW
            body_line_broken = body_line_angle < BODY_LINE_RESUME_ABOVE

        incline_broken = incline_ratio > MAX_INCLINE_RATIO

        holding_now = (
            framing_message is None
            and not elbow_broken
            and not tuck_broken
            and not body_line_broken
            and not incline_broken
        )

        # ---- form tiering (only meaningful while holding) ----
        issues: list[str] = []
        messages: list[str] = []
        if holding_now:
            if not (ELBOW_IDEAL_LOW <= elbow_angle <= ELBOW_IDEAL_HIGH):
                issues.append("elbow_angle")
                messages.append(
                    "Aim for roughly a right angle at the elbow — you're a bit "
                    + ("too straight." if elbow_angle > ELBOW_IDEAL_HIGH else "too collapsed.")
                )

            if elbow_tuck_ratio > TUCK_IDEAL_BELOW:
                issues.append("not_tucked")
                messages.append(
                    "Press your elbows in closer to your belly/lower ribs."
                )

            if body_line_angle < BODY_LINE_IDEAL_ABOVE:
                issues.append("body_line")
                messages.append(
                    "Keep your body in one straight line — no sagging or piking."
                )

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

        # ---- feedback priority: framing > hard breaks > form flaws > praise ----
        feedback = framing_message
        if feedback is None and incline_broken:
            feedback = (
                "Your body needs to hover roughly level with the ground, "
                "not angled steeply up or down."
            )
        if feedback is None and body_line_broken:
            feedback = "Straighten your body line — no sagging or piking at the hips."
        if feedback is None and tuck_broken:
            feedback = "Tuck your elbows in against your belly — they're drifting out."
        if feedback is None and elbow_broken:
            feedback = (
                "Bend your elbows to roughly a right angle and press them into your belly — "
                "this is a bent-arm hold, not a straight-arm one."
                if elbow_angle > ELBOW_RESUME_HIGH
                else "Don't let your elbows collapse flat — hold the bend."
            )
        if feedback is None and messages:
            feedback = messages[0]
        if feedback is None and target_reached:
            feedback = f"Target reached — {self.target_seconds}s held, nice work!"
        if feedback is None and holding_now:
            feedback = "Great hold — keep it there!"
        if feedback is None:
            feedback = "Get back into position to resume the timer."

        response.update(
            {
                "pose_detected": True,
                "active_side": self.active_side,
                "elbow_angle": round(elbow_angle, 1),
                "elbow_tuck_ratio": round(elbow_tuck_ratio, 3),
                "body_line_angle": round(body_line_angle, 1),
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


class PeacockPoseSession:
    """Full session: one shared pose model + one analyzer.

    `target_seconds` / `target_sets` / `set_number` are the coach-assigned
    plan for this user, supplied by the caller (the websocket route, from
    query params) — same convention as the other hold-based sessions.
    The frontend does not decide on its own whether a set/exercise is
    done; `session_complete` and `exercise_complete` are both computed here.
    """

    def __init__(
        self,
        target_seconds: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = PeacockPoseAnalyzer(target_seconds)
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
