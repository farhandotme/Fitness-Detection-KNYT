"""
Standing Forward Fold (Uttanasana) hold timing + posture correction.

Design
------
Same family as `PlankHoldAnalyzer` / `SidePlankAnalyzer` — a forward fold
has no reps, it's a single continuous timed position, so this runs the
identical **hold timer that only advances while the person is verified,
frame by frame, to actually be in a correct fold**:

    * The instant form breaks (stands back up, bends knees into a squat,
      or the framing goes bad), the timer **pauses**. It never resets to
      zero, so `hold_seconds` is monotonic for the life of a set.
      `current_streak_seconds` resets on a break so it reflects only the
      *current* attempt.
    * The instant good form resumes, the timer picks back up.

Camera framing
---------------
Judged from a side-on (profile) view, same convention as plank/side
plank — but unlike those, the person is standing and bending, so the
useful frame is taller than it is wide (need head-to-floor in shot),
not landscape.

Form signal (hard gate — pauses the timer)
-------------------------------------------
  * `fold_angle` = angle(shoulder, hip, knee). Standing upright this
    reads ~170-180°. Bending forward at the hips drives it down. Below
    `FOLD_RESUME_BELOW` the torso is genuinely folded over the legs;
    above `FOLD_BROKEN_ABOVE` they've stood back up (hysteresis band
    between the two stops flicker on a borderline angle).
  * `knee_angle` = angle(hip, knee, ankle) must stay above
    `SQUAT_GUARD_BELOW`. This is the guard that tells a forward fold
    apart from someone squatting down or sitting into a fold — a
    Standing Forward Fold keeps the legs standing (mostly straight),
    it does not bend at the knees the way a squat does. This IS a hard
    break here (unlike side plank's knee note), because a deeply bent
    knee changes the exercise entirely.
  * `standing_ratio` (vertical span / horizontal span of shoulder→ankle)
    must clear a minimum, which rules out someone lying flat on the
    floor faking a small fold_angle.

Only these three break the hold. Hand-reach is graded as a lighter-tier
form note (shapes `hold_quality`/feedback, doesn't pause the timer),
since not everyone's hamstrings let them touch the floor on day one.
`head_angle` is reported for info only and never affects quality or
the timer — a forward fold's torso keeps rotating deeper throughout
the hold, so there's no single stable "neutral neck angle" to check it
against the way there is in a plank.
"""

import math
from collections import deque
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_EAR,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    LEFT_WRIST,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_EAR,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)

# -------------------------------------------------------------------------
# Tunable constants
# -------------------------------------------------------------------------

MIN_LANDMARK_VISIBILITY = 0.4

SIDE_LANDMARKS = {
    "left": (LEFT_SHOULDER, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE, LEFT_WRIST),
    "right": (RIGHT_SHOULDER, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE, RIGHT_WRIST),
}
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 2


# ---- fold angle (shoulder-hip-knee), degrees ----
# Hysteresis band: once holding, only rising above FOLD_BROKEN_ABOVE
# pauses the timer; once broken/not-started, has to fold back down below
# FOLD_RESUME_BELOW to start again.
FOLD_BROKEN_ABOVE = 100.0
FOLD_RESUME_BELOW = 85.0
FOLD_IDEAL_BELOW = 55.0  # deep fold, hands typically near the floor here

# ---- knee angle (hip-knee-ankle), degrees ----
# Hard guard: below this it's a squat/seated fold, not a standing one.
SQUAT_GUARD_BELOW = 120.0
# Soft note zone: legs are standing but noticeably bent (tight hamstrings).
KNEE_FLAW_BELOW = 160.0

# ---- hand-reach note (wrist vs ankle height), normalized by leg length ----
REACH_FLAW_ABOVE = 0.35

# ---- head/neck angle (ear-shoulder-hip), degrees ----
# NOTE: unlike plank/side-plank, torso orientation keeps rotating all the
# way through a forward fold as it gets deeper — there's no single stable
# "neutral" angle to calibrate against, so this is reported for info only
# and never gates hold_quality or breaks the timer. A calibrated-baseline
# check here produced false "needs improvement" flags on textbook-perfect,
# dead-straight-leg, deep folds, since the neck angle at a shallow moment
# early in the hold doesn't match the (still relaxed) neck angle once the
# person folds deeper.

MISTAKE_PENALTY = {
    "knees_bent": 15,
    "hands_not_reaching": 12,
}

SCORE_HISTORY = 30
SCORE_SAMPLE_INTERVAL = 1.0

# ---- framing ----
FRAME_EDGE_MARGIN = 0.03
BODY_SPAN_TOO_CLOSE = 0.9
BODY_SPAN_TOO_FAR = 0.3
MIN_STANDING_RATIO = 0.35  # too low = lying flat on the floor, not standing/folding


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


def _side_visibility(landmarks, side: str) -> float:
    scores = []
    for idx in SIDE_LANDMARKS[side][:4]:  # shoulder/hip/knee/ankle only
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


def _framing_feedback(shoulder, hip, ankle) -> Optional[str]:
    for p in (shoulder, hip, ankle):
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — step back so your whole body, "
                "head to floor, fits in the shot."
            )

    dx = abs(ankle.x - shoulder.x)
    dy = abs(ankle.y - shoulder.y)
    body_span = math.hypot(dx, dy)

    if body_span > BODY_SPAN_TOO_CLOSE:
        return "You're too close to the camera — step back until your whole body fits in frame."
    if body_span < BODY_SPAN_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    if dy < 1e-6 or (dy / max(dx, 1e-6)) < MIN_STANDING_RATIO:
        return (
            "I need a standing side-on view — stand sideways to the camera, "
            "feet on the ground, then hinge forward at your hips."
        )

    return None


class StandingForwardFoldAnalyzer:
    """Stateful standing-forward-fold hold timer + posture checker.

    No `target_reps` — the coach-assigned target is a duration,
    `target_seconds`. `session_complete` is `hold_seconds >= target_seconds`,
    exactly mirroring `PlankHoldAnalyzer` / `SidePlankAnalyzer`.
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

        # No calibration step for this exercise (see head/neck note above) —
        # kept as a fixed True so the frontend's "Calibrating…" state never
        # shows for this exercise.
        self.calibrated = True

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
            "fold_angle": None,
            "knee_angle": None,
            "head_angle": None,
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
            "calibrated": self.calibrated,
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
                "No person detected — stand side-on to the camera, full body in frame."
            )
            response.update(self._progress_fields())
            return response

        self.active_side = self._pick_active_side(landmarks)
        if self.active_side is None:
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._register_broken_frame()
            response["feedback"] = (
                "Can't see your body clearly from either side — step back and "
                "turn side-on to the camera."
            )
            response.update(self._progress_fields())
            return response

        s_idx, h_idx, k_idx, a_idx, w_idx = SIDE_LANDMARKS[self.active_side]
        shoulder, hip, knee, ankle, wrist = (
            landmarks[s_idx],
            landmarks[h_idx],
            landmarks[k_idx],
            landmarks[a_idx],
            landmarks[w_idx],
        )
        ear = landmarks[LEFT_EAR if self.active_side == "left" else RIGHT_EAR]
        ear_ok = (
            _visible((ear,)) and ear.visibility is not None and ear.visibility > 0.3
        )
        wrist_ok = (
            _visible((wrist,))
            and wrist.visibility is not None
            and wrist.visibility > 0.3
        )

        fold_angle = _angle_deg(shoulder, hip, knee)
        knee_angle = _angle_deg(hip, knee, ankle)
        head_angle = _angle_deg(ear, shoulder, hip) if ear_ok else None

        framing_message = _framing_feedback(shoulder, hip, ankle)

        # ---- resolve hold-validity this frame (with hysteresis on fold_angle) ----
        if self.hold_active:
            fold_broken = fold_angle > FOLD_BROKEN_ABOVE
        else:
            fold_broken = fold_angle > FOLD_RESUME_BELOW

        # Hard guard: bent knees below this mean a squat/seated fold, not a
        # standing forward fold — always a hard break, no hysteresis needed
        # since the gap to a genuine standing fold is large.
        squat_detected = knee_angle < SQUAT_GUARD_BELOW

        holding_now = framing_message is None and not fold_broken and not squat_detected

        # ---- form tiering (only meaningful while holding) ----
        issues: list[str] = []
        messages: list[str] = []
        if holding_now:
            if knee_angle < KNEE_FLAW_BELOW:
                issues.append("knees_bent")
                messages.append(
                    "Try straightening your legs a bit more — a soft bend is fine "
                    "for tight hamstrings, just don't sink into a squat."
                )

            if wrist_ok:
                leg_length = max(_dist(hip, ankle), 1e-6)
                reach_gap = abs(wrist.y - ankle.y) / leg_length
                if reach_gap > REACH_FLAW_ABOVE:
                    issues.append("hands_not_reaching")
                    messages.append(
                        "Let your arms hang heavier and reach your hands toward "
                        "the floor or your shins."
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

        # ---- feedback priority: framing > hard break > form flaws > praise ----
        feedback = framing_message
        if feedback is None and squat_detected:
            feedback = (
                "Keep your legs standing — you're bending your knees into a squat "
                "instead of folding at the hips."
            )
        if feedback is None and fold_broken:
            feedback = (
                "That's not a forward fold yet — hinge at your hips and let your "
                "torso hang down toward your legs."
            )
        if feedback is None and messages:
            feedback = messages[0]
        if feedback is None and target_reached:
            feedback = f"Target reached — {self.target_seconds}s held, nice work!"
        if feedback is None and holding_now:
            feedback = "Great forward fold — keep holding!"
        if feedback is None:
            feedback = "Get back into the fold to resume the timer."

        response.update(
            {
                "pose_detected": True,
                "active_side": self.active_side,
                "fold_angle": round(fold_angle, 1),
                "knee_angle": round(knee_angle, 1),
                "head_angle": round(head_angle, 1) if head_angle is not None else None,
                "hold_state": "holding" if holding_now else "broken",
                "is_holding": holding_now,
                "target_reached": target_reached,
                "hold_quality": hold_quality,
                "calibrated": self.calibrated,
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


class StandingForwardFoldSession:
    """Full session: one shared pose model + one analyzer.

    `target_seconds` / `target_sets` / `set_number` are the coach-assigned
    plan for this user, supplied by the caller (the websocket route, from
    query params) — same convention as `PlankHoldSession` / `SidePlankSession`.
    The frontend does not decide on its own whether a set/exercise is done;
    `session_complete` and `exercise_complete` are both computed here.
    """

    def __init__(
        self,
        target_seconds: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = StandingForwardFoldAnalyzer(target_seconds)
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
