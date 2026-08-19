"""
Skipping (jump rope) rep counting + posture correction.

Corrected from an earlier version of this file
--------------------------------------------------
The first version tracked a continuously-adapting "ground baseline" and
counted a jump when displacement from it crossed a threshold. That has
a structural flaw for this exact exercise: the baseline was only allowed
to re-settle while the tracker was in the "ground" state, on the
assumption there'd be a few tenths of a second of ground contact between
jumps to do that settling. Real fast skipping barely touches the ground
between hops — often just 1-3 frames of "grounded" time — so the
baseline never fully re-anchored, kept drifting upward jump after jump,
and quietly raised the bar for what counted as "airborne" until nothing
crossed it anymore. On top of that, requiring hip AND ankle to *both*
independently confirm airborne was a second, compounding source of
over-strictness (the same mistake that zeroed out the Skier Jumping
Jacks analyzer before it was fixed) — if either signal was a little
noisier than the other, the AND-requirement could block every count.

This version uses peak/trough reversal detection instead, which has no
baseline to keep up with at all.

How it works
--------------
Track hip height (lightly smoothed, normalized by torso length). Instead
of comparing against a settled "ground level", follow the *direction* of
travel and the most extreme point reached in that direction:

  * While rising (person moving up), keep updating `extreme` to the
    highest point reached so far.
  * The instant the signal reverses — drops back down by more than
    `REVERSAL_MARGIN` from that extreme — a **peak** (top of the jump)
    is confirmed at that extreme value, and tracking switches to
    following the descent instead.
  * Symmetrically, while falling, keep updating `extreme` to the lowest
    point (most "landed") reached so far; the instant it reverses back
    upward by more than `REVERSAL_MARGIN`, a **trough** (landing) is
    confirmed, and a rep counts.

This needs no calibrated resting height and never drifts, because it's
purely relative — every jump is measured against its *own* peak and
trough, not against a shared baseline that has to keep pace with
however fast the person happens to be moving. It's the standard
technique for counting a fast, small, repeating oscillation (the same
family of algorithm used for pulse/vibration counting), which is a much
better fit here than a threshold-vs-baseline comparison.

Ankle height is still tracked and reported, and used as a light quality
signal (a real jump usually shows the ankle rising in step with the
hip), but — learning from the same over-strictness mistake — it is never
required to independently confirm before a rep counts.

Refractory period + minimum prominence against noise
-----------------------------------------------------------
Two safeguards keep this from over-counting on pure jitter: a peak/trough
only confirms if the reversal from the tracked extreme exceeds
`REVERSAL_MARGIN` (rejects small back-and-forth noise around a resting
position), and `MIN_REP_INTERVAL_SECONDS` refuses to count a new rep
faster than a physically-plausible fastest skip (set comfortably above
any realistic max jump-rope cadence, so it never actually slows a fast
skipper down — it only kills noise-driven chatter).
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_HIP,
    LEFT_SHOULDER,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_HIP,
    RIGHT_SHOULDER,
)

# -------------------------------------------------------------------------
# Tunable constants
# -------------------------------------------------------------------------

MIN_LANDMARK_VISIBILITY = 0.4

# ---- smoothing (light — enough to knock down single-frame jitter without lagging fast motion) ----
SMOOTH_ALPHA = 0.6

# ---- reversal detection, normalized by torso length ----
# How far the signal has to bounce back from its tracked extreme before a
# peak/trough is confirmed. Small enough to catch genuinely small jumps,
# large enough to reject ordinary landmark jitter.
REVERSAL_MARGIN = 0.014

# The baseline normalized height for a "100%" perfect jump.
IDEAL_JUMP_HEIGHT = 0.05

# Max lateral movement allowed per jump to prevent walking from being counted
MAX_HORIZONTAL_DRIFT = 0.10

# Minimum on-screen torso size to reject background clutter / ghost skeletons
MIN_TORSO_LENGTH = 0.15

# ---- refractory period against reversal-margin chatter ----
MIN_REP_INTERVAL_SECONDS = 0.15

MISTAKE_PENALTY = {
    "shallow_hop": 10,
}

SCORE_HISTORY = 30

# ---- framing (front-facing or side-on, standing) ----
FRAME_EDGE_MARGIN = 0.02
BBOX_TOO_CLOSE = 0.97
BBOX_TOO_FAR = 0.10


def _looks_like_a_person(landmarks) -> bool:
    core = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)
    visible = sum(
        1
        for i in core
        # Increased confidence threshold to 0.75 to filter out background objects
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.75
    )
    return visible >= 3


def _visible(points) -> bool:
    for p in points:
        if p is None:
            return False
        v = getattr(p, "visibility", None)
        if v is not None and v < MIN_LANDMARK_VISIBILITY:
            return False
    return True


def _framing_feedback(points) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return "You're partly out of frame — step back so your whole body, head to feet, fits in the shot."

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "You're too close to the camera — step back so your whole body fits in frame."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class _PeakTroughTracker:
    """Follows a lightly-smoothed, normalized vertical signal and
    confirms a peak (top of jump) then a trough (landing) via reversal
    detection — see module docstring. No baseline, nothing to drift."""

    def __init__(self):
        self.smoothed_y: Optional[float] = None
        self.direction: str = (
            "falling"  # "rising" | "falling" — which way we're tracking
        )
        self.extreme_y: Optional[float] = None
        self.peak_confirmed_time: Optional[float] = None
        self.trough_confirmed_time: Optional[float] = None
        self.last_jump_height = 0.0  # peak-to-trough excursion of the most recent cycle
        self.last_jump_horizontal_drift = 0.0  # Tracks side-to-side drift
        self._pending_peak_y: Optional[float] = None
        self._pending_peak_x: Optional[float] = None  # Stores the X pos at the peak

    def update(
        self, raw_y: float, raw_x: float, torso_length: float, t: float
    ) -> float:
        """Feed one frame's raw vertical and horizontal position (hip midpoint).
        Returns the current normalized displacement from the tracked
        extreme, for telemetry purposes."""
        if self.smoothed_y is None:
            self.smoothed_y = raw_y
        else:
            self.smoothed_y = (
                SMOOTH_ALPHA * raw_y + (1 - SMOOTH_ALPHA) * self.smoothed_y
            )

        if self.extreme_y is None:
            self.extreme_y = self.smoothed_y

        torso_length = max(torso_length, 1e-6)

        if self.direction == "falling":
            # Tracking toward a trough (landing) — extreme_y is the
            # lowest point (largest y, closest to the ground) seen.
            if self.smoothed_y > self.extreme_y:
                self.extreme_y = self.smoothed_y
            reversal = (
                self.smoothed_y - self.extreme_y
            ) / torso_length  # negative once rising
            if -reversal > REVERSAL_MARGIN:
                # Bounced back up enough to have clearly left this low
                # point. Only counts as a genuine landing if it follows a
                # real recorded peak.
                if self._pending_peak_y is not None:
                    self.trough_confirmed_time = t
                    self.last_jump_height = (
                        self.extreme_y - self._pending_peak_y
                    ) / torso_length

                    if self._pending_peak_x is not None:
                        # Calculate horizontal drift over the course of the jump cycle
                        self.last_jump_horizontal_drift = (
                            abs(raw_x - self._pending_peak_x) / torso_length
                        )

                    self._pending_peak_y = None
                    self._pending_peak_x = None  # Reset after landing
                self.direction = "rising"
                self.extreme_y = self.smoothed_y
        else:  # "rising"
            # Tracking toward a peak (top of the jump) — extreme_y is the
            # highest point (smallest y) seen.
            if self.smoothed_y < self.extreme_y:
                self.extreme_y = self.smoothed_y
            reversal = (
                self.smoothed_y - self.extreme_y
            ) / torso_length  # positive once falling
            if reversal > REVERSAL_MARGIN:
                # Bounced back down enough to confirm the peak and start
                # tracking the descent toward landing.
                self.peak_confirmed_time = t
                self._pending_peak_y = self.extreme_y
                self._pending_peak_x = raw_x  # Record X position at the top of the jump
                self.direction = "falling"
                self.extreme_y = self.smoothed_y

        return (self.extreme_y - self.smoothed_y) / torso_length


class SkippingAnalyzer:
    """Stateful Skipping (jump rope) rep counter — peak/trough reversal
    detection on hip height, ankle height tracked as a light quality
    signal only."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.hip = _PeakTroughTracker()
        self.ankle = _PeakTroughTracker()

        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        self._last_rep_time: Optional[float] = None
        self._last_seen_trough_time: Optional[float] = None

        self.session_start_time: Optional[float] = None

    # ---------------------------------------------------------------
    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "framing_ok": True,
            "framing_message": None,
            "hip_signal": None,
            "ankle_signal": None,
            "direction": self.hip.direction,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_form_quality": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = (
                "No person detected — step into frame, facing the camera."
            )
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        required_ok = _visible((l_shoulder, r_shoulder, l_hip, r_hip, l_ankle, r_ankle))
        if not required_ok:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your full body clearly — make sure your feet and "
                "hips are visible, facing the camera."
            )
            return response

        response["pose_detected"] = True

        framing_message = _framing_feedback(
            (l_shoulder, r_shoulder, l_hip, r_hip, l_ankle, r_ankle)
        )
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        if framing_message is not None:
            response["feedback"] = framing_message
            return response

        mid_shoulder_y = (l_shoulder.y + r_shoulder.y) / 2.0

        mid_hip_y = (l_hip.y + r_hip.y) / 2.0
        mid_hip_x = (l_hip.x + r_hip.x) / 2.0

        mid_ankle_y = (l_ankle.y + r_ankle.y) / 2.0
        mid_ankle_x = (l_ankle.x + r_ankle.x) / 2.0

        raw_torso_length = abs(mid_hip_y - mid_shoulder_y)

        # Reject background objects/statues mapped as tiny ghost skeletons
        if raw_torso_length < MIN_TORSO_LENGTH:
            response["pose_detected"] = False
            response["feedback"] = "Step closer to the camera."
            return response

        torso_length = max(raw_torso_length, 1e-6)

        prev_trough_time = self.hip.trough_confirmed_time

        hip_signal = self.hip.update(mid_hip_y, mid_hip_x, torso_length, t)
        ankle_signal = self.ankle.update(mid_ankle_y, mid_ankle_x, torso_length, t)

        response["hip_signal"] = round(hip_signal, 3)
        response["ankle_signal"] = round(ankle_signal, 3)
        response["direction"] = self.hip.direction

        rep_completed = False
        quality: Optional[str] = None
        feedback: Optional[str] = None

        just_landed = self.hip.trough_confirmed_time != prev_trough_time
        if just_landed:
            refractory_ok = (
                self._last_rep_time is None
                or (t - self._last_rep_time) >= MIN_REP_INTERVAL_SECONDS
            )

            # Check if the user stayed in place horizontally
            drift_ok = self.hip.last_jump_horizontal_drift < MAX_HORIZONTAL_DRIFT

            if refractory_ok and drift_ok:

                # Calculate jump quality as a percentage of IDEAL_JUMP_HEIGHT
                jump_score_percent = (
                    self.hip.last_jump_height / IDEAL_JUMP_HEIGHT
                ) * 100

                if jump_score_percent >= 80.0:
                    self.rep_count += 1
                    self._last_rep_time = t
                    rep_completed = True

                    if jump_score_percent >= 90.0:
                        self.good_reps += 1
                        quality = "good"
                        feedback = f"Jump {self.rep_count}!"
                    else:
                        self.flawed_reps += 1
                        quality = "needs_improvement"
                        feedback = (
                            f"Jump {self.rep_count} counted — hop a little higher."
                        )
                else:
                    feedback = "Jump too shallow (under 80%) — jump higher to count!"

            elif refractory_ok and not drift_ok:
                feedback = "Stay in place! Side-stepping doesn't count."

        if feedback is None:
            feedback = (
                "In the air — light landing."
                if self.hip.direction == "falling"
                else "Keep hopping — small, quick jumps."
            )

        response.update(
            {
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_form_quality": quality,
                "feedback": feedback,
            }
        )
        return response


class SkippingSession:
    """Full session: one shared pose model + one analyzer.

    `target_reps` / `target_sets` / `set_number` are the coach-assigned
    plan for this user, supplied by the caller (the websocket route, from
    query params) — same convention as the other rep-based sessions in
    this codebase. The frontend does not decide on its own whether a
    set/exercise is done; `session_complete` and `exercise_complete` are
    both computed here.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = SkippingAnalyzer(target_reps)
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
