"""
Butt Kicks analyzer.

Design brief (why this looks different from pushup.py / side_plank.py):
this is a FAST, alternating cardio drill. The #1 failure mode to avoid is
a false negative — the user kicking correctly but the counter missing it
because it was waiting for a clean, slow, fully-formed rep. So unlike the
push-up analyzer (which actively invalidates reps that are "too fast" or
"too short" in range), this analyzer never rejects a rep for being quick.
Speed is the point of the exercise, not a disqualifier.

Primary signal per leg (left / right tracked completely independently):
  - knee flexion angle (hip-knee-ankle) — a tight bend is the clearest,
    least occlusion-prone signal for "this leg just kicked".
  - heel lift relative to the knee (knee.y vs heel.y, normalized by shin
    length) — directly measures the heel traveling up toward the glute.
    Falls back to knee/ankle-only motion if the heel landmark itself is
    low-visibility (partial occlusion, motion blur).

Both signals are combined into a single 0-1 `kick_score` per leg and
counted with a wide hysteresis band (UP_THRESHOLD / DOWN_THRESHOLD) —
not a rigid state machine that needs a static pause at the top. A short
missed-frame hold buffer keeps a leg's state alive for a few frames of
occlusion or bad tracking instead of instantly resetting the rep attempt,
so a heel briefly leaving frame mid-kick doesn't cost the rep.
"""

import math
from collections import deque
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_HEEL,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_HEEL,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
)

# -------------------------------------------------------------------------
# Tunable constants
# -------------------------------------------------------------------------

MIN_LANDMARK_VISIBILITY = 0.35  # looser than pushup's 0.4 — fast motion blur
# routinely tanks MediaPipe's visibility score on correctly-tracked joints.

# Kick-score hysteresis (0-1 combined knee-flexion + heel-lift score).
# Wide gap on purpose: narrow bands cause double-counting on tracking
# jitter, which is the opposite failure mode from what we're optimizing
# for, but too narrow a gap also re-arms too early. This gap is a
# deliberate middle ground favoring "count it" over "reject it".
KICK_UP_THRESHOLD = 0.42
KICK_DOWN_THRESHOLD = 0.24

MIN_KICK_INTERVAL_S = 0.10  # debounce only — never used to invalidate a rep

# Missed-frame / occlusion hold buffer: a leg's tracking can drop out for
# a few frames (motion blur, brief occlusion by the other leg) without
# losing progress on an in-flight kick.
OCCLUSION_HOLD_FRAMES = 6

# Framing / "ready to count" gate — deliberately easy to satisfy. This is
# NOT a strict pose gate like the push-up floor check; it only exists to
# stop counting phantom kicks from an empty or badly-framed shot.
STABLE_READY_FRAMES = 3
GRACE_FRAMES = 15  # generous — fast cardio produces more tracking noise

TORSO_INCLINE_STANDING_MIN_DEG = 50.0  # near-vertical torso == standing
FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.97
BBOX_TOO_FAR = 0.12

# Soft form-quality thresholds (never block counting, only annotate).
SHALLOW_KICK_FLEX_SCORE = 0.32
FORWARD_LEAN_DEG = 28.0
SIDE_SWAY_RATIO = 0.14  # hip-x deviation / shoulder width

CADENCE_WINDOW = 8  # reps used for the rolling cadence estimate

# -------------------------------------------------------------------------
# Small geometry helpers (same conventions as pushup.py / side_plank.py)
# -------------------------------------------------------------------------


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


def _clip01(v: float) -> float:
    return 0.0 if v < 0 else (1.0 if v > 1 else v)


def _torso_incline_deg(mid_shoulder, mid_hip) -> Optional[float]:
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
                "You're partly out of frame — step back so your full body is visible."
            )

    if len(points) < 4:
        return None

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return (
            "You're too close to the camera — back up so your legs are fully visible."
        )
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class _LegSignal:
    """Per-frame geometry for one leg (left or right)."""

    __slots__ = (
        "visible",
        "heel_visible",
        "knee_flexion_deg",
        "heel_lift_deg",
        "flex_score",
        "heel_score",
        "kick_score",
    )

    def __init__(self):
        self.visible = False
        self.heel_visible = False
        self.knee_flexion_deg: Optional[float] = None
        self.heel_lift_deg: Optional[float] = None
        self.flex_score = 0.0
        self.heel_score = 0.0
        self.kick_score = 0.0


def _compute_leg_signal(hip, knee, ankle, heel) -> _LegSignal:
    sig = _LegSignal()

    leg_ok = _visible((hip, knee, ankle))
    sig.visible = leg_ok
    if not leg_ok:
        return sig

    knee_angle = _angle_deg(hip, knee, ankle)
    sig.knee_flexion_deg = knee_angle
    # 170-180deg == leg straight (standing). ~70deg == sharply bent (kicked).
    # Deliberately wide/lenient band so a real fast kick doesn't need to
    # reach an extreme angle to register.
    sig.flex_score = _clip01((160.0 - knee_angle) / 90.0)
    sig.heel_lift_deg = 180.0 - knee_angle  # proxy: how far heel has risen

    heel_ok = heel is not None and _visible((heel,))
    sig.heel_visible = heel_ok
    if heel_ok:
        shin_len = max(_dist(knee, ankle), 1e-4)
        heel_lift_ratio = (knee.y - heel.y) / shin_len
        sig.heel_score = _clip01((heel_lift_ratio + 0.5) / 1.0)
        sig.kick_score = max(sig.flex_score, sig.heel_score)
    else:
        # Heel occluded/blurred — fall back to knee+ankle motion alone,
        # per the spec's explicit fallback requirement.
        sig.kick_score = sig.flex_score

    return sig


class _LegTracker:
    """Hysteresis rep counter + occlusion hold buffer for a single leg."""

    def __init__(self, side: str):
        self.side = side
        self.stage = "down"  # "down" (armed, ready to kick) / "up" (kicked)
        self.reps = 0
        self.last_kick_time: Optional[float] = None
        self.rep_start_time: Optional[float] = None
        self.peak_flex_score = 0.0
        self.occlusion_streak = 0
        self.held_score = 0.0
        self.current_rep_issues: set[str] = set()

    def update(
        self, sig: _LegSignal, t: float
    ) -> tuple[bool, Optional[float], set[str]]:
        """Returns (rep_completed, rep_duration, issues_for_completed_rep)."""
        if not sig.visible:
            self.occlusion_streak += 1
            if self.occlusion_streak > OCCLUSION_HOLD_FRAMES:
                # Occlusion outlasted the hold buffer — bail out of any
                # in-flight kick attempt cleanly rather than leaving it
                # stuck forever, but don't punish reps already counted.
                self.stage = "down"
                self.rep_start_time = None
                self.peak_flex_score = 0.0
                self.current_rep_issues = set()
            return False, None, set()

        self.occlusion_streak = 0
        score = sig.kick_score
        self.held_score = score

        rep_completed = False
        rep_duration = None
        completed_issues: set[str] = set()

        if self.stage == "down" and score >= KICK_UP_THRESHOLD:
            self.stage = "up"
            self.rep_start_time = t
            self.peak_flex_score = sig.flex_score
            self.current_rep_issues = set()
        elif self.stage == "up":
            self.peak_flex_score = max(self.peak_flex_score, sig.flex_score)
            if score <= KICK_DOWN_THRESHOLD:
                self.stage = "down"
                too_soon = (
                    self.last_kick_time is not None
                    and (t - self.last_kick_time) < MIN_KICK_INTERVAL_S
                )
                if not too_soon:
                    rep_duration = (
                        (t - self.rep_start_time)
                        if self.rep_start_time is not None
                        else None
                    )
                    if self.peak_flex_score < SHALLOW_KICK_FLEX_SCORE:
                        self.current_rep_issues.add("shallow_kick")
                    self.reps += 1
                    self.last_kick_time = t
                    rep_completed = True
                    completed_issues = set(self.current_rep_issues)
                self.rep_start_time = None
                self.peak_flex_score = 0.0
                self.current_rep_issues = set()

        return rep_completed, rep_duration, completed_issues


def _classify_tempo(duration: Optional[float]) -> Optional[str]:
    """Purely descriptive — NEVER used to reject a rep. Fast is good here."""
    if duration is None:
        return None
    if duration <= 0.35:
        return "blazing"
    if duration <= 0.6:
        return "fast"
    if duration <= 1.0:
        return "good"
    if duration <= 1.6:
        return "slow"
    return "too_slow"


class ButtKicksAnalyzer:
    """Stateful butt-kicks rep counter: two independent per-leg hysteresis
    trackers plus lenient framing/posture gating and soft form coaching."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.left = _LegTracker("left")
        self.right = _LegTracker("right")

        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        self.session_start_time: Optional[float] = None

        self._ready_streak = 0
        self._bad_streak = 0
        self.ready = False

        self._hip_x_baseline: Optional[float] = None
        self._motion_confidence_smoothed = 0.0

        self._rep_times: deque[float] = deque(maxlen=CADENCE_WINDOW)

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

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
            "stage": "neutral",
            "rep_count": self.rep_count,
            "left_reps": self.left.reps,
            "right_reps": self.right.reps,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_side": None,
            "rep_duration": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "current_side": None,
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
            "current_kick_side": None,
            "heel_lift_deg": None,
            "knee_flexion_deg": None,
            "kick_peak_score": 0.0,
            "cadence_estimate": self._cadence_estimate(),
            "motion_confidence": round(self._motion_confidence_smoothed, 2),
        }

        if landmarks is None:
            response["feedback"] = "No person detected — step into frame."
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]
        l_heel, r_heel = landmarks[LEFT_HEEL], landmarks[RIGHT_HEEL]

        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
        left_leg_ok = _visible((l_hip, l_knee, l_ankle))
        right_leg_ok = _visible((r_hip, r_knee, r_ankle))

        if not torso_visible or (not left_leg_ok and not right_leg_ok):
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your legs clearly — step back so your hips, "
                "knees, and ankles are all in frame."
            )
            return response

        response["pose_detected"] = True

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        shoulder_width = max(_dist(l_shoulder, r_shoulder), 1e-4)

        bbox_candidates = [
            p
            for p in (
                l_shoulder,
                r_shoulder,
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

        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        torso_incline = _torso_incline_deg(mid_shoulder, mid_hip)
        is_standing = (
            torso_incline is not None
            and torso_incline >= TORSO_INCLINE_STANDING_MIN_DEG
            and mid_hip.y < ((l_ankle.y + r_ankle.y) / 2.0)
        )
        has_a_leg = left_leg_ok or right_leg_ok

        if is_standing and has_a_leg:
            self._ready_streak += 1
            self._bad_streak = 0
        else:
            self._ready_streak = 0
            self._bad_streak += 1

        if self._ready_streak >= STABLE_READY_FRAMES:
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES:
            self.ready = False
        # else: keep previous ready state — short grace period for noise,
        # matching the "don't punish a brief tracking blip" requirement.

        response["ready"] = self.ready
        response["position_ok"] = self.ready

        if not is_standing:
            response["position_message"] = (
                "Stand tall with your knees and ankles visible in frame — "
                "then start kicking your heels toward your glutes."
            )
        elif not has_a_leg:
            response["position_message"] = (
                "Can't see either leg clearly — reposition the camera."
            )
        else:
            response["position_message"] = None

        # ---- soft posture cues (never block counting) ----
        lean_deg = (90.0 - torso_incline) if torso_incline is not None else 0.0
        leaning_forward = lean_deg > FORWARD_LEAN_DEG

        if self._hip_x_baseline is None:
            self._hip_x_baseline = mid_hip.x
        else:
            self._hip_x_baseline = 0.9 * self._hip_x_baseline + 0.1 * mid_hip.x
        sway_ratio = abs(mid_hip.x - self._hip_x_baseline) / shoulder_width
        excessive_sway = sway_ratio > SIDE_SWAY_RATIO

        # ---- per-leg kick signals + rep state machines ----
        left_sig = (
            _compute_leg_signal(l_hip, l_knee, l_ankle, l_heel)
            if left_leg_ok
            else _LegSignal()
        )
        right_sig = (
            _compute_leg_signal(r_hip, r_knee, r_ankle, r_heel)
            if right_leg_ok
            else _LegSignal()
        )

        visibilities = []
        for lm in (l_hip, r_hip, l_knee, r_knee, l_ankle, r_ankle, l_heel, r_heel):
            v = getattr(lm, "visibility", None)
            if v is not None:
                visibilities.append(v)
        frame_confidence = (
            sum(visibilities) / len(visibilities) if visibilities else 0.0
        )
        self._motion_confidence_smoothed = (
            0.7 * self._motion_confidence_smoothed + 0.3 * frame_confidence
        )

        feedback = framing_message

        rep_completed = False
        rep_side = None
        rep_duration = None
        rep_class = None
        rep_form_quality = None
        current_kick_side = None
        stage = "neutral"

        if self.ready:
            left_completed, left_dur, left_issues = self.left.update(left_sig, t)
            right_completed, right_dur, right_issues = self.right.update(right_sig, t)

            if self.left.stage == "up" and self.right.stage == "up":
                stage = "both_kick"
            elif self.left.stage == "up":
                stage = "left_kick"
            elif self.right.stage == "up":
                stage = "right_kick"
            else:
                stage = "ready"

            if self.left.stage == "up":
                current_kick_side = "left"
            elif self.right.stage == "up":
                current_kick_side = "right"

            # A frame can only report one completed rep — if both legs
            # somehow crossed the line the same frame (fast + noisy), take
            # the earlier-armed one this tick and let the other land next
            # frame; it is still counted, just reported one frame later.
            if left_completed:
                rep_completed = True
                rep_side = "left"
                rep_duration = left_dur
                issues = left_issues
                if leaning_forward:
                    issues = issues | {"leaning_forward"}
                if excessive_sway:
                    issues = issues | {"side_sway"}
            elif right_completed:
                rep_completed = True
                rep_side = "right"
                rep_duration = right_dur
                issues = right_issues
                if leaning_forward:
                    issues = issues | {"leaning_forward"}
                if excessive_sway:
                    issues = issues | {"side_sway"}
            else:
                issues = set()

            if rep_completed:
                self.rep_count += 1
                self._rep_times.append(t)
                rep_class = _classify_tempo(rep_duration)

                if issues:
                    rep_form_quality = "needs_improvement"
                    self.flawed_reps += 1
                    issue_text = ", ".join(i.replace("_", " ") for i in sorted(issues))
                    feedback = f"Rep {self.rep_count} counted — {issue_text}."
                else:
                    rep_form_quality = "good"
                    self.good_reps += 1
                    feedback = f"Nice kick, {rep_side} side — {self.rep_count} total."
        else:
            stage = "neutral"

        if feedback is None and leaning_forward:
            feedback = "Chest up — you're leaning too far forward."
        if feedback is None and excessive_sway:
            feedback = "Keep your torso steady — less side-to-side sway."
        if feedback is None and not self.ready:
            feedback = response["position_message"] or (
                "Stand tall and start alternating heel kicks to your glutes."
            )
        if feedback is None:
            feedback = "Good rhythm — keep alternating."

        active_sig = None
        if current_kick_side == "left":
            active_sig = left_sig
        elif current_kick_side == "right":
            active_sig = right_sig
        elif left_sig.kick_score >= right_sig.kick_score:
            active_sig = left_sig if left_sig.visible else right_sig
        else:
            active_sig = right_sig if right_sig.visible else left_sig

        response.update(
            {
                "stage": stage,
                "rep_count": self.rep_count,
                "left_reps": self.left.reps,
                "right_reps": self.right.reps,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_side": rep_side,
                "rep_duration": rep_duration,
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "current_side": current_kick_side,
                "feedback": feedback,
                "current_kick_side": current_kick_side,
                "heel_lift_deg": (
                    round(active_sig.heel_lift_deg, 1)
                    if active_sig and active_sig.heel_lift_deg is not None
                    else None
                ),
                "knee_flexion_deg": (
                    round(active_sig.knee_flexion_deg, 1)
                    if active_sig and active_sig.knee_flexion_deg is not None
                    else None
                ),
                "kick_peak_score": round(
                    max(left_sig.kick_score, right_sig.kick_score), 2
                ),
                "cadence_estimate": self._cadence_estimate(),
                "motion_confidence": round(self._motion_confidence_smoothed, 2),
            }
        )
        return response

    def _cadence_estimate(self) -> Optional[float]:
        """Kicks per minute, averaged over the last few completed reps
        across both legs combined."""
        if len(self._rep_times) < 2:
            return None
        span = self._rep_times[-1] - self._rep_times[0]
        if span <= 0:
            return None
        intervals = len(self._rep_times) - 1
        avg_interval = span / intervals
        if avg_interval <= 0:
            return None
        return round(60.0 / avg_interval, 1)


class ButtKicksSession:
    """Full butt-kicks session: one shared pose model + one analyzer.

    Same `target_reps` / `target_sets` / `set_number` contract as
    `PushupSession` — the backend, not the frontend, decides when a set or
    the whole assigned plan is complete.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = ButtKicksAnalyzer(target_reps)
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
