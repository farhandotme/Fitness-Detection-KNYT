"""
Downward Dog (Adho Mukha Svanasana) hold timing + posture correction.

Design
------
Same architecture as `SidePlankAnalyzer` / `PlankHoldAnalyzer` — downward
dog has no reps, it's a single continuous held position, so this runs the
identical **hold timer that only advances while the person is verified,
frame by frame, to actually be in a correct downward dog**:

    * The instant the pose breaks (or the person leaves frame, or the
      camera framing goes bad), the timer **pauses**. It never silently
      resets to zero, so accumulated `hold_seconds` is monotonic for the
      lifetime of a set. `current_streak_seconds` (time since the last
      break) is what resets, giving live feedback on the *current*
      attempt without punishing total progress.
    * The instant good form resumes, the timer picks back up from where
      it left off.

This is deliberately strict about *counting* only genuinely-correct
downward dog frames — a shallow forward fold, a flat plank, or someone
just standing there must NOT accumulate hold time, or the timer becomes
meaningless. See the three-signal gate below.

Camera framing
--------------
Downward dog is judged from a **side-on (profile) view**, same convention
as the plank / side-plank detectors — the whole body (wrist to ankle)
needs to be in frame for the geometry checks to be reliable.

Pose signal — three independent checks must ALL agree before the hold
timer is allowed to run:
--------------------------------------------------------------------
  1. `hip_fold_angle` = angle(shoulder, hip, ankle). This is the "inverted
     V" angle at the hip. A ruler-straight body (standing OR a front
     plank) reads close to 180°; a deep forward fold / child's pose reads
     very small. A real downward dog sits in a distinct middle band.
     This one signal alone can't tell an upside-down V from someone just
     bent over with hips *not* raised, though — hence signal 2.
  2. `hip_elevation_ratio` = how far the hips sit *above* the shoulders
     (normalized by body length). Downward dog's defining signature is
     that the hips are the highest point of the whole body — clearly
     above the shoulders. This rules out tabletop/cat-cow (hips level
     with shoulders) and standing forward folds (hips not elevated).
  3. `arm_line_angle` = angle(hip, shoulder, wrist). In a correct downward
     dog the arms extend the line of the back — hip, shoulder and wrist
     read as close to a straight line. This rules out e.g. crouching with
     hips up but arms hanging down, or hands not reaching the floor.

Only when all three agree (with hysteresis so a borderline frame can't
flicker holding/broken every other frame) does the hold timer run.
Elbow straightness, knee straightness, and head/neck position are all
graded as lighter-weight form notes (same tier as side-plank's knee
note) — they don't pause the timer, they coach toward a stricter version
of the pose while still letting a beginner's modified downward dog count.
"""

import math
from collections import deque
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_EAR,
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    LEFT_WRIST,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_EAR,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)

# -------------------------------------------------------------------------
# Tunable constants
# -------------------------------------------------------------------------

MIN_LANDMARK_VISIBILITY = 0.4

# A side (left or right) is usable as `active_side` only if all of these
# are confidently visible on that side. For a side-on downward dog this
# naturally resolves to the camera-facing side.
SIDE_LANDMARKS = {
    "left": (
        LEFT_SHOULDER,
        LEFT_ELBOW,
        LEFT_WRIST,
        LEFT_HIP,
        LEFT_KNEE,
        LEFT_ANKLE,
    ),
    "right": (
        RIGHT_SHOULDER,
        RIGHT_ELBOW,
        RIGHT_WRIST,
        RIGHT_HIP,
        RIGHT_KNEE,
        RIGHT_ANKLE,
    ),
}
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 2  # a side-on view often only clearly shows 2-3


# ---- Signal 1: hip fold angle (shoulder-hip-ankle), degrees ----
# Hysteresis: once holding, the band is allowed to widen slightly before
# it counts as broken; to (re)start holding it has to land inside the
# tighter band first. This stops a borderline angle from flickering
# holding/broken every other frame.
FOLD_BROKEN_LOW = 35.0
FOLD_RESUME_LOW = 50.0
FOLD_BROKEN_HIGH = 145.0
FOLD_RESUME_HIGH = 130.0

# ---- Signal 2: hip elevation above the shoulders, normalized ----
# (mid_shoulder.y - mid_hip.y) / body_scale — positive means hips sit
# higher (physically up) than the shoulders. This is THE defining
# downward-dog signature; without it a bent-over shape is just a fold,
# not the pose.
ELEVATION_BROKEN = 0.015
ELEVATION_RESUME = 0.06
ELEVATION_IDEAL = 0.14  # at/above this, elevation is "good" tier (no flaw)

# ---- Signal 3: arm/back line straightness (hip-shoulder-wrist), degrees ----
ARM_LINE_BROKEN = 130.0
ARM_LINE_RESUME = 145.0
ARM_LINE_IDEAL = 160.0  # at/above this, no flaw

# ---- Soft form notes (never pause the timer) ----
ELBOW_STRAIGHT_MIN = 155.0  # below this = "bent_elbows" flaw
KNEE_STRAIGHT_MIN = 150.0  # below this = "bent_knees" flaw (legit beginner reg.)
HEAD_NEUTRAL_MIN = 140.0  # below this = "head_position" flaw (craning neck up)

# Per-issue form_score penalty (applied per frame while holding).
MISTAKE_PENALTY = {
    "bent_elbows": 15,
    "bent_knees": 10,
    "raise_hips": 15,
    "rounded_shoulders": 15,
    "head_position": 8,
}

# form_score is sampled into this rolling window roughly once a second
# (not every frame) so `avg_form_score` reflects the last ~SCORE_HISTORY
# seconds of holding rather than being dominated by frame rate.
SCORE_HISTORY = 30
SCORE_SAMPLE_INTERVAL = 1.0  # seconds

# -------------------------------------------------------------------------
# Camera framing thresholds (profile view).
# -------------------------------------------------------------------------
FRAME_EDGE_MARGIN = 0.03
BODY_SPAN_TOO_CLOSE = (
    0.9  # wrist-to-ankle span as a fraction of frame: too large = too close
)
BODY_SPAN_TOO_FAR = 0.3  # too small = too far away


def _visible(points) -> bool:
    for p in points:
        if p is None:
            return False
        v = getattr(p, "visibility", None)
        if v is not None and v < MIN_LANDMARK_VISIBILITY:
            return False
    return True


def _side_visibility(landmarks, side: str) -> float:
    """Lowest visibility score among the landmarks that make up `side` —
    a conservative "can we trust this side at all" score."""
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


def _framing_feedback(shoulder, wrist, hip, ankle) -> Optional[str]:
    """Coaches the user into a good spot for the camera to judge a
    downward dog from — checked every frame, independent of pose form.

    Checks, in order of how badly they break tracking:
      1. Part of the (active-side) body clipped at a frame edge.
      2. Too close / too far from the camera.
    """
    for p in (shoulder, wrist, hip, ankle):
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — reposition so your whole "
                "body, hands to feet, fits in the shot."
            )

    body_span = _dist(wrist, ankle)
    if body_span > BODY_SPAN_TOO_CLOSE:
        return "You're too close to the camera — step back until your whole body fits in frame."
    if body_span < BODY_SPAN_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class DownwardDogAnalyzer:
    """Stateful downward-dog-hold timer + posture checker.

    No `target_reps` here — the coach-assigned target is a duration,
    `target_seconds`. `session_complete` is `hold_seconds >=
    target_seconds`, exactly mirroring `SidePlankAnalyzer` /
    `PlankHoldAnalyzer`.
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

        self.form_scores: deque[int] = deque(maxlen=SCORE_HISTORY)
        self._last_score_sample_time: Optional[float] = None

    # ---------------------------------------------------------------
    def _is_complete(self) -> bool:
        return (
            self.target_seconds is not None and self.hold_seconds >= self.target_seconds
        )

    def _pick_active_side(self, landmarks) -> Optional[str]:
        vis = {side: _side_visibility(landmarks, side) for side in ("left", "right")}

        # Prefer to keep the current side if it's still trustworthy — avoids
        # flickering `active_side` (and the angles it drives) back and
        # forth on frames where both sides read similarly.
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
            "hip_fold_angle": None,
            "elevation_ratio": None,
            "arm_line_angle": None,
            "elbow_angle": None,
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
                "Can't see your body clearly from either side — step back "
                "and make sure your whole body, hands to feet, faces the camera."
            )
            response.update(self._progress_fields())
            return response

        sh_idx, el_idx, wr_idx, hip_idx, kn_idx, an_idx = SIDE_LANDMARKS[
            self.active_side
        ]
        shoulder, elbow, wrist, hip, knee, ankle = (
            landmarks[sh_idx],
            landmarks[el_idx],
            landmarks[wr_idx],
            landmarks[hip_idx],
            landmarks[kn_idx],
            landmarks[an_idx],
        )
        ear = landmarks[LEFT_EAR if self.active_side == "left" else RIGHT_EAR]
        ear_ok = (
            _visible((ear,)) and ear.visibility is not None and ear.visibility > 0.3
        )

        hip_fold_angle = _angle_deg(shoulder, hip, ankle)
        arm_line_angle = _angle_deg(hip, shoulder, wrist)
        elbow_angle = _angle_deg(shoulder, elbow, wrist)
        knee_angle = _angle_deg(hip, knee, ankle)
        head_angle = _angle_deg(ear, shoulder, hip) if ear_ok else None

        body_scale = max(_dist(shoulder, hip) + _dist(hip, ankle), 1e-6)
        elevation_ratio = (shoulder.y - hip.y) / body_scale

        framing_message = _framing_feedback(shoulder, wrist, hip, ankle)

        # ---- resolve hold-validity this frame (three-signal gate, each
        # with its own hysteresis so a single noisy frame can't flip it) ----
        if self.hold_active:
            fold_broken = (
                hip_fold_angle < FOLD_BROKEN_LOW or hip_fold_angle > FOLD_BROKEN_HIGH
            )
            elevation_broken = elevation_ratio < ELEVATION_BROKEN
            arm_line_broken = arm_line_angle < ARM_LINE_BROKEN
        else:
            fold_broken = (
                hip_fold_angle < FOLD_RESUME_LOW or hip_fold_angle > FOLD_RESUME_HIGH
            )
            elevation_broken = elevation_ratio < ELEVATION_RESUME
            arm_line_broken = arm_line_angle < ARM_LINE_RESUME

        pose_broken = fold_broken or elevation_broken or arm_line_broken
        holding_now = framing_message is None and not pose_broken

        # ---- form tiering (only meaningful while holding) ----
        issues: list[str] = []
        messages: list[str] = []
        if holding_now:
            if elevation_ratio < ELEVATION_IDEAL:
                issues.append("raise_hips")
                messages.append(
                    "Push your hips up and back higher — lengthen through "
                    "your spine toward the ceiling."
                )

            if arm_line_angle < ARM_LINE_IDEAL:
                issues.append("rounded_shoulders")
                messages.append(
                    "Press the floor away and extend through your arms — "
                    "keep a straight line from wrists to hips."
                )

            if elbow_angle < ELBOW_STRAIGHT_MIN:
                issues.append("bent_elbows")
                messages.append("Straighten your elbows — press firmly into the floor.")

            if knee_angle < KNEE_STRAIGHT_MIN:
                issues.append("bent_knees")
                messages.append(
                    "Try straightening your legs when ready — a soft bend "
                    "is a fine regression for now."
                )

            if head_angle is not None and head_angle < HEAD_NEUTRAL_MIN:
                issues.append("head_position")
                messages.append(
                    "Relax your neck — let your head hang between your "
                    "arms, gaze toward your feet or navel."
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
        if feedback is None and pose_broken:
            feedback = (
                "That's not downward dog yet — hands and feet on the "
                "floor, hips lifted high to form an upside-down V, arms "
                "and back in one straight line."
            )
        if feedback is None and messages:
            feedback = messages[0]
        if feedback is None and target_reached:
            feedback = f"Target reached — {self.target_seconds}s held, nice work!"
        if feedback is None and holding_now:
            feedback = "Great downward dog — keep holding!"
        if feedback is None:
            feedback = "Get back into downward dog to resume the timer."

        response.update(
            {
                "pose_detected": True,
                "active_side": self.active_side,
                "hip_fold_angle": round(hip_fold_angle, 1),
                "elevation_ratio": round(elevation_ratio, 3),
                "arm_line_angle": round(arm_line_angle, 1),
                "elbow_angle": round(elbow_angle, 1),
                "knee_angle": round(knee_angle, 1),
                "head_angle": round(head_angle, 1) if head_angle is not None else None,
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


class DownwardDogSession:
    """Full downward-dog session: one shared pose model + one analyzer.

    `target_seconds` / `target_sets` / `set_number` are the coach-assigned
    plan for this user, supplied by the caller (the websocket route, from
    query params) — same convention as `SidePlankSession` /
    `PlankHoldSession`. The frontend does not decide on its own whether a
    set/exercise is done; `session_complete` and `exercise_complete` are
    both computed here.
    """

    def __init__(
        self,
        target_seconds: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = DownwardDogAnalyzer(target_seconds)
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
