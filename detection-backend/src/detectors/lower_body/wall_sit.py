"""
Wall sit hold timing + posture correction.

Design
------
Same family as `PlankHoldAnalyzer` / `SidePlankAnalyzer` — a wall sit has
no reps, it's a single continuous timed position, so this does **not**
run an up/down rep state machine. It runs the identical **hold timer that
only advances while the person is verified, frame by frame, to actually
be in a correct wall sit**:

    * The instant form breaks (standing up, sliding down, drifting into a
      free squat, or the camera losing the person) the timer **pauses**.
      It never silently resets to zero, so accumulated `hold_seconds` is
      monotonic for the lifetime of a set. `current_streak_seconds` (time
      since the last break) is what resets, giving live feedback on the
      *current* attempt without punishing total progress.
    * The instant good form resumes, the timer picks back up from exactly
      where it left off.

Camera framing
---------------
Unlike a plank or side plank (judged side-on), a wall sit is judged from
a **front-facing or slight front-angle view** — the person faces the
camera with their back against a wall behind them. There's no landmark
for the wall itself, so "back flat against the wall" is inferred from
**torso verticality**: in a real wall sit the torso reads as close to
plumb-vertical in the image, because the wall is holding it upright. A
regular free-standing squat, by contrast, has the torso pitch forward to
keep balance over the feet. That single distinction — torso lean angle —
is what keeps this detector from counting a normal squat as a wall sit.

Form signal
-----------
Three angles, all evaluated on whichever leg(s) are trustworthy this
frame (see `_pick_legs`):

  * `torso_lean_angle` = angle of the shoulder->hip vector from vertical,
    in degrees. ~0° is plumb-straight (back reads flat against the wall).
    This is the primary squat-vs-wall-sit discriminator.
  * `knee_angle` = angle(hip, knee, ankle). ~90° is a classic wall sit
    (thighs parallel to the floor); this is allowed a generous band since
    the brief says "do not require a perfect 90-degree angle."
  * `hip_angle` = angle(shoulder, hip, knee). Confirms the torso and
    thigh are folded into a seated relationship (rather than, say, a
    standing person who merely leans their shoulders back).

A softer, secondary signal:

  * `shin_angle` = angle of the ankle->knee vector from vertical. Near 0°
    means the knee is stacked over the ankle; a large value means the
    knee has drifted forward of the foot (or the feet are placed at the
    wrong distance from the wall). This is graded as a form note, not a
    hard break — plenty of usable wall sits run a little knee-forward.

Only torso lean and knee/hip angle (the "is this even a wall sit, and is
it in the seated zone" checks) pause the timer. Shin drift and knee
symmetry are graded as form notes only, same tier as the side plank's
knee/head notes — this keeps a slightly imperfect wall sit counting while
still coaching the user toward a cleaner one.
"""

import math
from collections import deque
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

LEG_LANDMARKS = {
    "left": (LEFT_SHOULDER, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE),
    "right": (RIGHT_SHOULDER, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE),
}
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)

# ---- torso lean angle (shoulder-hip vector vs vertical), degrees ----
# Hysteresis: once holding, only leaning past TORSO_LEAN_BREAK pauses the
# timer (drifting into a free squat); once broken/not-started, the torso
# has to come back under TORSO_LEAN_RESUME to start it again. Stops a
# borderline lean from flickering holding/broken every other frame.
TORSO_LEAN_BREAK = 34.0
TORSO_LEAN_RESUME = 26.0
TORSO_LEAN_IDEAL = 14.0  # at/below this, torso tier is "good" (no flaw)

# ---- knee angle (hip-knee-ankle), degrees ----
# Generous band — "a few degrees off a perfect 90 still counts."
KNEE_TOO_HIGH_BREAK = 132.0  # standing up too far
KNEE_TOO_HIGH_RESUME = 122.0
KNEE_TOO_LOW_BREAK = 55.0  # sliding into a near-sit / resting position
KNEE_TOO_LOW_RESUME = 65.0
KNEE_IDEAL_LOW = 78.0
KNEE_IDEAL_HIGH = 102.0

# ---- hip angle (shoulder-hip-knee), degrees ----
# Confirms a folded, seated relationship between torso and thigh, not
# just "shoulders leaned back while still basically standing."
HIP_ANGLE_BREAK = 130.0
HIP_ANGLE_RESUME = 118.0

# ---- shin angle (ankle-knee vector vs vertical), degrees — form note only ----
SHIN_FLAW_ABOVE = 22.0

# ---- knee symmetry (both legs visible only) ----
# Ratio of knee-to-knee horizontal gap over hip-to-hip (and separately
# ankle-to-ankle) horizontal gap. Well below 1.0 on BOTH comparisons =
# knees pinching inward (valgus).
KNEE_VALGUS_RATIO = 0.55

# The knee-gap comparison above is only meaningful from a reasonably
# frontal view. From an angled/turned camera, perspective foreshortening
# compresses the knee-to-knee gap more than the hip-to-hip gap even with
# knees perfectly stacked, which would otherwise read as a false "caving
# in" for the entire hold. `FRONTALITY_Z_MAX` gates the check off when
# the shoulders' relative depth (MediaPipe's z) says the view isn't
# frontal enough to trust it. `VALGUS_CONFIRM_FRAMES` additionally
# requires the pinch to show up for several consecutive frames before it
# counts as a real issue, so a single noisy frame can't flip the whole
# hold to "flawed" (same forgiving-of-glitches principle as the rest of
# this detector).
FRONTALITY_Z_MAX = 0.15
VALGUS_CONFIRM_FRAMES = 5

# Per-issue form_score penalty (applied per frame while holding).
MISTAKE_PENALTY = {
    "torso_lean": 20,
    "knees_forward": 12,
    "not_quite_parallel": 10,
    "knee_valgus": 14,
    "hands_on_thighs": 6,
}

# form_score is sampled into this rolling window roughly once a second
# (not every frame) so `avg_form_score` reflects the last ~SCORE_HISTORY
# seconds of holding rather than being dominated by frame rate.
SCORE_HISTORY = 30
SCORE_SAMPLE_INTERVAL = 1.0  # seconds

# Standing-baseline calibration — captured from the first stretch of
# frames where the person reads as upright and still, before they slide
# down into the hold. Used only to report `hip_drop_fraction`, a friendly
# "how far down are you" number; it never gates the timer.
CALIBRATION_FRAMES = 12
STANDING_KNEE_ANGLE_MIN = 160.0
STANDING_TORSO_LEAN_MAX = 12.0

# -------------------------------------------------------------------------
# Camera framing thresholds (front-facing / slight-angle view — body
# should read as roughly upright and fully in frame, not lying down).
# -------------------------------------------------------------------------
FRAME_EDGE_MARGIN = 0.03
BODY_SPAN_TOO_CLOSE = (
    0.92  # shoulder-to-ankle span as a fraction of frame height: too large = too close
)
BODY_SPAN_TOO_FAR = 0.30  # too small = too far away
MIN_UPRIGHT_RATIO = 0.9  # |dy|/|dx| of shoulder->ankle below this = too horizontal (lying down, bad framing)


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 3


def _visible(points) -> bool:
    for p in points:
        if p is None:
            return False
        v = getattr(p, "visibility", None)
        if v is not None and v < MIN_LANDMARK_VISIBILITY:
            return False
    return True


def _leg_visibility(landmarks, side: str) -> float:
    """Lowest visibility score among the four landmarks that make up
    `side` — a conservative "can we trust this leg at all" score."""
    scores = []
    for idx in LEG_LANDMARKS[side]:
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


def _vertical_deviation_deg(top, bottom) -> float:
    """Angle of the vector top->bottom from straight-down vertical, in
    degrees. 0° = perfectly plumb. Used for both torso lean (shoulder ->
    hip) and shin angle (knee -> ankle)."""
    dx = bottom.x - top.x
    dy = bottom.y - top.y
    if dx == 0 and dy == 0:
        return 0.0
    ang = math.degrees(math.atan2(abs(dx), abs(dy))) if dy != 0 else 90.0
    return ang


class _Avg:
    """Tiny helper: average of up to two `_Point`-like landmarks."""

    __slots__ = ("x", "y", "visibility")

    def __init__(self, a, b=None):
        if b is None:
            self.x, self.y = a.x, a.y
            self.visibility = a.visibility
        else:
            self.x = (a.x + b.x) / 2
            self.y = (a.y + b.y) / 2
            self.visibility = min(
                a.visibility if a.visibility is not None else 0.0,
                b.visibility if b.visibility is not None else 0.0,
            )


def _framing_feedback(shoulder, hip, ankle) -> Optional[str]:
    """Coaches the user into a good spot for the camera to judge a wall
    sit from — checked every frame, independent of exercise form.

    Checks, in order of how badly they break tracking:
      1. Part of the body clipped at a frame edge.
      2. Lying down / too horizontal instead of upright — most likely bad
         camera placement rather than a real attempt.
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
                "You're partly out of frame — reposition so your whole "
                "body, head to feet, fits in the shot."
            )

    dx = abs(ankle.x - shoulder.x)
    dy = abs(ankle.y - shoulder.y)
    if dy < 1e-6 or (dx / dy) > (1.0 / MIN_UPRIGHT_RATIO):
        return (
            "I need an upright, front-facing view — stand facing the "
            "camera with your back to the wall behind you."
        )

    body_span = math.hypot(dx, dy)
    if body_span > BODY_SPAN_TOO_CLOSE:
        return "You're too close to the camera — step back until your whole body fits in frame."
    if body_span < BODY_SPAN_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class WallSitAnalyzer:
    """Stateful wall-sit-hold timer + posture checker.

    No `target_reps` here — the coach-assigned target is a duration,
    `target_seconds`. `session_complete` is `hold_seconds >= target_seconds`,
    exactly mirroring `PlankHoldAnalyzer` / `SidePlankAnalyzer`.
    """

    def __init__(self, target_seconds: Optional[int] = None):
        self.target_seconds = target_seconds

        self.legs_tracked: Optional[str] = None  # "both" | "left" | "right"

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

        # Standing-baseline calibration (see module docstring) — purely
        # informational (`hip_drop_fraction`), never gates the timer.
        self._calib_samples: list[tuple[float, float]] = []  # (hip_y, leg_len)
        self.calibrated = False
        self._baseline_hip_y = None
        self._baseline_leg_len = None

        self.form_scores: deque[int] = deque(maxlen=SCORE_HISTORY)
        self._last_score_sample_time: Optional[float] = None

        # Consecutive-frame counter used to confirm a real knee-valgus
        # pinch before it's reported as an issue (see FRONTALITY_Z_MAX /
        # VALGUS_CONFIRM_FRAMES above).
        self._valgus_streak = 0

    # ---------------------------------------------------------------
    def _is_complete(self) -> bool:
        return (
            self.target_seconds is not None and self.hold_seconds >= self.target_seconds
        )

    def _finish_calibration(self):
        n = len(self._calib_samples)
        self._baseline_hip_y = sum(s[0] for s in self._calib_samples) / n
        self._baseline_leg_len = sum(s[1] for s in self._calib_samples) / n
        self.calibrated = True

    def _pick_legs(self, landmarks):
        """Returns (mode, shoulder, hip, knee, ankle) where `mode` is
        "both" (averaged), "left", or "right" — whichever legs are
        trustworthy this frame. Prefers "both" when available since
        averaging smooths out single-frame jitter and lets a knee-valgus
        check run."""
        vis = {side: _leg_visibility(landmarks, side) for side in ("left", "right")}
        left_ok = vis["left"] >= MIN_LANDMARK_VISIBILITY
        right_ok = vis["right"] >= MIN_LANDMARK_VISIBILITY

        if left_ok and right_ok:
            ls, lh, lk, la = LEG_LANDMARKS["left"]
            rs, rh, rk, ra = LEG_LANDMARKS["right"]
            shoulder = _Avg(landmarks[ls], landmarks[rs])
            hip = _Avg(landmarks[lh], landmarks[rh])
            knee = _Avg(landmarks[lk], landmarks[rk])
            ankle = _Avg(landmarks[la], landmarks[ra])
            return "both", shoulder, hip, knee, ankle

        # Fall back to keeping whichever single side is usable — prefer
        # staying on the previously-tracked side to avoid flicker.
        for side in (self.legs_tracked, "left", "right"):
            if side in ("left", "right") and vis[side] >= MIN_LANDMARK_VISIBILITY:
                s_idx, h_idx, k_idx, a_idx = LEG_LANDMARKS[side]
                return (
                    side,
                    _Avg(landmarks[s_idx]),
                    _Avg(landmarks[h_idx]),
                    _Avg(landmarks[k_idx]),
                    _Avg(landmarks[a_idx]),
                )

        return None, None, None, None, None

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "legs_tracked": self.legs_tracked,
            "torso_lean_angle": None,
            "knee_angle": None,
            "hip_angle": None,
            "shin_angle": None,
            "hip_drop_fraction": None,
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
                "No person detected — stand facing the camera with your "
                "back against the wall."
            )
            response.update(self._progress_fields())
            return response

        mode, shoulder, hip, knee, ankle = self._pick_legs(landmarks)
        self.legs_tracked = mode
        if mode is None:
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._register_broken_frame()
            response["feedback"] = (
                "Can't see your legs clearly — step back so your whole "
                "body is visible to the camera."
            )
            response.update(self._progress_fields())
            return response

        framing_message = _framing_feedback(shoulder, hip, ankle)

        torso_lean_angle = _vertical_deviation_deg(shoulder, hip)
        knee_angle = _angle_deg(hip, knee, ankle)
        hip_angle = _angle_deg(shoulder, hip, knee)
        shin_angle = _vertical_deviation_deg(knee, ankle)

        # ---- resolve hold-validity this frame (with hysteresis) ----
        if self.hold_active:
            torso_broken = torso_lean_angle > TORSO_LEAN_BREAK
            knee_too_high = knee_angle > KNEE_TOO_HIGH_BREAK
            knee_too_low = knee_angle < KNEE_TOO_LOW_BREAK
            hip_broken = hip_angle > HIP_ANGLE_BREAK
        else:
            torso_broken = torso_lean_angle > TORSO_LEAN_RESUME
            knee_too_high = knee_angle > KNEE_TOO_HIGH_RESUME
            knee_too_low = knee_angle < KNEE_TOO_LOW_RESUME
            hip_broken = hip_angle > HIP_ANGLE_RESUME

        hard_break = torso_broken or knee_too_high or knee_too_low or hip_broken
        holding_now = framing_message is None and not hard_break

        # ---- standing-baseline calibration (before/between holds) ----
        # Sampled only from genuinely upright, still frames — mirrors the
        # side plank's "only calibrate from clean holds" idea, just
        # inverted (calibrate from clean *stands*, not clean holds).
        if (
            not self.calibrated
            and knee_angle > STANDING_KNEE_ANGLE_MIN
            and torso_lean_angle < STANDING_TORSO_LEAN_MAX
            and framing_message is None
        ):
            self._calib_samples.append((hip.y, _dist(hip, ankle)))
            if len(self._calib_samples) >= CALIBRATION_FRAMES:
                self._finish_calibration()

        hip_drop_fraction = None
        if self.calibrated and self._baseline_leg_len:
            hip_drop_fraction = max(
                0.0, (hip.y - self._baseline_hip_y) / self._baseline_leg_len
            )

        # ---- form tiering (only meaningful while holding) ----
        issues: list[str] = []
        messages: list[str] = []
        if holding_now:
            if torso_lean_angle > TORSO_LEAN_IDEAL:
                issues.append("torso_lean")
                messages.append("Keep your back flat against the wall.")

            if knee_angle < KNEE_IDEAL_LOW:
                issues.append("not_quite_parallel")
                messages.append("Rise a little if you're dropping too low.")
            elif knee_angle > KNEE_IDEAL_HIGH:
                issues.append("not_quite_parallel")
                messages.append("Slide a little lower — thighs near parallel.")

            if shin_angle > SHIN_FLAW_ABOVE:
                issues.append("knees_forward")
                messages.append("Keep your knees over your ankles.")

            if mode == "both":
                ls, lh, lk, la = LEG_LANDMARKS["left"]
                rs, rh, rk, ra = LEG_LANDMARKS["right"]
                l_shoulder, r_shoulder = landmarks[ls], landmarks[rs]
                l_knee, r_knee = landmarks[lk], landmarks[rk]
                l_hip, r_hip = landmarks[lh], landmarks[rh]
                l_ankle, r_ankle = landmarks[la], landmarks[ra]

                # The knee-gap comparison below only means anything from a
                # reasonably frontal view. From an angled/turned camera,
                # perspective foreshortens the knee-to-knee gap more than
                # the hip-to-hip gap even with knees perfectly stacked —
                # which reads as a false "caving in" for the whole hold.
                # Use MediaPipe's z (relative depth) on the shoulders as a
                # frontality check, and skip the comparison entirely when
                # the view isn't square-on enough to trust it.
                l_z = l_shoulder.z if l_shoulder.z is not None else 0.0
                r_z = r_shoulder.z if r_shoulder.z is not None else 0.0
                frontal_enough = abs(l_z - r_z) <= FRONTALITY_Z_MAX

                pinched_this_frame = False
                if frontal_enough:
                    knee_gap = abs(l_knee.x - r_knee.x)
                    hip_gap = max(abs(l_hip.x - r_hip.x), 1e-6)
                    ankle_gap = max(abs(l_ankle.x - r_ankle.x), 1e-6)
                    # Require the pinch relative to BOTH the hips and the
                    # ankles — a real valgus collapse narrows the knees
                    # against the whole leg's natural width, not just one
                    # reference point, which guards against a single
                    # off landmark estimate.
                    pinched_this_frame = (knee_gap / hip_gap) < KNEE_VALGUS_RATIO and (
                        knee_gap / ankle_gap
                    ) < KNEE_VALGUS_RATIO

                self._valgus_streak = (
                    self._valgus_streak + 1 if pinched_this_frame else 0
                )

                if self._valgus_streak >= VALGUS_CONFIRM_FRAMES:
                    issues.append("knee_valgus")
                    messages.append(
                        "Push your knees out slightly — they're caving inward."
                    )
            else:
                # Only two legs visible → can't compare knee gap to
                # anything meaningful; don't let a stale streak from
                # earlier carry over into a false flag later.
                self._valgus_streak = 0

            # Optional: hands resting on the thighs, if wrists are visible
            # near the knee/hip region — light-weight form note only.
            wrist_candidates = [
                landmarks[LEFT_WRIST] if mode in ("both", "left") else None,
                landmarks[RIGHT_WRIST] if mode in ("both", "right") else None,
            ]
            for wrist in wrist_candidates:
                if wrist is None:
                    continue
                if (
                    wrist.visibility is None
                    or wrist.visibility < MIN_LANDMARK_VISIBILITY
                ):
                    continue
                if _dist(wrist, knee) < 0.08:
                    issues.append("hands_on_thighs")
                    messages.append(
                        "Try lifting your hands off your thighs to keep the legs doing the work."
                    )
                    break

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
        if feedback is None and knee_too_high:
            feedback = "Slide down until your thighs are near parallel to the floor."
        if feedback is None and knee_too_low:
            feedback = (
                "Rise up a little — you've dropped below a wall sit into a low sit."
            )
        if feedback is None and (torso_broken or hip_broken):
            feedback = (
                "Lean your back against the wall and settle into a seated "
                "position — knees bent, thighs roughly parallel to the floor."
            )
        if feedback is None and messages:
            feedback = messages[0]
        if feedback is None and not self.started and holding_now:
            feedback = "Great — you're in the hold, stay there!"
        if feedback is None and target_reached:
            feedback = f"Target reached — {self.target_seconds}s held, nice work!"
        if feedback is None and holding_now:
            feedback = "Stay in the hold — looking good!"
        if feedback is None:
            feedback = "Get back into your wall sit to resume the timer."

        response.update(
            {
                "pose_detected": True,
                "legs_tracked": self.legs_tracked,
                "torso_lean_angle": round(torso_lean_angle, 1),
                "knee_angle": round(knee_angle, 1),
                "hip_angle": round(hip_angle, 1),
                "shin_angle": round(shin_angle, 1),
                "hip_drop_fraction": (
                    round(hip_drop_fraction, 2)
                    if hip_drop_fraction is not None
                    else None
                ),
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
        self._valgus_streak = 0

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


class WallSitSession:
    """Full wall-sit session: one shared pose model + one analyzer.

    `target_seconds` / `target_sets` / `set_number` are the coach-assigned
    plan for this user, supplied by the caller (the websocket route, from
    query params) — same convention as `PlankHoldSession` / `SidePlankSession`.
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
        self.analyzer = WallSitAnalyzer(target_seconds)
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
