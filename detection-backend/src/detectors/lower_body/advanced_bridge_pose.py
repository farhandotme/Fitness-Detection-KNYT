"""
Advanced Bridge Pose (Urdhva Dhanurasana / Wheel Pose) — timed isometric
hold, judged from a side-on (profile) view.

This is a **hold timer**, not a rep counter — same family as
`hollow_hold.py` and `side_plank.py`. The timer pauses the instant the
pose breaks and resumes exactly where it left off; `hold_seconds` never
resets mid-session.

What "correct" means, derived directly from the reference images
------------------------------------------------------------------
Both hands AND both feet planted on the floor, arms and legs extending
up from the floor, and — the one thing that actually defines this pose —
the **hips are the highest point of the body**, arched up well above
both the shoulder line and the knee line, forming a clear dome/bridge
shape. That's the exact opposite shape from a hollow hold's shallow
banana curl (where the hips are deliberately the LOW point); here the
hips are unambiguously the HIGH point.

Four corroborating, calibration-free signals confirm that shape every
frame (no absolute floor calibration needed — only the relative
ordering/closeness of the joints matters, which is robust to camera
distance and doesn't degrade the way an absolute-position check would):

  1. **Arch angle** — angle(shoulder, hip, knee), vertex at the hip. A
     flat body reads ~180°; a deep backbend arch reads much smaller,
     since the hip juts up sharply between the shoulder and knee. This
     is the primary, most sensitive signal.
  2. **Hip above shoulder** — the hip must sit measurably higher (in
     the real world) than the shoulder.
  3. **Hip above knee** — same idea, against the knee.
  4. **Hands and feet at a similar height** — the wrist and ankle should
     both be near the same "ground level", since they're the two ends of
     the arch's base. If one is far higher than the other, the pose
     hasn't fully formed yet (e.g. feet are down but hands haven't been
     placed) or has broken down on one side.

All four use relative comparisons between the person's OWN joints
(normalized by their own body length), not fixed universal pixel
positions or a shoulder/hip-width ratio prone to noise when both terms
are small — see the note on `_view_mode` below for why that distinction
matters. Each signal has its own broken/resume hysteresis band (same
pattern as `hollow_hold.py`'s shoulder/leg-lift gates) so a single noisy
frame doesn't flicker the hold state; `holding_now` requires ALL FOUR to
currently read "not broken".

Soft flaws (rep — well, hold-second — still counts, tagged
`needs_improvement`)
-----------------------------------------------------------------------
  - Arms not fully extended (elbows bent a lot).
  - Legs not fully extended (knees bent a lot beyond what's normal for
    this pose — some knee bend is expected and visible in the reference
    images, so this only fires well past that).
  - Head/neck position drifting from the person's own calibrated
    neutral (same calibrated-baseline approach `side_plank.py` uses for
    its head-position check — there's no single universal "correct" head
    angle for this pose across body types, so it's graded against
    *your* settled position, not a fixed number).

Why `_view_mode` here is NOT the shoulder/hip-width ratio
------------------------------------------------------------------------
An earlier detector in this codebase (`front_leg_swing.py`) shipped with
a real bug: it classified side-vs-front using
`shoulder_width / hip_width`, which is fine for confirming FRONT (both
terms are large and stable) but breaks down for confirming SIDE, because
in profile both terms collapse toward zero and their ratio becomes noisy
and unstable — a genuine side-on stance could get randomly misread as
"front". This detector is also a side-view exercise, so it uses the
already-fixed version from the start: width is normalized against
**torso height** (shoulder-to-hip span), which stays stable regardless
of which way the person is facing, giving a reliable, well-separated
signal instead of a division of two noisy near-zero numbers.
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

SIDE_LANDMARKS = {
    "left": (LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE),
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


# ---- arch angle (shoulder-hip-knee, vertex at hip), degrees ----
# Smaller = deeper arch. Hysteresis: BROKEN is the easier-to-trigger exit
# (angle rising = flattening out), RESUME is the stricter re-entry.
ARCH_ANGLE_BROKEN = 155.0
ARCH_ANGLE_RESUME = 140.0
ANGLE_SMOOTH_ALPHA = 0.4  # EMA smoothing on all angle/ratio signals below

# ---- hip elevation vs shoulder/knee, fraction of body length ----
HIP_ABOVE_SHOULDER_BROKEN = 0.02
HIP_ABOVE_SHOULDER_RESUME = 0.05
HIP_ABOVE_KNEE_BROKEN = 0.02
HIP_ABOVE_KNEE_RESUME = 0.05

# ---- hands/feet at a similar "ground level", fraction of body length ----
BASE_LEVEL_DIFF_BROKEN = 0.45
BASE_LEVEL_DIFF_RESUME = 0.35

# ---- soft flaws (counted, tagged) ----
ARM_STRAIGHT_MIN = 140.0  # elbow angle
LEG_STRAIGHT_MIN = 110.0  # knee angle — some bend is normal/expected here
HEAD_ANGLE_DELTA = 18.0  # degrees of drift from the calibrated baseline
CALIBRATION_FRAMES = 15

MISTAKE_PENALTY = {
    "arms_bent": 12,
    "legs_bent": 12,
    "head_position": 8,
}
SCORE_HISTORY = 30
SCORE_SAMPLE_INTERVAL = 1.0  # seconds

# ---- view-mode classification — see module docstring for why this is
# torso-height-normalized rather than a shoulder/hip-width ratio. ----
SIDE_VIEW_WIDTH_TORSO_MAX = 0.35
FRONT_VIEW_WIDTH_TORSO_MIN = 0.55
VIEW_RATIO_SMOOTHING_ALPHA = 0.35

# Camera framing
FRAME_EDGE_MARGIN = 0.03
BODY_SPAN_TOO_CLOSE = 0.95
BODY_SPAN_TOO_FAR = 0.15


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


def _midpoint(a, b) -> _Point:
    return _Point((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)


def _bbox_aspect_points(points: list[_Point]) -> Optional[tuple[float, float]]:
    if len(points) < 4:
        return None
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    return (max(xs) - min(xs), max(ys) - min(ys))


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
                "hands to feet, fits in the shot."
            )

    box = _bbox_aspect_points(points)
    if box is None:
        return None
    width, height = box
    body_span = math.hypot(width, height)

    if body_span > BODY_SPAN_TOO_CLOSE:
        return "You're too close to the camera — move back so your whole body fits in frame."
    if body_span < BODY_SPAN_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


def _view_mode(width_signal: float, torso_height: float) -> str:
    """See module docstring — normalized against torso height (stable
    regardless of facing direction), not a shoulder/hip-width ratio."""
    ratio = width_signal / max(torso_height, 1e-6)
    if ratio <= SIDE_VIEW_WIDTH_TORSO_MAX:
        return "side"
    if ratio >= FRONT_VIEW_WIDTH_TORSO_MIN:
        return "front"
    return "angled"


class AdvancedBridgePoseAnalyzer:
    """Stateful advanced bridge pose (wheel pose) hold timer + posture
    checker. No `target_reps` here — the coach-assigned target is a
    duration, `target_seconds`, exactly like `HollowHoldAnalyzer`."""

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

        # Personal head/neck baseline — same calibrated-from-clean-holding-
        # frames approach as side_plank.py, since there's no single
        # universal "correct" head angle across body types for this pose.
        self._calib_samples: list[float] = []
        self.calibrated = False
        self._baseline_head_angle = 180.0

        # EMA smoothing state for the four gating signals.
        self._smoothed_arch_angle: Optional[float] = None
        self._smoothed_hip_above_shoulder: Optional[float] = None
        self._smoothed_hip_above_knee: Optional[float] = None
        self._smoothed_base_level_diff: Optional[float] = None
        self._smoothed_view_ratio: Optional[float] = None

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
        if (
            self.active_side is not None
            and vis[self.active_side] >= MIN_LANDMARK_VISIBILITY
        ):
            return self.active_side
        best_side = max(vis, key=lambda s: vis[s])
        return best_side if vis[best_side] >= MIN_LANDMARK_VISIBILITY else None

    @staticmethod
    def _smooth(prev: Optional[float], raw: float) -> float:
        if prev is None:
            return raw
        return ANGLE_SMOOTH_ALPHA * raw + (1 - ANGLE_SMOOTH_ALPHA) * prev

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "view_mode": None,
            "active_side": self.active_side,
            "arch_angle": None,
            "elbow_angle": None,
            "knee_angle": None,
            "head_angle": None,
            "hip_above_shoulder_ratio": None,
            "hip_above_knee_ratio": None,
            "base_level_diff_ratio": None,
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
                "Can't see your body clearly — make sure you're filmed "
                "side-on, hands to feet, whole body in frame."
            )
            response.update(self._progress_fields())
            return response

        s_idx, e_idx, w_idx, h_idx, k_idx, a_idx = SIDE_LANDMARKS[self.active_side]
        shoulder, elbow, wrist, hip, knee, ankle = (
            landmarks[s_idx],
            landmarks[e_idx],
            landmarks[w_idx],
            landmarks[h_idx],
            landmarks[k_idx],
            landmarks[a_idx],
        )
        ear = landmarks[LEFT_EAR if self.active_side == "left" else RIGHT_EAR]
        ear_ok = _visible((ear,))

        body_len = max(_dist(shoulder, ankle), 1e-6)
        torso_height = max(_dist(shoulder, hip), 1e-6)

        # ---- framing / orientation ----
        bbox_points = [
            _Point(p.x, p.y)
            for p in (shoulder, elbow, wrist, hip, knee, ankle)
            if _visible((p,))
        ]
        framing_message = _framing_feedback(bbox_points)

        # width_signal: reuse both shoulders if visible (more stable),
        # otherwise fall back to the active-side torso length itself.
        l_sh, r_sh = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        shoulder_width = _dist(l_sh, r_sh) if _visible((l_sh, r_sh)) else 0.0
        hip_width = _dist(l_hip, r_hip) if _visible((l_hip, r_hip)) else 0.0
        raw_view_ratio = max(shoulder_width, hip_width) / torso_height
        self._smoothed_view_ratio = self._smooth(
            self._smoothed_view_ratio, raw_view_ratio
        )
        view_mode = _view_mode(self._smoothed_view_ratio, 1.0)
        response["view_mode"] = view_mode

        side_on = view_mode == "side"

        # ---- core gating signals (all relative comparisons — see
        # module docstring for why this avoids the front_leg_swing bug) ----
        raw_arch_angle = _angle_deg(shoulder, hip, knee)
        raw_hip_above_shoulder = (shoulder.y - hip.y) / body_len
        raw_hip_above_knee = (knee.y - hip.y) / body_len
        raw_base_level_diff = abs(wrist.y - ankle.y) / body_len

        self._smoothed_arch_angle = self._smooth(
            self._smoothed_arch_angle, raw_arch_angle
        )
        self._smoothed_hip_above_shoulder = self._smooth(
            self._smoothed_hip_above_shoulder, raw_hip_above_shoulder
        )
        self._smoothed_hip_above_knee = self._smooth(
            self._smoothed_hip_above_knee, raw_hip_above_knee
        )
        self._smoothed_base_level_diff = self._smooth(
            self._smoothed_base_level_diff, raw_base_level_diff
        )

        arch_angle = self._smoothed_arch_angle
        hip_above_shoulder = self._smoothed_hip_above_shoulder
        hip_above_knee = self._smoothed_hip_above_knee
        base_level_diff = self._smoothed_base_level_diff

        response["arch_angle"] = round(arch_angle, 1)
        response["hip_above_shoulder_ratio"] = round(hip_above_shoulder, 3)
        response["hip_above_knee_ratio"] = round(hip_above_knee, 3)
        response["base_level_diff_ratio"] = round(base_level_diff, 3)

        elbow_angle = _angle_deg(shoulder, elbow, wrist)
        knee_angle = _angle_deg(hip, knee, ankle)
        response["elbow_angle"] = round(elbow_angle, 1)
        response["knee_angle"] = round(knee_angle, 1)

        # ---- resolve each signal's broken/resume state, hysteresis-gated ----
        if self.hold_active:
            arch_broken = arch_angle > ARCH_ANGLE_BROKEN
            hip_sh_broken = hip_above_shoulder < HIP_ABOVE_SHOULDER_BROKEN
            hip_kn_broken = hip_above_knee < HIP_ABOVE_KNEE_BROKEN
            base_broken = base_level_diff > BASE_LEVEL_DIFF_BROKEN
        else:
            arch_broken = arch_angle > ARCH_ANGLE_RESUME
            hip_sh_broken = hip_above_shoulder < HIP_ABOVE_SHOULDER_RESUME
            hip_kn_broken = hip_above_knee < HIP_ABOVE_KNEE_RESUME
            base_broken = base_level_diff > BASE_LEVEL_DIFF_RESUME

        holding_now = (
            framing_message is None
            and side_on
            and not arch_broken
            and not hip_sh_broken
            and not hip_kn_broken
            and not base_broken
        )

        # ---- calibrate head baseline from clean, currently-holding frames ----
        if not self.calibrated and holding_now and ear_ok:
            head_angle_sample = _angle_deg(ear, shoulder, hip)
            self._calib_samples.append(head_angle_sample)
            if len(self._calib_samples) >= CALIBRATION_FRAMES:
                self._finish_calibration()

        head_angle = _angle_deg(ear, shoulder, hip) if ear_ok else None
        response["head_angle"] = (
            round(head_angle, 1) if head_angle is not None else None
        )

        # ---- form tiering (only meaningful while holding) ----
        issues: list[str] = []
        messages: list[str] = []
        if holding_now:
            if elbow_angle < ARM_STRAIGHT_MIN:
                issues.append("arms_bent")
                messages.append("Straighten your arms more — push the floor away.")
            if knee_angle < LEG_STRAIGHT_MIN:
                issues.append("legs_bent")
                messages.append("Straighten your legs more — push through your heels.")
            if self.calibrated and head_angle is not None:
                if abs(head_angle - self._baseline_head_angle) > HEAD_ANGLE_DELTA:
                    issues.append("head_position")
                    messages.append(
                        "Relax your neck — let your head hang back evenly, don't "
                        "tuck or strain it."
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

        # ---- feedback priority: framing > orientation > hard break > flaws > praise ----
        feedback = framing_message
        if feedback is None and not side_on:
            feedback = (
                "Turn side-on to the camera — I need a side view of your "
                "whole body to check this pose."
            )
        if feedback is None and (arch_broken or hip_sh_broken or hip_kn_broken):
            feedback = (
                "Push your hips up higher — they need to be the highest "
                "point of your body, arched well above your shoulders and knees."
            )
        if feedback is None and base_broken:
            feedback = (
                "Make sure both hands and both feet are firmly planted on the floor."
            )
        if feedback is None and messages:
            feedback = messages[0]
        if feedback is None and not self.calibrated and holding_now:
            feedback = "Great bridge — hold it, calibrating your baseline."
        if feedback is None and target_reached:
            feedback = f"Target reached — {self.target_seconds}s held, beautiful work!"
        if feedback is None and holding_now:
            feedback = "Strong bridge — keep holding!"
        if feedback is None:
            feedback = "Get back into the bridge to resume the timer."

        response.update(
            {
                "pose_detected": True,
                "active_side": self.active_side,
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


class AdvancedBridgePoseSession:
    """Full advanced bridge pose session: one shared pose model + one
    analyzer. `target_seconds` / `target_sets` / `set_number` are the
    coach-assigned plan for this user, supplied by the caller (the
    websocket route, from query params) — same convention as
    `HollowHoldSession`."""

    def __init__(
        self,
        target_seconds: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = AdvancedBridgePoseAnalyzer(target_seconds)
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
