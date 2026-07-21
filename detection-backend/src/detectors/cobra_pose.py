"""
Cobra Pose (Bhujangasana) hold-timer + posture correction.

Cobra Pose is a static yoga hold, not a rep-counted exercise — you lie
prone, press up into the backbend, and hold the position; there's no
"down/up" cycle to count reps on. So this mirrors `SidePlankAnalyzer` /
`PlankHoldAnalyzer` exactly instead of `PushupAnalyzer`: a **continuous
hold timer that only advances while the person is verified, frame by
frame, to actually be in a correct Cobra Pose**.

  * The instant the pose breaks (chest drops back down, hips lift off the
    floor, the person stands up, or the camera framing goes bad), the
    timer **pauses**. It never silently resets to zero, so accumulated
    `hold_seconds` is monotonic for the lifetime of a set.
    `current_streak_seconds` (time since the last break) is what resets,
    giving live feedback on the *current* attempt without punishing total
    progress.
  * The instant good form resumes, the timer picks back up from where it
    left off.

Hold signal
-----------
  * `lift_ratio` = (hip.y - shoulder.y) / reference_length, where
    `reference_length` is the hip-to-knee segment — it stays anchored to
    the floor for the whole exercise (hips don't move), so it's a stable
    scale reference even as the torso arches and shortens the on-screen
    shoulder-hip distance. Image y grows downward, so lying flat gives a
    ratio near 0; a full arch gives a clearly larger positive number.
    This is the primary signal deciding "are they actually in the pose",
    with hysteresis (`LIFT_BROKEN` / `LIFT_RESUME`) so a borderline lift
    can't flicker holding/broken every other frame.
  * `hips_lifting_off_floor` — a soft posture note (does NOT pause the
    timer) if the hips rise off the floor baseline learned while resting
    flat before/between holds — the defining fault that turns a Cobra
    Pose into more of an upward-dog. Same tiering convention as
    `SidePlankAnalyzer`'s hip-sag/hip-pike notes.
  * `uneven_lift` — a soft posture note for left/right shoulder-height
    asymmetry (twisting instead of a symmetric arch).
  * `back_arch_angle` (shoulder-hip-knee) is reported for reference only
    — informational, not gating, same as the elbow angles.

Camera framing / lying-prone detection reuses the exact same
camera-angle-independent floor-vs-standing voting classifier as the
push-up detector — a person lying prone for Cobra Pose reads the same to
that classifier as someone in a push-up plank (horizontal body, low
incline).
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
    LEFT_WRIST,
    PoseEngine,
    RIGHT_ANKLE,
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

CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 3


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


# -------------------------------------------------------------------------
# Floor-position detection (camera-angle independent, same voting scheme
# as pushup.py — someone lying prone for Cobra Pose looks the same to this
# classifier as someone in a push-up plank: horizontal body, low incline).
# -------------------------------------------------------------------------
LEG_VERTICAL_STANDING_MIN = 0.85
LEG_VERTICAL_FLOOR_MAX = 0.45
TORSO_INCLINE_STANDING_MIN_DEG = 55.0
TORSO_INCLINE_FLOOR_MAX_DEG = 35.0
BBOX_ASPECT_FLOOR_MIN = 1.2
BBOX_ASPECT_STANDING_MAX = 0.75

STABLE_FLOOR_FRAMES = 5
GRACE_FRAMES = 8

# View-mode classification (shoulder width / torso length)
SIDE_VIEW_RATIO_MAX = 0.45
FRONT_VIEW_RATIO_MIN = 0.85

# Camera framing
FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.95
BBOX_TOO_FAR = 0.15

# -------------------------------------------------------------------------
# Cobra-specific: chest-lift hysteresis band decides whether the hold is
# "on" this frame. `lift_ratio` = (hip.y - shoulder.y) / reference_length.
# -------------------------------------------------------------------------
LIFT_BROKEN = 0.28  # once holding, a drop below this pauses the timer
LIFT_RESUME = 0.40  # from broken/not-started, must climb back above this

# Hips must stay pinned to the floor — the defining feature that separates
# Cobra Pose from a push-up/upward-dog. Tolerance is normalized by
# reference_length.
HIP_LIFT_TOLERANCE = 0.12

# Left/right shoulder-height mismatch while holding (torso twisting
# instead of a symmetric arch), normalized by shoulder width.
SHOULDER_TWIST_TOLERANCE = 0.20

# Per-issue form_score penalty (applied per frame while holding).
MISTAKE_PENALTY = {
    "hips_lifting_off_floor": 25,
    "uneven_lift": 12,
}

# form_score is sampled into this rolling window roughly once a second
# (not every frame) so `avg_form_score` reflects the last ~SCORE_HISTORY
# seconds of holding rather than being dominated by frame rate.
SCORE_HISTORY = 30
SCORE_SAMPLE_INTERVAL = 1.0


def _leg_far_point(l_ankle, r_ankle, l_knee, r_knee) -> Optional[_Point]:
    ankles = [p for p in (l_ankle, r_ankle) if _visible((p,))]
    if len(ankles) == 2:
        return _midpoint(*ankles)
    if len(ankles) == 1:
        return _Point(ankles[0].x, ankles[0].y)
    knees = [p for p in (l_knee, r_knee) if _visible((p,))]
    if len(knees) == 2:
        return _midpoint(*knees)
    if len(knees) == 1:
        return _Point(knees[0].x, knees[0].y)
    return None


def _view_mode(shoulder_width: float, torso_length: float) -> str:
    ratio = shoulder_width / max(torso_length, 1e-6)
    if ratio <= SIDE_VIEW_RATIO_MAX:
        return "side"
    if ratio >= FRONT_VIEW_RATIO_MIN:
        return "front"
    return "angled"


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


def _assess_body_position(
    leg_vertical_ratio: Optional[float],
    torso_incline_deg: Optional[float],
    bbox_aspect: Optional[float],
) -> tuple[bool, bool]:
    """Votes across three independent, camera-agnostic cues. Returns
    (is_floor, is_standing) — both require agreement, not just a majority,
    so a lone ambiguous cue can never flip the result on its own."""
    standing_votes = 0
    floor_votes = 0

    if leg_vertical_ratio is not None:
        if leg_vertical_ratio >= LEG_VERTICAL_STANDING_MIN:
            standing_votes += 2
        elif leg_vertical_ratio <= LEG_VERTICAL_FLOOR_MAX:
            floor_votes += 2

    # NOTE: torso incline only ever contributes a *floor* vote here, never
    # a *standing* vote. Cobra Pose (especially a deep/"full" backbend —
    # chest pressed way up, head tilted back, arms straightened) legitimately
    # sends the shoulder-to-hip incline steep while the person is still
    # lying down with their legs flat on the ground. Treating that steep
    # incline as a "standing" signal would drop `is_floor` — and therefore
    # pause the hold timer — the moment someone presses into a deeper
    # variation of the pose, which is exactly backwards. Whether someone
    # is actually standing up is decided by the leg/bbox cues below
    # instead, which stay reliable no matter how deep the arch goes.
    if (
        torso_incline_deg is not None
        and torso_incline_deg <= TORSO_INCLINE_FLOOR_MAX_DEG
    ):
        floor_votes += 1

    if bbox_aspect is not None:
        if bbox_aspect >= BBOX_ASPECT_FLOOR_MIN:
            floor_votes += 1
        elif bbox_aspect <= BBOX_ASPECT_STANDING_MAX:
            standing_votes += 1

    is_floor = floor_votes >= 2 and standing_votes == 0
    is_standing = standing_votes >= 2 and floor_votes == 0
    return is_floor, is_standing


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


class CobraPoseAnalyzer:
    """Stateful Cobra Pose hold timer + posture checker.

    No `target_reps` here — the coach-assigned target is a duration,
    `target_seconds`. `session_complete` is `hold_seconds >= target_seconds`,
    exactly mirroring `SidePlankAnalyzer` / `PlankHoldAnalyzer`.
    """

    def __init__(self, target_seconds: Optional[int] = None):
        self.target_seconds = target_seconds

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

        # Chest-lift smoothing
        self.smoothed_lift: Optional[float] = None
        self.lift_smooth_alpha = 0.5

        # Floor-position gating (lying prone at all — separate from
        # whether the pose is currently held)
        self._floor_streak = 0
        self._bad_streak = 0
        self.ready = False

        # Hip-stays-grounded baseline, learned while resting flat on the
        # floor (before/between holds)
        self._floor_hip_y: Optional[float] = None

        self.form_scores: "deque[int]" = deque(maxlen=SCORE_HISTORY)
        self._last_score_sample_time: Optional[float] = None

    # ---------------------------------------------------------------
    def _is_complete(self) -> bool:
        return (
            self.target_seconds is not None and self.hold_seconds >= self.target_seconds
        )

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
            "lift_ratio": None,
            "smoothed_lift_ratio": None,
            "back_arch_angle": None,
            "left_elbow_angle": None,
            "right_elbow_angle": None,
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
                "No person detected — get into frame, lying face down on the floor."
            )
            response.update(self._progress_fields())
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
        legs_visible = _visible((l_hip, l_knee)) or _visible((r_hip, r_knee))

        if not torso_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._register_broken_frame()
            response["feedback"] = (
                "Can't see your torso — make sure your shoulders and hips "
                "are both in frame."
            )
            response.update(self._progress_fields())
            return response

        if not legs_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._register_broken_frame()
            response["feedback"] = (
                "Can't see your hips and knees — make sure your whole body "
                "from shoulders to knees is in frame."
            )
            response.update(self._progress_fields())
            return response

        response["pose_detected"] = True

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)
        shoulder_width = _dist(l_shoulder, r_shoulder)

        view_mode = _view_mode(shoulder_width, torso_length)
        response["view_mode"] = view_mode

        leg_far = _leg_far_point(l_ankle, r_ankle, l_knee, r_knee)
        leg_vertical_ratio = (
            abs(mid_hip.y - leg_far.y) / torso_length if leg_far is not None else None
        )
        torso_incline = _torso_incline_deg(mid_shoulder, mid_hip)

        bbox_candidates = [
            p
            for p in (
                l_shoulder,
                r_shoulder,
                l_elbow,
                r_elbow,
                l_wrist,
                r_wrist,
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

        # ---- camera framing ----
        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        # ---- are they lying on the floor at all? ----
        is_floor, is_standing = _assess_body_position(
            leg_vertical_ratio, torso_incline, bbox_aspect
        )

        if is_floor:
            self._floor_streak += 1
            self._bad_streak = 0
        else:
            self._floor_streak = 0
            self._bad_streak += 1

        if self._floor_streak >= STABLE_FLOOR_FRAMES:
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES:
            self.ready = False

        position_ok = self.ready
        response["position_ok"] = position_ok
        response["ready"] = self.ready

        if is_standing:
            position_message = (
                "You're standing — lie face down on the floor to start "
                "Cobra Pose: legs extended behind you, hands under your shoulders."
            )
        elif not position_ok:
            position_message = (
                "Lie flat on your stomach with your legs extended and your "
                "hands under your shoulders to begin Cobra Pose."
            )
        else:
            position_message = None
        response["position_message"] = position_message

        # ---- reference length for normalizing the lift (hip->knee
        # segment, which stays anchored to the floor the whole exercise) ----
        ref_candidates = []
        if _visible((l_hip, l_knee)):
            ref_candidates.append(_dist(l_hip, l_knee))
        if _visible((r_hip, r_knee)):
            ref_candidates.append(_dist(r_hip, r_knee))
        if ref_candidates:
            reference_length = sum(ref_candidates) / len(ref_candidates)
        else:
            reference_length = max(shoulder_width, torso_length, 1e-6)
        reference_length = max(reference_length, 1e-6)

        # ---- chest-lift ratio (drives the hold state) ----
        raw_lift = (mid_hip.y - mid_shoulder.y) / reference_length

        if self.smoothed_lift is None:
            self.smoothed_lift = raw_lift
        else:
            self.smoothed_lift = (
                self.lift_smooth_alpha * raw_lift
                + (1 - self.lift_smooth_alpha) * self.smoothed_lift
            )

        # ---- informational angles (not gating) ----
        back_arch_angle = None
        arch_candidates = []
        if _visible((l_shoulder, l_hip, l_knee)):
            arch_candidates.append(_angle_deg(l_shoulder, l_hip, l_knee))
        if _visible((r_shoulder, r_hip, r_knee)):
            arch_candidates.append(_angle_deg(r_shoulder, r_hip, r_knee))
        if arch_candidates:
            back_arch_angle = sum(arch_candidates) / len(arch_candidates)

        left_elbow_angle = (
            _angle_deg(l_shoulder, l_elbow, l_wrist)
            if _visible((l_shoulder, l_elbow, l_wrist))
            else None
        )
        right_elbow_angle = (
            _angle_deg(r_shoulder, r_elbow, r_wrist)
            if _visible((r_shoulder, r_elbow, r_wrist))
            else None
        )

        # ---- learn the "hips on the floor" baseline while genuinely
        # resting flat (only updates when clearly not holding, so it can't
        # drift upward while the person is mid-pose) ----
        if position_ok and not self.hold_active and self.smoothed_lift < LIFT_BROKEN:
            if self._floor_hip_y is None:
                self._floor_hip_y = mid_hip.y
            else:
                self._floor_hip_y = 0.9 * self._floor_hip_y + 0.1 * mid_hip.y

        # ---- resolve hold-validity this frame (with hysteresis) ----
        if not position_ok:
            lift_broken = True
        elif self.hold_active:
            lift_broken = self.smoothed_lift < LIFT_BROKEN
        else:
            lift_broken = self.smoothed_lift < LIFT_RESUME

        holding_now = position_ok and framing_message is None and not lift_broken

        # ---- posture tiering (only meaningful while holding) ----
        issues: list[str] = []
        messages: list[str] = []
        if holding_now:
            if self._floor_hip_y is not None:
                hip_rise = (self._floor_hip_y - mid_hip.y) / reference_length
                if hip_rise > HIP_LIFT_TOLERANCE:
                    issues.append("hips_lifting_off_floor")
                    messages.append(
                        "Keep your hips and thighs pressed to the floor — "
                        "lift from your chest and upper back, not your hips."
                    )

            if view_mode in ("front", "angled") and shoulder_width > 1e-6:
                shoulder_twist = abs(l_shoulder.y - r_shoulder.y) / shoulder_width
                if shoulder_twist > SHOULDER_TWIST_TOLERANCE:
                    issues.append("uneven_lift")
                    messages.append(
                        "You're lifting unevenly — press up symmetrically "
                        "through both hands and keep your shoulders level."
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

        # ---- feedback priority: framing > not-on-the-floor > pose broken
        # > form flaws > praise ----
        feedback = framing_message
        if feedback is None and (is_standing or not position_ok):
            feedback = position_message
        if feedback is None and not holding_now:
            feedback = (
                "Press up into the arch — straighten your arms and lift "
                "your chest to start the hold."
                if not self.started
                else "Lost the pose — press back up into the arch to resume the timer."
            )
        if feedback is None and messages:
            feedback = messages[0]
        if feedback is None and target_reached:
            feedback = f"Target reached — {self.target_seconds}s held, nice work!"
        if feedback is None and holding_now:
            feedback = "Great cobra arch — keep holding!"
        if feedback is None:
            feedback = "Get back into Cobra Pose to resume the timer."

        response.update(
            {
                "lift_ratio": round(raw_lift, 3),
                "smoothed_lift_ratio": round(self.smoothed_lift, 3),
                "back_arch_angle": (
                    round(back_arch_angle, 1) if back_arch_angle is not None else None
                ),
                "left_elbow_angle": (
                    round(left_elbow_angle, 1) if left_elbow_angle is not None else None
                ),
                "right_elbow_angle": (
                    round(right_elbow_angle, 1)
                    if right_elbow_angle is not None
                    else None
                ),
                "hold_state": (
                    "holding"
                    if self.started and self.hold_active
                    else ("broken" if self.started else "not_started")
                ),
                "is_holding": holding_now,
                "target_reached": target_reached,
                "hold_quality": hold_quality,
                "posture_ok": len(issues) == 0,
                "posture_issues": issues,
                "posture_messages": messages,
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


class CobraPoseSession:
    """Full Cobra Pose session: one shared pose model + one analyzer.

    Same `target_seconds` / `target_sets` / `set_number` contract as
    `SidePlankSession` — the backend, not the frontend, is the source of
    truth for `session_complete` (this set is done) and `exercise_complete`
    (the whole assigned plan is done).
    """

    def __init__(
        self,
        target_seconds: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = CobraPoseAnalyzer(target_seconds)
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
