"""
Bird dog rep counter + anti-cheat form gate.

Design
------
A correct bird dog rep is: start in a stable quadruped ("tabletop")
position — hands under shoulders, knees under hips, back flat — then
reach ONE arm forward and the OPPOSITE leg backward at the same time,
both fully straight and in line with the torso, hold for a beat, then
return to tabletop. That's one rep. Then the same thing on the other
side.

The whole point of this detector is that it must be **hard to cheat and
easy to do correctly for a beginner**. The most common ways people cheat
this exercise (intentionally or not) are:

  1. Raising the SAME-SIDE arm and leg instead of opposite ones (much
     less core-anti-rotation demand — this is a different, easier
     exercise, not a bird dog).
  2. Barely lifting the limbs a few inches ("phantom reps") instead of
     reaching them out straight and in line with the torso.
  3. Flicking/kipping the limbs up and immediately dropping them, using
     momentum instead of a controlled, held extension.
  4. Letting the back sag or arch, or the hips twist open, to make the
     reach easier — classic beginner form breakdown.
  5. Starting from a collapsed/incorrect base position (not on all
     fours) so "reaching" isn't really happening from a stable core.

This detector gates counting on (1)-(3) and (5) as **hard requirements**
— get any of those wrong and the rep simply does not count, with
feedback telling the user exactly why. (4) is graded as a **form
flaw** the same way `pushup.py` grades hip sag and `side_plank.py`
grades head position — it still counts (so a beginner isn't punished
with zero progress for imperfect form) but it's surfaced clearly as
"counted, but fix this," and repeated flaws should visibly show up in
`flawed_reps` vs `good_reps`.

Why per-session calibration (not fixed angle thresholds)
-----------------------------------------------------------
An earlier version of this detector used fixed absolute angles (e.g.
"reaching = shoulder-hip-wrist angle > 150 degrees") to decide when a
limb was tucked vs. fully reached. That works only for a near-perfect
side-on camera at roughly hip height. Real users shoot this from a
laptop propped on the floor, a phone leaned against something, a webcam
looking down at an angle, etc. — the SAME physical "tabletop" pose can
project to very different 2D angles depending on camera height/tilt, so
a fixed threshold either never triggers (too strict for this user's
angle) or triggers immediately (too loose). That mismatch is what made
the previous version get permanently stuck on "waiting for tabletop".

Instead, the first couple of seconds of every session are spent
**calibrating against this specific person, in this specific camera
position**: whatever resting shoulder/hip/wrist and shoulder/hip/ankle
angles they're holding are captured as that person's personal "tucked"
baseline, and reaching is then judged as a large-enough angle *increase*
relative to that baseline — not against a hardcoded number. This is the
same calibrate-against-yourself idea `side_plank.py` uses for its head
angle. If calibration can't find a plausible resting pose within a few
seconds, generous hard-coded fallback thresholds take over so the
exercise still works rather than blocking the user forever.

Camera framing
---------------
Judged from a side-on (profile) view, same convention as `pushup.py`
and `side_plank.py` — a bird dog reach happens in the sagittal plane
(forward/back), so a side view is the only angle that can actually see
full arm/leg extension and back-line straightness at the same time. It
does not need to be a *perfect* profile shot (see calibration above),
just roughly side-on rather than head-on.

Rep state machine
------------------
Two stages, `tabletop` (both arm and leg tucked/resting) and `reaching`
(one contralateral arm+leg pair extended). A rep completes on the
reaching -> tabletop transition, but only counts if every hard gate
below held for the whole reach:

  * `ready` — a stable tabletop base was held before the reach started
    (mirrors `pushup.py`'s floor-position gate, `STABLE_BASE_FRAMES` /
    `GRACE_FRAMES`). Reaching before a stable base is established never
    counts.
  * Contralateral pairing — the extending arm side and extending leg
    side must be opposite. If they're ever the same side mid-reach, the
    attempt is invalidated on the spot (not counted), with an explicit
    "wrong pairing" message — this is the main anti-cheat gate.
  * Full extension — both the arm (shoulder-hip-wrist angle) and leg
    (shoulder-hip-ankle angle) must reach well past this person's
    calibrated tucked baseline, AND the elbow/knee must be genuinely
    straight (not just raised while bent). Falling short of either is a
    partial reach and does not count.
  * Held long enough — `MIN_HOLD_SECONDS` at full extension, so a fast
    kip/flick can't register as a rep. There's also a `MAX_REP_DURATION`
    ceiling so a stalled/abandoned attempt doesn't sit open forever.

Back-line straightness (sag/arch) and hip-twist are graded as soft form
flaws exactly like the hard-gate/soft-flag split in `side_plank.py`:
they affect `rep_form_quality` and are called out in `feedback`, but
don't block the count on their own.
"""

import math
import statistics
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

# ---- straightness gates (shoulder-elbow-wrist / hip-knee-ankle) ----
# A "reach" with a bent elbow/knee is not a real extension — it's a
# shortcut. These stay as fixed angles (not calibrated) because a truly
# straight limb reads close to 180 degrees from any reasonable camera
# angle — this one IS camera-angle-invariant, unlike the reach angles.
ELBOW_STRAIGHT_MIN = 145.0
KNEE_STRAIGHT_MIN = 145.0

# ---- timing gates ----
MIN_HOLD_SECONDS = 0.30  # must stay fully extended at least this long
MIN_REP_DURATION = 0.45  # tabletop->reach->tabletop, total, seconds
MAX_REP_DURATION = 10.0  # longer than this = abandoned attempt, discard

# ---- back-line straightness (soft flaw, not a hard gate) ----
# Measured as angle(shoulder, hip, stance_knee) where stance_knee is the
# grounded (non-reaching) leg's knee — should read close to a straight
# line same as the plank/side-plank alignment checks.
ALIGNMENT_FLAW_BELOW = 140.0

# ---- hip-twist (soft flaw) — calibrated per-person from a clean tabletop ----
HIP_TWIST_RATIO_DELTA = 0.4
TWIST_CALIBRATION_FRAMES = 15

# Per-issue penalty applied to a completed rep's form_score.
MISTAKE_PENALTY = {
    "back_sag": 20,
    "back_arch": 15,
    "hip_twist": 15,
}

# -------------------------------------------------------------------------
# Personal baseline calibration (replaces fixed absolute reach-angle
# thresholds — see module docstring).
# -------------------------------------------------------------------------
BASE_CALIBRATION_FRAMES = 20  # ~0.6-1s of frames at typical webcam FPS
# Generous fallback thresholds used ONLY (a) to decide which frames are
# plausibly "tucked" while still collecting calibration samples, and
# (b) if calibration never manages to lock in (e.g. the person never
# holds still). Wide on purpose so they don't themselves become the
# bottleneck.
FALLBACK_TUCKED_BELOW = 115.0
FALLBACK_EXTEND_ABOVE = 150.0

# Once calibrated: reaching = at least this many degrees ABOVE personal
# baseline. Returning to tabletop = back within this many degrees of it.
REACH_EXTEND_DELTA = 40.0
# How far above personal baseline still counts as "resting/tucked". A real
# person's tabletop pose naturally wobbles (breathing, minor shifts,
# camera-angle foreshortening as they move slightly) by well more than a
# few degrees frame to frame — too tight a tolerance here was causing
# `ready` to flicker off on a genuinely correct resting pose. This is
# intentionally generous; the things that actually gate a counted rep
# (contralateral pairing, straight-limb extension, hold time) are strict
# elsewhere, so being forgiving about "is this roughly tabletop" doesn't
# open up a way to cheat.
TUCK_RESUME_DELTA = 35.0

# A single noisy frame reading the "wrong" side as reaching (tracking
# jitter, a hand/foot briefly occluded, MediaPipe swapping left/right for
# one frame) should not nuke an otherwise-correct rep. Require this many
# CONSECUTIVE frames of a genuine side switch before treating a rep as
# invalidated.
SWITCH_DEBOUNCE_FRAMES = 5

# Calibration must NEVER be able to block a session forever. If a plausibly
# tucked pose (see BASE_CALIBRATION_FRAMES above) hasn't been seen within
# this many seconds of the first valid frame, lock in a best-effort
# baseline from whatever the lowest observed angles were instead of
# waiting indefinitely — see `_finalize_calibration()`.
CALIBRATION_TIMEOUT_SECONDS = 4.0

# A calibrated threshold can never be pushed past this — 180 degrees is a
# perfectly straight line, and asking for something even a genuinely
# fully-extended limb can't reach (e.g. if a noisy/best-effort baseline
# ends up close to 180 itself) would make reps permanently impossible.
MAX_REACH_THRESHOLD_DEG = 174.0

# Standing-rejection only — NOT a "must be perfectly horizontal" gate.
# Real tabletop shots from an imperfect camera angle can read well above
# 0 degrees; this just filters out "clearly standing up" frames so
# calibration doesn't lock onto a bad pose.
STANDING_INCLINE_REJECT_DEG = 78.0

STABLE_BASE_FRAMES = 3
GRACE_FRAMES = 10

# Camera framing
FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.97
BBOX_TOO_FAR = 0.10


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.5
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


class _Point:
    __slots__ = ("x", "y")

    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y


def _midpoint(a, b) -> _Point:
    return _Point((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)


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


class BirdDogAnalyzer:
    """Stateful bird-dog rep counter with a hard anti-cheat gate."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.stage = "tabletop"  # "tabletop" | "reaching"
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.rejected_reps = 0  # attempts that failed the anti-cheat gate

        self.last_timestamp_s: Optional[float] = None
        self.session_start_time: Optional[float] = None

        # Base-position gating (mirrors pushup.py's floor gate)
        self._base_streak = 0
        self._bad_streak = 0
        self.ready = False

        # ---- personal baseline calibration ----
        self._calib_samples: deque = deque(maxlen=BASE_CALIBRATION_FRAMES)
        self.base_calibrated = False
        self.baseline_arm_angle: Optional[float] = None
        self.baseline_leg_angle: Optional[float] = None
        # Timeout fallback bookkeeping — see CALIBRATION_TIMEOUT_SECONDS.
        self._calib_start_time: Optional[float] = None
        self._min_arm_seen: Optional[float] = None
        self._min_leg_seen: Optional[float] = None

        # In-progress reach attempt state
        self._reach_start_time: Optional[float] = None
        self._reach_hold_time = 0.0
        self._reach_arm_side: Optional[str] = None
        self._reach_leg_side: Optional[str] = None
        self._reach_invalidated = False
        self._reach_invalid_reason: Optional[str] = None
        self._reach_issues: set[str] = set()
        self._reach_ever_fully_extended = False
        # Debounce counters — see SWITCH_DEBOUNCE_FRAMES.
        self._arm_switch_streak = 0
        self._leg_switch_streak = 0

        # Hip-twist calibration (per person, from clean tabletop frames)
        self._twist_calib_samples: list[float] = []
        self.twist_calibrated = False
        self._baseline_twist_ratio = 1.0

    # ---------------------------------------------------------------
    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _reset_attempt(self):
        self._reach_start_time = None
        self._reach_hold_time = 0.0
        self._reach_arm_side = None
        self._reach_leg_side = None
        self._reach_invalidated = False
        self._reach_invalid_reason = None
        self._reach_issues = set()
        self._reach_ever_fully_extended = False
        self._arm_switch_streak = 0
        self._leg_switch_streak = 0

    def _arm_extend_above(self) -> float:
        if self.base_calibrated and self.baseline_arm_angle is not None:
            return min(
                self.baseline_arm_angle + REACH_EXTEND_DELTA, MAX_REACH_THRESHOLD_DEG
            )
        return FALLBACK_EXTEND_ABOVE

    def _arm_tuck_resume_below(self) -> float:
        if self.base_calibrated and self.baseline_arm_angle is not None:
            # Keep at least a 10-degree gap below the extend threshold so
            # the two never collide even with a clamped/best-effort baseline.
            return min(
                self.baseline_arm_angle + TUCK_RESUME_DELTA,
                self._arm_extend_above() - 10.0,
            )
        return FALLBACK_TUCKED_BELOW

    def _leg_extend_above(self) -> float:
        if self.base_calibrated and self.baseline_leg_angle is not None:
            return min(
                self.baseline_leg_angle + REACH_EXTEND_DELTA, MAX_REACH_THRESHOLD_DEG
            )
        return FALLBACK_EXTEND_ABOVE

    def _leg_tuck_resume_below(self) -> float:
        if self.base_calibrated and self.baseline_leg_angle is not None:
            return min(
                self.baseline_leg_angle + TUCK_RESUME_DELTA,
                self._leg_extend_above() - 10.0,
            )
        return FALLBACK_TUCKED_BELOW

    def _finalize_calibration(self, t: float) -> None:
        """Lock in personal baseline angles. Prefers the MEDIAN of frames
        that genuinely looked tucked (median, not mean, so one weird
        outlier frame during calibration can't skew the baseline); if
        those never showed up within CALIBRATION_TIMEOUT_SECONDS (e.g.
        the subject in frame is never really at rest), falls back to the
        lowest angles observed so far so the session can never get stuck
        "calibrating" forever.
        """
        if len(self._calib_samples) >= BASE_CALIBRATION_FRAMES:
            self.baseline_arm_angle = statistics.median(
                s[0] for s in self._calib_samples
            )
            self.baseline_leg_angle = statistics.median(
                s[1] for s in self._calib_samples
            )
            self.base_calibrated = True
            return

        if (
            self._calib_start_time is None
            or t - self._calib_start_time < CALIBRATION_TIMEOUT_SECONDS
        ):
            return  # still within the calibration window, keep waiting

        if self._calib_samples:
            # Partial but real samples beat the running-min fallback.
            self.baseline_arm_angle = statistics.median(
                s[0] for s in self._calib_samples
            )
            self.baseline_leg_angle = statistics.median(
                s[1] for s in self._calib_samples
            )
            self.base_calibrated = True
        elif self._min_arm_seen is not None and self._min_leg_seen is not None:
            self.baseline_arm_angle = self._min_arm_seen
            self.baseline_leg_angle = self._min_leg_seen
            self.base_calibrated = True
        # else: never saw a usable frame at all yet — nothing to lock onto.

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "ready": self.ready,
            "calibrating": not self.base_calibrated,
            "base_calibrated": self.base_calibrated,
            "baseline_arm_angle": (
                round(self.baseline_arm_angle, 1)
                if self.baseline_arm_angle is not None
                else None
            ),
            "baseline_leg_angle": (
                round(self.baseline_leg_angle, 1)
                if self.baseline_leg_angle is not None
                else None
            ),
            "stage": self.stage,
            "reach_arm_side": None,
            "reach_leg_side": None,
            "left_arm_reach_angle": None,
            "right_arm_reach_angle": None,
            "left_leg_reach_angle": None,
            "right_leg_reach_angle": None,
            "elbow_angle": None,
            "knee_angle": None,
            "alignment_angle": None,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "rejected_reps": self.rejected_reps,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_form_quality": None,
            "posture_issues": [],
            "framing_ok": True,
            "framing_message": None,
            "calibrated": self.base_calibrated,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        dt = 0.0
        if self.last_timestamp_s is not None:
            dt = max(0.0, min(t - self.last_timestamp_s, 0.5))
        self.last_timestamp_s = t

        if landmarks is None or not _looks_like_a_person(landmarks):
            self._register_bad_frame()
            response["ready"] = self.ready
            response["feedback"] = (
                "No person detected — get into frame on all fours, side-on to the camera."
            )
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        left_arm_ok = _visible((l_shoulder, l_elbow, l_wrist))
        right_arm_ok = _visible((r_shoulder, r_elbow, r_wrist))
        left_leg_ok = _visible((l_hip, l_knee, l_ankle))
        right_leg_ok = _visible((r_hip, r_knee, r_ankle))
        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))

        if (
            not torso_visible
            or not (left_arm_ok or right_arm_ok)
            or not (left_leg_ok or right_leg_ok)
        ):
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._register_bad_frame()
            response["ready"] = self.ready
            response["feedback"] = (
                "Can't see your body clearly — make sure your shoulders, "
                "hips, arms and legs are all in frame from the side."
            )
            return response

        response["pose_detected"] = True

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        shoulder_width = _dist(l_shoulder, r_shoulder)
        hip_width = _dist(l_hip, r_hip)

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

        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        torso_incline = _torso_incline_deg(mid_shoulder, mid_hip)
        not_standing = (
            torso_incline is None or torso_incline <= STANDING_INCLINE_REJECT_DEG
        )

        # ---- per-side reach angles (always computed, regardless of stage —
        # these are what the frontend shows live so the user can see the
        # numbers move and trust the thing is actually working) ----
        def arm_reach(side_ok, hip_pt, shoulder_pt, wrist_pt):
            return _angle_deg(hip_pt, shoulder_pt, wrist_pt) if side_ok else None

        def leg_reach(side_ok, shoulder_pt, hip_pt, ankle_pt):
            return _angle_deg(shoulder_pt, hip_pt, ankle_pt) if side_ok else None

        left_arm_reach = arm_reach(left_arm_ok, l_hip, l_shoulder, l_wrist)
        right_arm_reach = arm_reach(right_arm_ok, r_hip, r_shoulder, r_wrist)
        left_leg_reach = leg_reach(left_leg_ok, l_shoulder, l_hip, l_ankle)
        right_leg_reach = leg_reach(right_leg_ok, r_shoulder, r_hip, r_ankle)

        response["left_arm_reach_angle"] = (
            round(left_arm_reach, 1) if left_arm_reach is not None else None
        )
        response["right_arm_reach_angle"] = (
            round(right_arm_reach, 1) if right_arm_reach is not None else None
        )
        response["left_leg_reach_angle"] = (
            round(left_leg_reach, 1) if left_leg_reach is not None else None
        )
        response["right_leg_reach_angle"] = (
            round(right_leg_reach, 1) if right_leg_reach is not None else None
        )

        # ---- calibration: capture this person's resting angles ----
        # Preferred path: average frames that plausibly look tucked (not
        # standing, both limbs below the wide fallback threshold). If that
        # never happens within CALIBRATION_TIMEOUT_SECONDS — e.g. the
        # subject in frame is never actually at rest — `_finalize_calibration`
        # falls back to the lowest angles observed so far instead of
        # waiting forever.
        if not self.base_calibrated:
            if self._calib_start_time is None:
                self._calib_start_time = t

            arm_vals = [a for a in (left_arm_reach, right_arm_reach) if a is not None]
            leg_vals = [a for a in (left_leg_reach, right_leg_reach) if a is not None]

            if arm_vals:
                avg_arm = sum(arm_vals) / len(arm_vals)
                self._min_arm_seen = (
                    avg_arm
                    if self._min_arm_seen is None
                    else min(self._min_arm_seen, avg_arm)
                )
            if leg_vals:
                avg_leg = sum(leg_vals) / len(leg_vals)
                self._min_leg_seen = (
                    avg_leg
                    if self._min_leg_seen is None
                    else min(self._min_leg_seen, avg_leg)
                )

            plausibly_tucked = (
                not_standing
                and all(
                    a is None or a < FALLBACK_TUCKED_BELOW
                    for a in (left_arm_reach, right_arm_reach)
                )
                and all(
                    a is None or a < FALLBACK_TUCKED_BELOW
                    for a in (left_leg_reach, right_leg_reach)
                )
            )
            if plausibly_tucked and arm_vals and leg_vals:
                self._calib_samples.append(
                    (sum(arm_vals) / len(arm_vals), sum(leg_vals) / len(leg_vals))
                )

            self._finalize_calibration(t)

        arm_tuck_resume = self._arm_tuck_resume_below()
        leg_tuck_resume = self._leg_tuck_resume_below()
        arm_extend_above = self._arm_extend_above()
        leg_extend_above = self._leg_extend_above()

        # ---- base (tabletop) gate ----
        both_arms_tucked = all(
            a is None or a < arm_tuck_resume for a in (left_arm_reach, right_arm_reach)
        )
        both_legs_tucked = all(
            a is None or a < leg_tuck_resume for a in (left_leg_reach, right_leg_reach)
        )

        is_base_now = not_standing and both_arms_tucked and both_legs_tucked

        if is_base_now:
            self._base_streak += 1
            self._bad_streak = 0
        else:
            self._base_streak = 0
            self._bad_streak += 1

        if self._base_streak >= STABLE_BASE_FRAMES:
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES and self.stage == "tabletop":
            # Only drop readiness while resting — never mid-reach, or every
            # legitimate reach (which necessarily moves away from the
            # tabletop shape) would immediately un-ready itself.
            self.ready = False
        response["ready"] = self.ready

        # Calibrate hip-twist baseline only from clean, stable tabletop frames.
        if is_base_now and shoulder_width > 1e-6:
            ratio = hip_width / shoulder_width
            if not self.twist_calibrated:
                self._twist_calib_samples.append(ratio)
                if len(self._twist_calib_samples) >= TWIST_CALIBRATION_FRAMES:
                    self._baseline_twist_ratio = sum(self._twist_calib_samples) / len(
                        self._twist_calib_samples
                    )
                    self.twist_calibrated = True

        feedback = framing_message
        if feedback is None and not self.base_calibrated:
            feedback = (
                "Calibrating — hold a steady tabletop position (hands under "
                "shoulders, knees under hips) for a moment…"
            )
        elif feedback is None and not self.ready and self.stage == "tabletop":
            feedback = (
                "Get onto all fours, side-on to the camera — hands under "
                "shoulders, knees under hips, back flat — to start counting."
            )

        # ---- which side(s) are currently reaching ----
        def extended_side(angles: dict, threshold: float) -> Optional[str]:
            candidates = {s: a for s, a in angles.items() if a is not None}
            if not candidates:
                return None
            best_side = max(candidates, key=lambda s: candidates[s])
            if candidates[best_side] >= threshold:
                return best_side
            return None

        arm_side_now = extended_side(
            {"left": left_arm_reach, "right": right_arm_reach}, arm_extend_above
        )
        leg_side_now = extended_side(
            {"left": left_leg_reach, "right": right_leg_reach}, leg_extend_above
        )

        elbow_angle = knee_angle = None
        alignment_angle = None

        rep_completed = False
        rep_quality = None

        if self.ready:
            if self.stage == "tabletop":
                if arm_side_now is not None or leg_side_now is not None:
                    # A reach attempt is beginning.
                    self.stage = "reaching"
                    self._reset_attempt()
                    self._reach_start_time = t
                    self._reach_arm_side = arm_side_now
                    self._reach_leg_side = leg_side_now
            else:  # self.stage == "reaching"
                # Track whichever side is currently reaching for each limb
                # (allow it to resolve/settle over the first few frames,
                # but once both are known, a side switch means the reach
                # was abandoned and restarted — not a smooth continuation).
                # Debounced: a single noisy frame (tracking jitter, brief
                # occlusion) reading the "wrong" side must NOT be able to
                # nuke an otherwise-correct rep — only a sustained switch
                # over SWITCH_DEBOUNCE_FRAMES consecutive frames counts.
                if self._reach_arm_side is None:
                    self._reach_arm_side = arm_side_now
                    self._arm_switch_streak = 0
                elif arm_side_now is not None and arm_side_now != self._reach_arm_side:
                    self._arm_switch_streak += 1
                    if self._arm_switch_streak >= SWITCH_DEBOUNCE_FRAMES:
                        self._reach_invalidated = True
                        self._reach_invalid_reason = (
                            "You switched arms mid-rep — reset to tabletop and "
                            "reach one arm and the opposite leg together."
                        )
                else:
                    self._arm_switch_streak = 0

                if self._reach_leg_side is None:
                    self._reach_leg_side = leg_side_now
                    self._leg_switch_streak = 0
                elif leg_side_now is not None and leg_side_now != self._reach_leg_side:
                    self._leg_switch_streak += 1
                    if self._leg_switch_streak >= SWITCH_DEBOUNCE_FRAMES:
                        self._reach_invalidated = True
                        self._reach_invalid_reason = (
                            "You switched legs mid-rep — reset to tabletop and "
                            "reach one arm and the opposite leg together."
                        )
                else:
                    self._leg_switch_streak = 0

                # ---- THE core anti-cheat check: same-side vs opposite ----
                if (
                    not self._reach_invalidated
                    and self._reach_arm_side is not None
                    and self._reach_leg_side is not None
                    and self._reach_arm_side == self._reach_leg_side
                ):
                    self._reach_invalidated = True
                    self._reach_invalid_reason = (
                        "That's a same-side raise — a real bird dog reaches "
                        "OPPOSITE arm and leg together, not both on one side."
                    )

                active_arm = self._reach_arm_side
                active_leg = self._reach_leg_side

                if active_arm == "left":
                    elbow_angle = (
                        _angle_deg(l_shoulder, l_elbow, l_wrist)
                        if left_arm_ok
                        else None
                    )
                elif active_arm == "right":
                    elbow_angle = (
                        _angle_deg(r_shoulder, r_elbow, r_wrist)
                        if right_arm_ok
                        else None
                    )

                if active_leg == "left":
                    knee_angle = (
                        _angle_deg(l_hip, l_knee, l_ankle) if left_leg_ok else None
                    )
                elif active_leg == "right":
                    knee_angle = (
                        _angle_deg(r_hip, r_knee, r_ankle) if right_leg_ok else None
                    )

                # Back-line straightness, judged against the GROUNDED
                # (non-reaching) side's knee, exactly like the plank family
                # judges shoulder-hip-ankle straightness.
                stance_side = "right" if active_leg == "left" else "left"
                stance_knee = r_knee if stance_side == "right" else l_knee
                stance_leg_ok = right_leg_ok if stance_side == "right" else left_leg_ok
                if stance_leg_ok:
                    alignment_angle = _angle_deg(mid_shoulder, mid_hip, stance_knee)
                    if alignment_angle < ALIGNMENT_FLAW_BELOW:
                        dx = stance_knee.x - mid_shoulder.x
                        if abs(dx) > 1e-6:
                            frac = (mid_hip.x - mid_shoulder.x) / dx
                            expected_y = mid_shoulder.y + frac * (
                                stance_knee.y - mid_shoulder.y
                            )
                            deviation = mid_hip.y - expected_y
                            if deviation > 0:
                                self._reach_issues.add("back_sag")
                            else:
                                self._reach_issues.add("back_arch")

                if (
                    self.twist_calibrated
                    and shoulder_width > 1e-6
                    and abs((hip_width / shoulder_width) - self._baseline_twist_ratio)
                    > HIP_TWIST_RATIO_DELTA
                ):
                    self._reach_issues.add("hip_twist")

                active_arm_angle = (
                    left_arm_reach if active_arm == "left" else right_arm_reach
                )
                active_leg_angle = (
                    left_leg_reach if active_leg == "left" else right_leg_reach
                )

                fully_extended = (
                    active_arm is not None
                    and active_leg is not None
                    and elbow_angle is not None
                    and knee_angle is not None
                    and elbow_angle >= ELBOW_STRAIGHT_MIN
                    and knee_angle >= KNEE_STRAIGHT_MIN
                    and (active_arm_angle or 0) >= arm_extend_above
                    and (active_leg_angle or 0) >= leg_extend_above
                )

                if fully_extended and not self._reach_invalidated:
                    self._reach_ever_fully_extended = True
                    self._reach_hold_time += dt

                # ---- exit reach back to tabletop ----
                both_relaxing = (
                    (arm_side_now is None)
                    and (leg_side_now is None)
                    and both_arms_tucked
                    and both_legs_tucked
                )
                reach_duration = (
                    t - self._reach_start_time if self._reach_start_time else 0.0
                )
                timed_out = reach_duration > MAX_REP_DURATION

                if both_relaxing or timed_out:
                    self.stage = "tabletop"

                    valid = (
                        not self._reach_invalidated
                        and self._reach_ever_fully_extended
                        and self._reach_hold_time >= MIN_HOLD_SECONDS
                        and MIN_REP_DURATION <= reach_duration <= MAX_REP_DURATION
                    )

                    if valid:
                        rep_completed = True
                        self.rep_count += 1
                        if self._reach_issues:
                            rep_quality = "needs_improvement"
                            self.flawed_reps += 1
                            issue_text = ", ".join(
                                i.replace("_", " ") for i in sorted(self._reach_issues)
                            )
                            feedback = (
                                f"Rep {self.rep_count} counted, but watch your "
                                f"form ({issue_text})."
                            )
                        else:
                            rep_quality = "good"
                            self.good_reps += 1
                            feedback = (
                                f"Clean rep {self.rep_count} — opposite "
                                f"{self._reach_arm_side} arm / "
                                f"{self._reach_leg_side} leg, fully extended."
                            )
                    else:
                        self.rejected_reps += 1
                        if self._reach_invalidated:
                            feedback = self._reach_invalid_reason
                        elif not self._reach_ever_fully_extended:
                            feedback = (
                                "Not counted — reach your arm and opposite leg "
                                "all the way out straight, in line with your back."
                            )
                        elif self._reach_hold_time < MIN_HOLD_SECONDS:
                            feedback = (
                                "Not counted — that was too quick. Hold the "
                                "extension for a beat before returning."
                            )
                        elif reach_duration < MIN_REP_DURATION:
                            feedback = "Too fast — not counted, control the movement."
                        else:
                            feedback = "That attempt wasn't counted — reset to tabletop and try again."

                    self._reset_attempt()

        response["stage"] = self.stage
        response["reach_arm_side"] = self._reach_arm_side
        response["reach_leg_side"] = self._reach_leg_side
        response["elbow_angle"] = (
            round(elbow_angle, 1) if elbow_angle is not None else None
        )
        response["knee_angle"] = (
            round(knee_angle, 1) if knee_angle is not None else None
        )
        response["alignment_angle"] = (
            round(alignment_angle, 1) if alignment_angle is not None else None
        )
        response["posture_issues"] = sorted(self._reach_issues)
        response["rep_completed"] = rep_completed
        response["rep_form_quality"] = rep_quality
        response["rep_count"] = self.rep_count
        response["good_reps"] = self.good_reps
        response["flawed_reps"] = self.flawed_reps
        response["rejected_reps"] = self.rejected_reps
        response["session_complete"] = self._is_complete()
        response["calibrating"] = not self.base_calibrated
        response["base_calibrated"] = self.base_calibrated
        response["calibrated"] = self.base_calibrated
        response["baseline_arm_angle"] = (
            round(self.baseline_arm_angle, 1)
            if self.baseline_arm_angle is not None
            else None
        )
        response["baseline_leg_angle"] = (
            round(self.baseline_leg_angle, 1)
            if self.baseline_leg_angle is not None
            else None
        )

        if feedback is None and self.stage == "reaching":
            feedback = "Reaching — hold it, arm and opposite leg straight and long."
        if feedback is None:
            feedback = "Good tabletop position — reach one arm and the opposite leg."
        response["feedback"] = feedback

        return response

    # ---------------------------------------------------------------
    def _register_bad_frame(self):
        self._bad_streak += 1
        self._base_streak = 0
        if self._bad_streak >= GRACE_FRAMES and self.stage == "tabletop":
            self.ready = False
        if self.stage == "reaching":
            # Losing tracking mid-reach invalidates the attempt — it can't
            # be verified, so it doesn't count.
            self._reach_invalidated = True
            self._reach_invalid_reason = (
                "Lost tracking mid-rep — not counted. Reset to tabletop and try again."
            )


class BirdDogSession:
    """Full bird-dog session: one shared pose model + one analyzer.

    `target_reps` / `target_sets` / `set_number` are the coach-assigned
    plan for this user, supplied by the caller (the websocket route, from
    query params) — same convention as `PushupSession` / `SidePlankSession`.
    The frontend does not decide on its own whether a set/exercise is
    done; `session_complete` and `exercise_complete` are both computed
    here.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        # Bird dog is filmed farther back than a close-up exercise (the
        # whole body, fingertip to opposite foot, has to fit in frame), so
        # use the same lower confidence floor `poseEngine.py` recommends
        # for full-body / farther-away exercises rather than the close-up
        # defaults.
        self.engine = PoseEngine(
            min_detection_confidence=0.6,
            min_presence_confidence=0.6,
            min_tracking_confidence=0.55,
        )
        self.analyzer = BirdDogAnalyzer(target_reps)
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
