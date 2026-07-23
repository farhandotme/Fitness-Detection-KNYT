"""
Reverse Warrior (Viparita Virabhadrasana) hold timing + posture correction.

Design
------
No reps here — like `SidePlankAnalyzer` / `PlankHoldAnalyzer`, this is a
single continuous timed hold. The timer only advances while the person is
verified, frame by frame, to actually be in a correct Reverse Warrior. The
moment form breaks (or the person leaves frame, or the framing goes bad),
the timer **pauses** — it never silently resets `hold_seconds` to zero, so
total progress is monotonic. `current_streak_seconds` is what resets, for
live feedback on the *current* attempt.

Why this needs MULTIPLE independent hard gates
-----------------------------------------------
A false "count" here is a charting/cheating problem, not just a cosmetic
bug. A single loose angle check is easy to satisfy by accident (e.g. just
standing with one arm up), so this detector requires **every one** of five
independent signals to agree before a frame counts as a real hold. Each
one alone is a common pose; together they are extremely specific to
Reverse Warrior:

  1. `stance` — wide, lunge-like stance (legs spread far apart relative to
     the person's own torso length). Rules out standing/upright poses.
  2. `front_knee` — one knee clearly bent (lunging into the front leg).
  3. `back_knee` — the OTHER leg's knee is straight.
  4. `raised_arm` — the arm on the SAME side as the bent (front) knee is
     extended and reaching overhead, wrist well above the shoulder.
  5. `torso_lean` — the torso is arced sideways/back over the straight
     (back) leg — the signature backbend shape of Reverse Warrior.

Any ONE of these failing pauses the timer (hard gate). A handful of softer
things are graded as posture notes that lower `form_score` but do NOT stop
the clock.

Real-camera stability (why raw single-frame angles aren't enough)
-------------------------------------------------------------------
Two problems showed up against a real webcam feed that don't show up with
synthetic landmarks:

  * **Shoulder width is an unreliable scale reference for this pose.**
    Reverse Warrior twists/arcs the torso, so the two shoulders are
    frequently at different depths from the camera (one rotated closer,
    one further) — a 2D shoulder-to-shoulder distance shrinks under that
    foreshortening even though the person hasn't moved their feet at all.
    That was inflating `stance_ratio` and made it an unstable signal.
    Fixed by using `torso_len` (shoulder-midpoint to hip-midpoint) as the
    scale reference instead — a front-on vertical body segment that stays
    far more stable under the twisting this pose involves.

  * **Frame-to-frame landmark jitter causes false breaks.** MediaPipe's
    per-frame estimate wobbles a few degrees/pixels even when a person is
    rock-still, and this pose asks for several joints near their limits
    (knees near-straight, elbow fully extended) where a small wobble can
    momentarily cross a hard-gate threshold. Two independent fixes:
      (a) every gate quantity is smoothed with a short exponential moving
          average (`_EMA_ALPHA`) before being compared to any threshold,
          so a single noisy frame can't flip the verdict on its own;
      (b) a short **grace period** (`GRACE_PERIOD_SECONDS`) — once a hold
          is already in progress, a gate failing has to stay failed for
          longer than the grace window before it actually counts as a
          break. A one-frame blip gets absorbed; genuinely broken form
          (which stays broken) still pauses the timer. Grace does NOT
          apply to *entering* a hold in the first place — you still have
          to cleanly clear every resume threshold to start the clock, and
          it does not apply to framing/visibility problems (those pause
          immediately, since they mean the signal itself can't be trusted).

Camera framing
--------------
Unlike a plank (side-on), Reverse Warrior is judged from a roughly
front-on camera — the whole body needs to be in frame: both arms, both
legs, head to feet, with the wide stance visible left-to-right.
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

# This exercise needs the WHOLE body tracked (both arms + both legs) —
# there is no "pick the better side" fallback like a side plank has.
ALL_TRACKED_LANDMARKS = (
    LEFT_SHOULDER,
    RIGHT_SHOULDER,
    LEFT_ELBOW,
    RIGHT_ELBOW,
    LEFT_WRIST,
    RIGHT_WRIST,
    LEFT_HIP,
    RIGHT_HIP,
    LEFT_KNEE,
    RIGHT_KNEE,
    LEFT_ANKLE,
    RIGHT_ANKLE,
)

# ---- Noise handling (applied to every gate quantity before thresholding) ----
# Exponential moving average smoothing factor — lower = smoother/slower to
# react, higher = snappier/noisier. 0.35 damps single-frame jitter heavily
# while still catching a genuine, sustained form break within a few frames.
_EMA_ALPHA = 0.35

# Once a hold is already active, a hard-gate failure has to persist beyond
# this many seconds before it actually registers as a break. Absorbs the
# odd noisy frame without punishing a hold that never really left form.
# Does NOT apply when first entering a hold, and does NOT apply to framing/
# visibility problems.
GRACE_PERIOD_SECONDS = 0.35

# ---- Gate 1: stance width, ankle-to-ankle distance / torso length ----
# (torso length — shoulder-midpoint to hip-midpoint — is the scale
# reference here, NOT shoulder width; see module docstring for why.)
STANCE_BROKEN = 0.95
STANCE_RESUME = 1.15

# ---- Gate 2: front (bent) knee angle, degrees. hip-knee-ankle ----
# The two knee angles must also differ clearly, or we can't tell which leg
# is "front" (e.g. both slightly bent while just standing).
FRONT_KNEE_BROKEN = 138.0
FRONT_KNEE_RESUME = 122.0
FRONT_KNEE_TOO_DEEP = 65.0  # softer note only, not a hard break
FRONT_KNEE_IDEAL_LOW = 80.0
FRONT_KNEE_IDEAL_HIGH = 130.0  # widened — 115-130° is still a fine working lunge depth
MIN_KNEE_ANGLE_GAP = 18.0  # front vs back knee angle must differ by at least this

# ---- Gate 3: back (straight) knee angle, degrees ----
BACK_KNEE_BROKEN = 148.0
BACK_KNEE_RESUME = 160.0

# ---- Gate 4: raised arm (front-knee side), overhead + extended ----
RAISED_ELBOW_BROKEN = 128.0
RAISED_ELBOW_RESUME = 145.0
# (shoulder.y - wrist.y) / torso_len — how far above the shoulder the wrist
# sits, normalized by torso length so it's scale-invariant. Image y grows
# downward, so a positive value means the wrist is higher than the shoulder.
RAISED_WRIST_HEIGHT_BROKEN = 0.10
RAISED_WRIST_HEIGHT_RESUME = 0.20

# ---- Gate 5: torso lean toward the back leg, normalized by torso length ----
TORSO_LEAN_BROKEN = 0.09
TORSO_LEAN_RESUME = 0.16

# ---- Soft posture notes (graded, don't pause the timer) ----
LOWERED_WRIST_TOO_HIGH = (
    0.05  # (shoulder.y - wrist.y)/torso_len above this = lowered arm drifting up
)
MISTAKE_PENALTY = {
    "front_knee_too_deep": 12,
    "front_knee_too_shallow": 10,
    "lowered_arm_drifting_up": 14,
    "raised_arm_not_fully_extended": 10,
}

SCORE_HISTORY = 30
SCORE_SAMPLE_INTERVAL = 1.0  # seconds

# ---- Camera framing ----
FRAME_EDGE_MARGIN = 0.02
BODY_SPAN_TOO_CLOSE = (
    0.95  # shoulder-to-ankle vertical span as fraction of frame height
)
BODY_SPAN_TOO_FAR = 0.30


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 3  # need most of the core to trust a full-body pose


def _fully_visible(landmarks) -> bool:
    for i in ALL_TRACKED_LANDMARKS:
        v = landmarks[i].visibility
        if v is None or v < MIN_LANDMARK_VISIBILITY:
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


def _midpoint(a, b):
    class _P:
        __slots__ = ("x", "y")

    p = _P()
    p.x = (a.x + b.x) / 2.0
    p.y = (a.y + b.y) / 2.0
    return p


def _framing_feedback(landmarks) -> Optional[str]:
    """Checked every frame, independent of exercise form. Reverse Warrior
    needs the WHOLE body — both arms and legs, head to feet — visible in a
    roughly front-on frame with the wide stance readable left-to-right."""
    for i in ALL_TRACKED_LANDMARKS:
        p = landmarks[i]
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "Part of you is out of frame — step back so your whole body, "
                "both arms and both legs, fits in the shot."
            )

    l_sh, r_sh = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
    l_an, r_an = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]
    shoulder_mid = _midpoint(l_sh, r_sh)
    ankle_mid = _midpoint(l_an, r_an)
    vertical_span = abs(ankle_mid.y - shoulder_mid.y)

    if vertical_span > BODY_SPAN_TOO_CLOSE:
        return "You're too close to the camera — step back until your whole body fits in frame."
    if vertical_span < BODY_SPAN_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class ReverseWarriorAnalyzer:
    """Stateful Reverse Warrior hold timer + posture checker.

    Mirrors the `SidePlankAnalyzer` contract: no `target_reps`, just a
    `target_seconds` duration, and `session_complete` is
    `hold_seconds >= target_seconds`.
    """

    def __init__(self, target_seconds: Optional[int] = None):
        self.target_seconds = target_seconds

        self.front_side: Optional[str] = None  # side with the bent (lunging) knee

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

        # Exponential moving averages of the five gate quantities, keyed by
        # name. Reset whenever the pose is lost so a stale smoothed value
        # can't linger across a genuine break.
        self._smoothed: dict[str, float] = {}

        # Wall-clock time (seconds) the current hard-gate failure started,
        # while a hold was already active — None while nothing is failing.
        self._break_started_at: Optional[float] = None

        self.form_scores: deque[int] = deque(maxlen=SCORE_HISTORY)
        self._last_score_sample_time: Optional[float] = None

    # ---------------------------------------------------------------
    def _is_complete(self) -> bool:
        return (
            self.target_seconds is not None and self.hold_seconds >= self.target_seconds
        )

    def _smooth(self, key: str, value: float) -> float:
        """Exponential moving average — first observation seeds it exactly
        (no artificial ramp-up delay), every value after blends in."""
        prev = self._smoothed.get(key)
        new = value if prev is None else (_EMA_ALPHA * value + (1 - _EMA_ALPHA) * prev)
        self._smoothed[key] = new
        return new

    def _reset_smoothing(self):
        self._smoothed.clear()
        self._break_started_at = None

    def _pick_front_side(self, landmarks) -> Optional[tuple[str, float, float]]:
        """Returns (front_side, front_knee_angle, back_knee_angle) or None
        if we can't confidently tell which leg is the lunging one this
        frame (used only to decide side; the hard gates below still apply
        their own thresholds independently)."""
        angles = {}
        for side, (_, _, _, hip_i, knee_i, ankle_i) in SIDE_LANDMARKS.items():
            angles[side] = _angle_deg(
                landmarks[hip_i], landmarks[knee_i], landmarks[ankle_i]
            )

        left_a, right_a = angles["left"], angles["right"]
        if abs(left_a - right_a) < MIN_KNEE_ANGLE_GAP:
            # Prefer to keep the previous front_side if the gap is
            # ambiguous but not zero — avoids flicker on borderline frames.
            if self.front_side is not None:
                other = "right" if self.front_side == "left" else "left"
                return self.front_side, angles[self.front_side], angles[other]
            return None

        front = "left" if left_a < right_a else "right"
        back = "right" if front == "left" else "left"
        return front, angles[front], angles[back]

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "front_side": self.front_side,
            "stance_ratio": None,
            "front_knee_angle": None,
            "back_knee_angle": None,
            "raised_elbow_angle": None,
            "raised_wrist_height": None,
            "torso_lean": None,
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
            self._reset_smoothing()
            response["feedback"] = (
                "No person detected — step into frame, facing the camera, "
                "with room for a wide stance."
            )
            response.update(self._progress_fields())
            return response

        response["pose_detected"] = True

        if not _fully_visible(landmarks):
            response["low_visibility"] = True
            self._register_broken_frame()
            self._reset_smoothing()
            response["feedback"] = (
                "Can't see your whole body clearly — make sure both arms and "
                "both legs, head to feet, are visible to the camera."
            )
            response.update(self._progress_fields())
            return response

        framing_message = _framing_feedback(landmarks)
        if framing_message is not None:
            # Framing/visibility problems bypass the grace period entirely —
            # if we can't trust the signal, we don't keep counting on it.
            self._register_broken_frame()
            self._reset_smoothing()
            response["framing_ok"] = False
            response["framing_message"] = framing_message
            response["feedback"] = framing_message
            response.update(self._progress_fields())
            return response

        picked = self._pick_front_side(landmarks)
        if picked is None:
            self.front_side = None
            self._register_broken_frame()
            self._reset_smoothing()
            response["feedback"] = (
                "Step into a wide lunge stance with one knee clearly bent — "
                "I can't tell which leg is your front leg yet."
            )
            response.update(self._progress_fields())
            return response

        front_side, raw_front_knee_angle, raw_back_knee_angle = picked
        self.front_side = front_side
        back_side = "right" if front_side == "left" else "left"

        f_sh_i, f_el_i, f_wr_i, f_hip_i, f_knee_i, f_ank_i = SIDE_LANDMARKS[front_side]
        b_sh_i, b_el_i, b_wr_i, b_hip_i, b_knee_i, b_ank_i = SIDE_LANDMARKS[back_side]

        f_shoulder, f_elbow, f_wrist = (
            landmarks[f_sh_i],
            landmarks[f_el_i],
            landmarks[f_wr_i],
        )
        b_shoulder, b_elbow, b_wrist = (
            landmarks[b_sh_i],
            landmarks[b_el_i],
            landmarks[b_wr_i],
        )
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]
        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]

        shoulder_mid = _midpoint(l_shoulder, r_shoulder)
        hip_mid = _midpoint(l_hip, r_hip)
        torso_len = max(_dist(shoulder_mid, hip_mid), 1e-6)

        # Stance is measured against torso length, NOT shoulder width — a
        # twisted/arced torso foreshortens shoulder width and makes it an
        # unreliable ruler for this particular pose (see module docstring).
        raw_stance_ratio = _dist(l_ankle, r_ankle) / torso_len

        raw_raised_elbow_angle = _angle_deg(f_shoulder, f_elbow, f_wrist)
        raw_raised_wrist_height = (f_shoulder.y - f_wrist.y) / torso_len

        lowered_elbow_angle = _angle_deg(b_shoulder, b_elbow, b_wrist)
        lowered_wrist_height = (b_shoulder.y - b_wrist.y) / torso_len

        back_ankle = landmarks[b_ank_i]
        front_ankle = landmarks[f_ank_i]
        lean_dx = shoulder_mid.x - hip_mid.x
        direction = back_ankle.x - front_ankle.x
        if abs(direction) < 1e-6:
            raw_torso_lean = 0.0
        else:
            raw_torso_lean = (lean_dx * (1.0 if direction > 0 else -1.0)) / torso_len

        # ---- smooth every gate quantity before it touches a threshold ----
        front_knee_angle = self._smooth("front_knee_angle", raw_front_knee_angle)
        back_knee_angle = self._smooth("back_knee_angle", raw_back_knee_angle)
        stance_ratio = self._smooth("stance_ratio", raw_stance_ratio)
        raised_elbow_angle = self._smooth("raised_elbow_angle", raw_raised_elbow_angle)
        raised_wrist_height = self._smooth(
            "raised_wrist_height", raw_raised_wrist_height
        )
        torso_lean = self._smooth("torso_lean", raw_torso_lean)

        # ---- resolve hold-validity this frame (with hysteresis per gate) ----
        if self.hold_active:
            stance_broken = stance_ratio < STANCE_BROKEN
            front_knee_broken = front_knee_angle > FRONT_KNEE_BROKEN
            back_knee_broken = back_knee_angle < BACK_KNEE_BROKEN
            raised_broken = (
                raised_elbow_angle < RAISED_ELBOW_BROKEN
                or raised_wrist_height < RAISED_WRIST_HEIGHT_BROKEN
            )
            torso_broken = torso_lean < TORSO_LEAN_BROKEN
        else:
            stance_broken = stance_ratio < STANCE_RESUME
            front_knee_broken = front_knee_angle > FRONT_KNEE_RESUME
            back_knee_broken = back_knee_angle < BACK_KNEE_RESUME
            raised_broken = (
                raised_elbow_angle < RAISED_ELBOW_RESUME
                or raised_wrist_height < RAISED_WRIST_HEIGHT_RESUME
            )
            torso_broken = torso_lean < TORSO_LEAN_RESUME

        hard_break = (
            stance_broken
            or front_knee_broken
            or back_knee_broken
            or raised_broken
            or torso_broken
        )

        # ---- grace period: only matters if a hold is already running ----
        if not hard_break:
            self._break_started_at = None
            holding_now = True
        elif not self.hold_active:
            # Never enter a hold on a grace basis — must cleanly clear
            # every resume threshold first.
            holding_now = False
        else:
            if self._break_started_at is None:
                self._break_started_at = t
            within_grace = (t - self._break_started_at) <= GRACE_PERIOD_SECONDS
            holding_now = within_grace

        # ---- form tiering (only meaningful while holding) ----
        issues: list[str] = []
        messages: list[str] = []
        if holding_now:
            if front_knee_angle < FRONT_KNEE_TOO_DEEP:
                issues.append("front_knee_too_deep")
                messages.append(
                    "Ease your front knee up slightly — you're sinking deeper than necessary."
                )
            elif front_knee_angle > FRONT_KNEE_IDEAL_HIGH:
                issues.append("front_knee_too_shallow")
                messages.append(
                    "Bend your front knee more — sink deeper into the lunge."
                )

            if raised_elbow_angle < 155.0:
                issues.append("raised_arm_not_fully_extended")
                messages.append("Straighten your top arm fully overhead.")

            if lowered_wrist_height > LOWERED_WRIST_TOO_HIGH:
                issues.append("lowered_arm_drifting_up")
                messages.append(
                    "Let your lower arm rest down along your back leg instead of lifting it."
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

        # ---- feedback priority: which hard gate broke > form flaws > praise ----
        feedback = None
        if hard_break and not holding_now:
            if stance_broken:
                feedback = (
                    "Widen your stance — step your feet further apart into a lunge."
                )
            elif front_knee_broken:
                feedback = "Bend your front knee — sink into a lunge on one side."
            elif back_knee_broken:
                feedback = "Straighten your back leg fully."
            elif raised_broken:
                feedback = "Reach your top arm straight up overhead, in line with your back leg."
            elif torso_broken:
                feedback = (
                    "Arc your torso back over your back leg — this is a backbend, not a "
                    "static lunge."
                )
        if feedback is None and messages:
            feedback = messages[0]
        if feedback is None and target_reached:
            feedback = f"Target reached — {self.target_seconds}s held, nice work!"
        if feedback is None and holding_now:
            feedback = "Great Reverse Warrior — keep holding!"
        if feedback is None:
            feedback = "Get back into Reverse Warrior to resume the timer."

        response.update(
            {
                "front_side": self.front_side,
                "stance_ratio": round(stance_ratio, 2),
                "front_knee_angle": round(front_knee_angle, 1),
                "back_knee_angle": round(back_knee_angle, 1),
                "raised_elbow_angle": round(raised_elbow_angle, 1),
                "raised_wrist_height": round(raised_wrist_height, 2),
                "lowered_elbow_angle": round(lowered_elbow_angle, 1),
                "lowered_wrist_height": round(lowered_wrist_height, 2),
                "torso_lean": round(torso_lean, 2),
                "hold_state": "holding" if holding_now else "broken",
                "is_holding": holding_now,
                "target_reached": target_reached,
                "hold_quality": hold_quality,
                "posture_ok": len(issues) == 0,
                "posture_issues": issues,
                "posture_messages": messages,
                "framing_ok": True,
                "framing_message": None,
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


class ReverseWarriorSession:
    """Full Reverse Warrior session: one shared pose model + one analyzer.

    Same convention as `SidePlankSession` — `target_seconds` /
    `target_sets` / `set_number` are the coach-assigned plan, supplied by
    the caller. The frontend never decides completion on its own;
    `session_complete` / `exercise_complete` are both computed here.
    """

    def __init__(
        self,
        target_seconds: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = ReverseWarriorAnalyzer(target_seconds)
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
