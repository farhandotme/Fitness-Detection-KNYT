"""
Plank hold timing + posture correction.

Design
------
Every other exercise in this backend (squat, lunge, high knees, ...) counts
discrete reps. A plank hold has no reps — it's a single continuous timed
position — so `PlankHoldAnalyzer` doesn't run a rep state machine at all.
Instead it runs a **hold timer that only advances while the person is
verified, frame by frame, to actually be in a correct plank**:

    * The instant form breaks (or the person leaves frame, or the camera
      framing goes bad), the timer **pauses**. It never silently resets to
      zero — losing 25 seconds of progress because of one bad frame or a
      half-second wobble would be exactly the kind of thing that makes a
      user distrust the app, so accumulated `hold_seconds` is monotonic
      for the lifetime of a set. `current_streak_seconds` (time since the
      last break) is what resets, giving live feedback on the *current*
      attempt without punishing total progress.
    * The instant good form resumes, the timer picks back up from where it
      left off.

This makes "did the timer count or not" trivially explainable to a user at
any moment: `is_holding` is true if and only if this exact frame passed
every check below, and `hold_state` / `feedback` always say why if it
didn't.

Camera framing
---------------
Unlike the standing, front-facing exercises, a plank is judged from a
**side-on (profile) view** — that's the only angle a straight-line body
check can be made from. So framing here checks that the body reads as
*horizontal* (lying into a plank) rather than vertical (standing), and
`active_side` picks whichever side of the body (left or right) is
currently better tracked, since a profile view only ever shows one side
well. It's re-evaluated every frame (preferring to keep the current side
to avoid flicker) so the analyzer keeps working if the person's stance
shifts or they turn slightly.

Form signal
-----------
Three joint angles, all evaluated on the currently-active side:

  * `alignment_angle` = angle(shoulder, hip, ankle). ~180° is a
    ruler-straight body. This is the primary hold-validity gate, with a
    hysteresis band (`ALIGN_BROKEN` to resume above `ALIGN_RESUME`, and
    once resumed only `ALIGN_BROKEN` to *stay* active) so a value sitting
    right on the boundary can't flicker holding/broken every other frame.
    Whether a bad angle means the hips are sagging or piking is read off
    the *signed* vertical deviation of the hip from the dead-straight
    shoulder-ankle line, not the angle itself, so the coaching message
    always points the right direction.
  * `knee_angle` = angle(hip, knee, ankle). A real plank keeps the legs
    straight; a knee angle collapsing well below straight means the
    person has dropped to their knees — a hard break, not a "flaw",
    since kneeling isn't a plank at all regardless of hip alignment.
  * `head_angle` = angle(ear, shoulder, hip). Neutral neck keeps the ear
    roughly in line with the shoulder-hip line. Because "neutral" varies
    by neck length and camera angle, this one *is* calibrated against the
    person's own first few good-hold seconds (unlike the two angles
    above, which use fixed targets — a straight body is a straight body
    regardless of build).

A broken knee angle pauses the timer outright. A bad hip alignment also
pauses it (a "plank" with your hips in the air or on the floor isn't
holding a plank). Head position never pauses the timer by itself — it's
graded as a lighter-weight form note. This mirrors the site-wide
philosophy of "always count/hold what's genuinely happening, but tell the
person what to fix" — just applied to seconds instead of reps.
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
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_EAR,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
)

# -------------------------------------------------------------------------
# Tunable constants
# -------------------------------------------------------------------------

MIN_LANDMARK_VISIBILITY = 0.4

# A side (left or right) is usable as `active_side` only if all four of
# these are confidently visible on that side.
SIDE_LANDMARKS = {
    "left": (LEFT_SHOULDER, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE),
    "right": (RIGHT_SHOULDER, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE),
}
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 2  # a side-on view often only clearly shows 2-3


# ---- body-alignment angle (shoulder-hip-ankle), degrees ----
# Hysteresis band: once holding, only a drop below ALIGN_BROKEN pauses the
# timer; once broken/not-started, alignment has to climb back above
# ALIGN_RESUME (a few degrees above ALIGN_BROKEN) to start it again. This
# gap is what stops a borderline angle from flickering holding/broken.
ALIGN_BROKEN = 145.0
ALIGN_RESUME = 156.0
ALIGN_IDEAL = 167.0  # at/above this, hip alignment is "good" tier (no flaw)

# ---- knee angle (hip-knee-ankle), degrees ----
# Below KNEE_BROKEN the person has essentially dropped to their knees —
# not a plank, regardless of hip alignment, so this is a hard break too.
KNEE_BROKEN = 115.0
KNEE_IDEAL = 160.0  # at/above this, legs are "good" tier (no flaw)

# ---- head/neck angle (ear-shoulder-hip), degrees — calibrated per-person ----
HEAD_ANGLE_DELTA = 18.0  # allowed drift from personal baseline before flagging
CALIBRATION_FRAMES = 15  # consecutive good-hold frames needed to calibrate

# Per-issue form_score penalty (applied per frame while holding).
MISTAKE_PENALTY = {
    "hip_sag": 22,
    "hip_pike": 18,
    "knees_dropping": 20,
    "head_position": 10,
}

# form_score is sampled into this rolling window roughly once a second
# (not every frame) so `avg_form_score` reflects the last ~SCORE_HISTORY
# seconds of holding rather than being dominated by frame rate.
SCORE_HISTORY = 30
SCORE_SAMPLE_INTERVAL = 1.0  # seconds

# -------------------------------------------------------------------------
# Camera framing / stance-position thresholds (profile view — body should
# read as roughly horizontal, not standing).
# -------------------------------------------------------------------------
FRAME_EDGE_MARGIN = 0.03
BODY_SPAN_TOO_CLOSE = (
    0.85  # shoulder-to-ankle span as a fraction of frame width: too large = too close
)
BODY_SPAN_TOO_FAR = 0.35  # too small = too far away
MAX_STANDING_RATIO = 0.65  # |dy|/|dx| of shoulder->ankle above this = too vertical (standing, not planking)


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
    """Lowest visibility score among the four landmarks that make up
    `side` — a conservative "can we trust this side at all" score."""
    scores = []
    for idx in SIDE_LANDMARKS[side]:
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


def _hip_deviation(shoulder, hip, ankle) -> float:
    """Signed vertical deviation of the hip from the straight
    shoulder-ankle line, normalized by body length. Positive = hip sits
    *below* the line (sagging); negative = hip sits *above* it (piking).
    Unlike a cross-product line-deviation, this is based on simple x
    interpolation, so its sign is unaffected by which way the person is
    facing the camera (left profile vs. right profile)."""
    body_len = max(_dist(shoulder, ankle), 1e-6)
    dx = ankle.x - shoulder.x
    if abs(dx) < 1e-6:
        return 0.0
    frac = (hip.x - shoulder.x) / dx
    line_y_at_hip = shoulder.y + frac * (ankle.y - shoulder.y)
    return (hip.y - line_y_at_hip) / body_len


def _framing_feedback(shoulder, hip, ankle) -> Optional[str]:
    """Coaches the user into a good spot for the camera to judge a plank
    from — checked every frame, independent of exercise form.

    Checks, in order of how badly they break tracking:
      1. Part of the (active-side) body clipped at a frame edge.
      2. Standing too upright instead of horizontal — most likely they
         haven't gotten into plank position yet, or the camera isn't
         actually side-on.
      3. Too close / too far from the camera.
    """
    for p in (shoulder, hip, ankle):
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — reposition so your whole body, "
                "head to feet, fits in the shot."
            )

    dx = abs(ankle.x - shoulder.x)
    dy = abs(ankle.y - shoulder.y)
    if dx < 1e-6 or (dy / dx) > MAX_STANDING_RATIO:
        return (
            "Turn sideways to the camera and get into forearm plank position "
            "— I need a side-on view to check your alignment."
        )

    body_span = math.hypot(dx, dy)
    if body_span > BODY_SPAN_TOO_CLOSE:
        return "You're too close to the camera — step back until your whole body fits in frame."
    if body_span < BODY_SPAN_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class PlankHoldAnalyzer:
    """Stateful plank-hold timer + posture checker.

    No `target_reps` here — the coach-assigned target is a duration,
    `target_seconds`. `session_complete` is `hold_seconds >= target_seconds`,
    exactly mirroring how the rep-based analyzers compare `rep_count` to
    `target_reps`.
    """

    def __init__(self, target_seconds: Optional[int] = None):
        self.target_seconds = target_seconds

        self.active_side: Optional[str] = None

        self.hold_active = False  # is the timer running THIS frame
        self.started = False  # has the timer ever run at all
        self.hold_seconds = 0.0
        self.good_seconds = 0.0
        self.flawed_seconds = 0.0
        self.current_streak_seconds = 0.0
        self.best_streak_seconds = 0.0
        self.break_count = 0

        self.last_timestamp_s: Optional[float] = None
        self.session_start_time: Optional[float] = None

        self._was_complete = False  # for edge-triggering `target_reached`

        # Personal head/neck baseline, calibrated from the first stretch of
        # genuinely good holding (good hip + knee alignment) rather than a
        # fixed angle, since neutral neck angle varies by build/camera tilt.
        self._calib_samples: list[float] = []
        self.calibrated = False
        self._baseline_head_angle = 180.0

        self.form_scores: deque[int] = deque(maxlen=SCORE_HISTORY)
        self._last_score_sample_time: Optional[float] = None

    # ---------------------------------------------------------------
    def _is_complete(self) -> bool:
        return (
            self.target_seconds is not None and self.hold_seconds >= self.target_seconds
        )

    def _finish_calibration(self):
        n = len(self._calib_samples)
        self._baseline_head_angle = sum(self._calib_samples) / n
        self.calibrated = True

    def _pick_active_side(self, landmarks) -> Optional[str]:
        vis = {side: _side_visibility(landmarks, side) for side in ("left", "right")}

        # Prefer to keep the current side if it's still trustworthy — avoids
        # flickering `active_side` (and the angle it drives) back and forth
        # on frames where both sides read similarly.
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
            "alignment_angle": None,
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
            dt = max(0.0, min(t - self.last_timestamp_s, 0.5))  # clamp huge gaps
        self.last_timestamp_s = t

        if landmarks is None or not _looks_like_a_person(landmarks):
            self._register_broken_frame()
            response["feedback"] = (
                "No person detected — get into frame, sideways to the camera."
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
                "turn sideways to the camera."
            )
            response.update(self._progress_fields())
            return response

        s_idx, h_idx, k_idx, a_idx = SIDE_LANDMARKS[self.active_side]
        shoulder, hip, knee, ankle = (
            landmarks[s_idx],
            landmarks[h_idx],
            landmarks[k_idx],
            landmarks[a_idx],
        )
        ear = landmarks[LEFT_EAR if self.active_side == "left" else RIGHT_EAR]
        ear_ok = (
            _visible((ear,)) and ear.visibility is not None and ear.visibility > 0.3
        )

        alignment_angle = _angle_deg(shoulder, hip, ankle)
        knee_angle = _angle_deg(hip, knee, ankle)
        head_angle = _angle_deg(ear, shoulder, hip) if ear_ok else None

        framing_message = _framing_feedback(shoulder, hip, ankle)

        # ---- resolve hold-validity this frame (with hysteresis) ----
        knee_broken = knee_angle < KNEE_BROKEN
        if self.hold_active:
            align_broken = alignment_angle < ALIGN_BROKEN
        else:
            align_broken = alignment_angle < ALIGN_RESUME

        holding_now = framing_message is None and not align_broken and not knee_broken

        # ---- form tiering (only meaningful while holding) ----
        issues: list[str] = []
        messages: list[str] = []
        if holding_now:
            if alignment_angle < ALIGN_IDEAL:
                deviation = _hip_deviation(shoulder, hip, ankle)
                if deviation > 0:
                    issues.append("hip_sag")
                    messages.append(
                        "Lift your hips — you're sagging, squeeze your core and glutes."
                    )
                else:
                    issues.append("hip_pike")
                    messages.append(
                        "Lower your hips — you're piking up too high, flatten out."
                    )

            if knee_angle < KNEE_IDEAL:
                issues.append("knees_dropping")
                messages.append(
                    "Straighten your legs — keep your knees off the ground."
                )

            if self.calibrated and head_angle is not None:
                if abs(head_angle - self._baseline_head_angle) > HEAD_ANGLE_DELTA:
                    issues.append("head_position")
                    messages.append(
                        "Keep your neck neutral — don't let your head drop or crane up."
                    )

            # Calibrate the neutral-neck baseline only from genuinely clean
            # holds (no hip/knee issues) so a bad rep can't poison it.
            if (
                not self.calibrated
                and head_angle is not None
                and "hip_sag" not in issues
                and "hip_pike" not in issues
                and "knees_dropping" not in issues
            ):
                self._calib_samples.append(head_angle)
                if len(self._calib_samples) >= CALIBRATION_FRAMES:
                    self._finish_calibration()

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
        if feedback is None and knee_broken:
            feedback = (
                "Get your knees off the ground — straighten your legs into a plank."
            )
        if feedback is None and align_broken:
            feedback = (
                "That's not a plank position yet — get your body in a straight "
                "line from shoulders to ankles."
            )
        if feedback is None and messages:
            feedback = messages[0]
        if feedback is None and not self.calibrated and holding_now:
            feedback = "Great form — hold it, calibrating your neutral posture."
        if feedback is None and target_reached:
            feedback = f"Target reached — {self.target_seconds}s held, nice work!"
        if feedback is None and holding_now:
            feedback = "Great plank — keep holding!"
        if feedback is None:
            feedback = "Get back into plank position to resume the timer."

        response.update(
            {
                "pose_detected": True,
                "active_side": self.active_side,
                "alignment_angle": round(alignment_angle, 1),
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


class PlankHoldSession:
    """Full plank-hold session: one shared pose model + one analyzer.

    `target_seconds` / `target_sets` / `set_number` are the coach-assigned
    plan for this user, supplied by the caller (the websocket route, from
    query params) — same convention as the rep-based sessions, just with a
    duration standing in for a rep count. The frontend does not decide on
    its own whether a set/exercise is done; `session_complete` (this set's
    hold time is met) and `exercise_complete` (the whole assigned plan —
    all sets — is done) are both computed here.
    """

    def __init__(
        self,
        target_seconds: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = PlankHoldAnalyzer(target_seconds)
        self.target_sets = max(1, target_sets)
        self.set_number = max(1, min(set_number, self.target_sets))

    def detect(self, frame, timestamp_ms: int) -> dict[str, Any]:
        landmarks = self.engine.detect(frame, timestamp_ms)
        result = self.analyzer.update(landmarks, timestamp_ms)
        result["landmarks"] = (
            PoseEngine.landmarks_to_json(landmarks) if landmarks else []
        )

        # Backend-validated plan progress — frontend just reads these, it
        # never computes them itself.
        result["set_number"] = self.set_number
        result["target_sets"] = self.target_sets
        result["exercise_complete"] = bool(
            result["session_complete"] and self.set_number >= self.target_sets
        )
        return result

    def close(self):
        self.engine.close()
