"""
Seated Cable Shrug — seated, holding a low-pulley cable handle with arms
extended in front of the body. Starting position: shoulders let all the
way down/sagged. Rep: shrug the shoulders straight up toward the ears as
far as possible, pause briefly, then slowly lower back to fully sagged.
(Reference: https://www.muscleandstrength.com/exercises/seated-cable-shrug.html)

Why this exercise needs its own signal (not a reused joint angle)
------------------------------------------------------------------
Every other analyzer in this codebase drives its rep state machine off a
joint *angle* (elbow angle, hip flexion angle, knee angle...) because
angles are naturally scale- and distance-invariant — 90 degrees means the
same thing whether the camera is close or far, tall person or short.

A shrug has no comparable joint angle: it's a near-pure vertical
translation of the shoulder girdle (scapular elevation), not a rotation
around a joint that stays in a fixed spot. So instead this analyzer
measures the **neck gap** — the vertical on-screen distance between each
ear and its shoulder, normalized by shoulder width (a length that does
NOT change as someone shrugs, so it works as a stable, camera-distance-
invariant scale reference):

    neck_gap_ratio = (shoulder.y - ear.y) / shoulder_width

When the shoulders sag all the way down (the resting/starting position),
this ratio is at its largest for that person. When the shoulders shrug up
toward the ears, the ratio shrinks.

Because neck length / shoulder width varies a lot between people (and
with camera angle), a single fixed universal threshold would either miss
short-necked people's real reps or count a tall person's small twitch as
a full shrug. So this analyzer **auto-calibrates**: it watches the first
couple of seconds of a confirmed-seated session (the person is expected
to start relaxed/sagged, exactly as the exercise instructions describe)
and records the largest ratio observed as that person's own "fully
sagged" baseline. Every threshold from then on is expressed as a
*percentage of that person's own baseline*, not an absolute number — so
the counter adapts to anyone's proportions and camera setup rather than
guessing a one-size-fits-all number. The baseline is also allowed to
keep drifting UP afterward (never down) if an even more relaxed sag is
observed later, so it keeps tracking the person's true bottom rather than
locking in on an initial position that wasn't fully relaxed.

Cheat-form detection (per the exercise's own "tips")
------------------------------------------------------
* "Focus on lifting the weight with your traps and not your biceps" ->
  tracked via elbow angle (shoulder-elbow-wrist). The arms are supposed
  to stay extended out in front the whole rep; if the elbow bends
  noticeably during the ascent, that's the person curling the weight up
  with their arms instead of shrugging, and gets flagged.
* Leaning back / using body momentum to help heave the weight up (a very
  common cable-shrug cheat) -> tracked via torso lean: if the mid-hip to
  mid-shoulder line tips backward beyond a tolerance during the rep, it's
  flagged.
* Standing up / bouncing out of the seat to help the pull -> tracked via
  hip stability: the hip midpoint has to stay within a small band of
  where it was when the seated position was confirmed, for the whole
  rep, or the rep is invalidated rather than counted.

None of these cheat flags block a genuine shrug from counting — same
tiering as every other analyzer here (push-up hip sag, flutter kicks knee
bend): a real rep that alternates/completes still counts, just tagged
"needs_improvement" instead of "good".
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_EAR,
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_SHOULDER,
    LEFT_WRIST,
    NOSE,
    PoseEngine,
    RIGHT_EAR,
    RIGHT_ELBOW,
    RIGHT_HIP,
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


# ---- seated / upright gate ----
# Torso incline here is measured from VERTICAL (unlike the floor-exercise
# analyzers which measure incline from horizontal) since this movement is
# done sitting upright.
UPRIGHT_MIN_DEG = 60.0  # torso must read at least this close to vertical
STABLE_SEATED_FRAMES = 5
GRACE_FRAMES = 20  # ~0.65s of tolerance for a brief tracking hiccup before
# dropping "ready" mid-rep — a real webcam has motion blur and brief
# low-confidence frames, especially during the shrug itself.

# Hips must stay within this fraction of shoulder-width of where they were
# when "seated" was first confirmed — guards against standing up / bouncing
# out of the seat to help heave the weight.
HIP_DRIFT_MAX_RATIO = 0.35

# ---- calibration (establishes this person's own "fully sagged" baseline) ----
CALIBRATION_MIN_FRAMES = 30  # ~1s at 30fps
CALIBRATION_MAX_FRAMES = 90  # ~3s — stop waiting and lock in whatever we have
CALIBRATION_MIN_SAMPLES = 15  # need at least this many valid samples

# ---- shrug thresholds, expressed as a fraction of the calibrated baseline ----
# neck_gap_ratio shrinks as the shoulders rise, so "top" is a LOW fraction
# and "bottom" is a HIGH fraction of the sagged baseline.
#
# Calibrated against real shoulder-shrug biomechanics: voluntary scapular
# elevation averages ~37-40 deg (Archives of Orthopaedic and Trauma Surgery,
# goniometer study, n=30; consistent with the commonly cited ~40 deg normal
# ROM figure). Mapped through this analyzer's neck_gap_ratio proxy, a real,
# full-effort shrug ("as high as you can", per the exercise's own cue)
# reduces the ratio by roughly 18-25% from the sagged baseline -- not the
# 28% the previous 0.72 threshold demanded. That stricter value made the
# "up" phase essentially unreachable for a correctly performed rep (a
# realistic 22%-reduction shrug never crossed 0.72 and the counter never
# left "down" -- confirmed by simulation), which is why reps weren't being
# counted at all, correct form or not.
TOP_SHRUG_FRACTION = 0.80  # ratio must drop to <= 80% of baseline to count as "up"
BOTTOM_RESET_FRACTION = 0.93  # must climb back to >= 93% of baseline to re-arm "down"
# The gap between 0.80 and 0.93 is a dead zone so a single noisy frame can't
# flip the state back and forth.

CONFIRM_FRAMES = 3  # consecutive agreeing frames before a phase change is confirmed

MIN_REP_DURATION = 0.5  # seconds — a full down->up->down cycle can't be faster
MAX_REP_DURATION = 12.0  # seconds — very slow, deliberate reps still count
MIN_TOP_PAUSE = 0.3  # seconds held at the top before starting back down, for
# the "good pause" quality tag (the exercise's own tip) — NOT required to count

# ---- cheat-form thresholds (quality flags, do not block counting) ----
ELBOW_BEND_FLAW_BELOW = 145.0  # elbow angle (shoulder-elbow-wrist); below this
# during the ascent reads as "curling with the arms" rather than a pure shrug
TORSO_LEAN_FLAW_DEG = 12.0  # degrees of backward lean change from the
# rep's starting torso angle before it's flagged as "using momentum"

# ---- camera framing ----
FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.95
BBOX_TOO_FAR = 0.15


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


def _torso_vertical_incline_deg(mid_shoulder, mid_hip) -> Optional[float]:
    """Degrees off TRUE VERTICAL (90 = perfectly upright, 0 = lying flat)."""
    dx = mid_hip.x - mid_shoulder.x
    dy = mid_hip.y - mid_shoulder.y
    if dx == 0 and dy == 0:
        return None
    return math.degrees(math.atan2(abs(dy), max(abs(dx), 1e-9)))


def _torso_signed_lean_deg(mid_shoulder, mid_hip) -> float:
    """Signed lean angle used to detect a CHANGE in lean over the course of
    a rep (leaning back to use momentum), not just upright-vs-not."""
    dx = mid_shoulder.x - mid_hip.x
    dy = mid_hip.y - mid_shoulder.y
    return math.degrees(math.atan2(dx, max(dy, 1e-9)))


def _bbox_aspect_and_points(points: list[_Point]):
    if len(points) < 4:
        return None
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    if height <= 1e-6:
        return None
    return width / height


def _framing_feedback(points: list[_Point]) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — reposition so your head, "
                "shoulders, and hips are all visible."
            )

    if len(points) < 4:
        return None

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return (
            "You're too close to the camera — back up so your upper body fits in frame."
        )
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class SeatedCableShrugAnalyzer:
    """Stateful seated-cable-shrug rep counter with automatic per-person
    calibration of the "fully sagged" baseline, plus cheat-form flags for
    arm-curling, momentum/lean, and standing-up-out-of-the-seat."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        # Phase state machine: "down" (sagged/bottom) or "up" (shrugged/top)
        self.phase = "down"
        self._pending_phase: Optional[str] = None
        self._pending_streak = 0

        self.rep_start_time: Optional[float] = None
        self.top_reached_time: Optional[float] = None
        self.last_rep_time: Optional[float] = None
        self.session_start_time: Optional[float] = None

        # Seated-position gating
        self._seated_streak = 0
        self._bad_streak = 0
        self._visibility_bad_streak = 0
        self.ready = False
        self.seated_hip_anchor: Optional[_Point] = None
        self.seated_shoulder_width: Optional[float] = None

        # Calibration of this person's own "fully sagged" baseline
        self._calibrating = True
        self._calibration_frame_count = 0
        self._calibration_samples: list[float] = []
        self.baseline_ratio: Optional[float] = None

        # Per-rep quality tracking
        self._rep_min_elbow_angle: Optional[float] = None
        self._rep_start_lean_deg: Optional[float] = None
        self._rep_max_lean_delta: float = 0.0
        self._rep_broke_position = False

    # ---------------------------------------------------------------
    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 6.0:
            return "too_slow"
        if duration >= 2.5:
            return "slow"
        if duration >= 1.0:
            return "good"
        if duration >= MIN_REP_DURATION:
            return "fast"
        return "too_fast"

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _reset_calibration(self):
        """Position was lost before calibration finished — start over once
        it's re-confirmed, rather than locking in a bad partial baseline."""
        self._calibrating = True
        self._calibration_frame_count = 0
        self._calibration_samples = []
        self.baseline_ratio = None

    # ---------------------------------------------------------------
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
            "calibrating": self._calibrating,
            "calibration_progress": (
                round(
                    min(
                        1.0,
                        len(self._calibration_samples) / CALIBRATION_MIN_SAMPLES,
                    ),
                    2,
                )
                if self._calibrating
                else 1.0
            ),
            "baseline_ratio": (
                round(self.baseline_ratio, 3) if self.baseline_ratio else None
            ),
            "neck_gap_ratio": None,
            "shrug_progress": None,  # 0.0 (fully sagged) -> 1.0 (fully shrugged)
            "left_elbow_angle": None,
            "right_elbow_angle": None,
            "phase": self.phase,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_duration": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "rep_flaws": [],
            "top_pause_duration": None,
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            self._visibility_bad_streak += 1
            if self._visibility_bad_streak >= GRACE_FRAMES:
                self._invalidate_in_progress_rep()
                self.ready = False
            response["feedback"] = (
                "No person detected — sit facing the camera with your "
                "head, shoulders, and hips visible."
            )
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_ear, r_ear = landmarks[LEFT_EAR], landmarks[RIGHT_EAR]
        nose = landmarks[NOSE]
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]

        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))

        if not torso_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._visibility_bad_streak += 1
            if self._visibility_bad_streak >= GRACE_FRAMES:
                self._invalidate_in_progress_rep()
                self.ready = False
            response["feedback"] = (
                "Can't see your torso clearly — make sure your shoulders "
                "and hips are both in frame."
            )
            return response

        response["pose_detected"] = True

        left_side_ok = _visible((l_shoulder, l_ear))
        right_side_ok = _visible((r_shoulder, r_ear))
        nose_ok = _visible((nose,))

        # A dead-on front-facing camera — the natural way to film a seated
        # cable shrug from a propped-up phone — is exactly the angle where
        # MediaPipe's ear landmarks are LEAST reliable (ears are mostly a
        # profile-view feature). Requiring an ear to be visible at all was
        # hard-failing this exercise for the most common real camera setup.
        # Fall back to the nose as the head-level reference instead — since
        # this analyzer only ever measures *relative* change against a
        # calibrated personal baseline, the fallback reference doesn't need
        # to be anatomically identical to the ear, it just needs to move
        # consistently as the shoulder rises, which the nose does too.
        using_ear_reference = left_side_ok or right_side_ok

        if not using_ear_reference and not nose_ok:
            response["low_visibility"] = True
            self._visibility_bad_streak += 1
            if self._visibility_bad_streak >= GRACE_FRAMES:
                self._invalidate_in_progress_rep()
                self.ready = False
            response["feedback"] = (
                "Can't see your head clearly — face the camera so your "
                "face and shoulders are both visible."
            )
            return response

        # Cleared every visibility gate this frame — the tracking hiccup
        # (if any) is over, so stop counting toward the grace threshold.
        self._visibility_bad_streak = 0

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        shoulder_width = max(_dist(l_shoulder, r_shoulder), 1e-6)

        torso_vertical_incline = _torso_vertical_incline_deg(mid_shoulder, mid_hip)
        signed_lean = _torso_signed_lean_deg(mid_shoulder, mid_hip)

        bbox_candidates = [
            p
            for p in (l_shoulder, r_shoulder, l_hip, r_hip, l_ear, r_ear)
            if _visible((p,))
        ]
        bbox_points = [_Point(p.x, p.y) for p in bbox_candidates]
        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        is_upright = (
            torso_vertical_incline is not None
            and torso_vertical_incline >= UPRIGHT_MIN_DEG
        )

        # ---- hip-stability check (guards against standing up / bouncing) ----
        hip_stable = True
        if self.seated_hip_anchor is not None and self.seated_shoulder_width:
            hip_drift = _dist(mid_hip, self.seated_hip_anchor)
            hip_stable = hip_drift <= HIP_DRIFT_MAX_RATIO * self.seated_shoulder_width

        is_seated_ok = is_upright and hip_stable

        if is_seated_ok:
            self._seated_streak += 1
            self._bad_streak = 0
        else:
            self._seated_streak = 0
            self._bad_streak += 1

        if self._seated_streak >= STABLE_SEATED_FRAMES:
            if not self.ready:
                # Freshly (re-)confirmed seated — anchor hip position.
                self.seated_hip_anchor = mid_hip
                self.seated_shoulder_width = shoulder_width
                # Only (re-)run calibration if we don't already have a good
                # baseline. A brief readiness drop from an ordinary tracking
                # hiccup (motion blur, a low-confidence frame) shouldn't
                # force the person to sit frozen for another 1-3s and lose
                # whatever rep was in progress — their "fully sagged"
                # baseline hasn't actually changed just because tracking
                # blipped for a few frames.
                if self.baseline_ratio is None:
                    self._reset_calibration()
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES:
            if self.ready:
                self._invalidate_in_progress_rep()
            self.ready = False

        response["position_ok"] = self.ready
        response["ready"] = self.ready

        if not self.ready:
            response["position_message"] = (
                "Sit upright facing the camera, feet planted, holding the "
                "handle with arms extended in front — hold still so your "
                "seated position can be confirmed."
            )
            response["feedback"] = response["position_message"]
            return response

        # ---- per-side neck gap (shoulder.y - ear.y — positive, shrinks
        # toward zero as the shoulder rises up toward the ear), normalized ----
        side_ratios = []
        if left_side_ok:
            side_ratios.append((l_shoulder.y - l_ear.y) / shoulder_width)
        if right_side_ok:
            side_ratios.append((r_shoulder.y - r_ear.y) / shoulder_width)

        if side_ratios:
            neck_gap_ratio = sum(side_ratios) / len(side_ratios)
        else:
            # Neither ear usable this frame (common straight-on camera
            # angle) — fall back to the nose as the head-level reference.
            neck_gap_ratio = (mid_shoulder.y - nose.y) / shoulder_width
        response["neck_gap_ratio"] = round(neck_gap_ratio, 3)

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
        response["left_elbow_angle"] = (
            round(left_elbow_angle, 1) if left_elbow_angle is not None else None
        )
        response["right_elbow_angle"] = (
            round(right_elbow_angle, 1) if right_elbow_angle is not None else None
        )

        # ---- calibration: learn this person's own "fully sagged" baseline ----
        if self._calibrating:
            self._calibration_frame_count += 1
            self._calibration_samples.append(neck_gap_ratio)

            done_enough = (
                len(self._calibration_samples) >= CALIBRATION_MIN_SAMPLES
                and self._calibration_frame_count >= CALIBRATION_MIN_FRAMES
            )
            timed_out = self._calibration_frame_count >= CALIBRATION_MAX_FRAMES

            if done_enough or timed_out:
                if self._calibration_samples:
                    self.baseline_ratio = max(self._calibration_samples)
                self._calibrating = False

            response["calibrating"] = self._calibrating
            response["calibration_progress"] = round(
                min(1.0, len(self._calibration_samples) / CALIBRATION_MIN_SAMPLES),
                2,
            )

            if self._calibrating:
                response["feedback"] = (
                    "Calibrating — hold your starting position with "
                    "shoulders fully relaxed and sagged for a moment."
                )
                return response

        # Baseline can keep drifting UP (an even more relaxed sag observed
        # later) but never down, so the reference always reflects the
        # person's true bottom rather than an initial partial relax.
        if self.baseline_ratio is None:
            self.baseline_ratio = neck_gap_ratio
        elif neck_gap_ratio > self.baseline_ratio:
            self.baseline_ratio = neck_gap_ratio

        response["baseline_ratio"] = round(self.baseline_ratio, 3)

        shrug_progress = 0.0
        if self.baseline_ratio > 1e-6:
            shrug_progress = 1.0 - (neck_gap_ratio / self.baseline_ratio)
        shrug_progress = max(0.0, min(1.0, shrug_progress))
        response["shrug_progress"] = round(shrug_progress, 2)

        # ---- track worst cheat signals for whichever rep is in progress ----
        if self.phase == "up" or self._pending_phase == "up":
            if left_elbow_angle is not None:
                self._rep_min_elbow_angle = (
                    left_elbow_angle
                    if self._rep_min_elbow_angle is None
                    else min(self._rep_min_elbow_angle, left_elbow_angle)
                )
            if right_elbow_angle is not None:
                self._rep_min_elbow_angle = (
                    right_elbow_angle
                    if self._rep_min_elbow_angle is None
                    else min(self._rep_min_elbow_angle, right_elbow_angle)
                )

        if self._rep_start_lean_deg is not None:
            lean_delta = abs(signed_lean - self._rep_start_lean_deg)
            self._rep_max_lean_delta = max(self._rep_max_lean_delta, lean_delta)

        if not hip_stable:
            self._rep_broke_position = True

        # ---- phase state machine (down -> up -> down = 1 rep) ----
        top_threshold = self.baseline_ratio * TOP_SHRUG_FRACTION
        bottom_threshold = self.baseline_ratio * BOTTOM_RESET_FRACTION

        if neck_gap_ratio <= top_threshold:
            candidate_phase = "up"
        elif neck_gap_ratio >= bottom_threshold:
            candidate_phase = "down"
        else:
            candidate_phase = None  # dead zone — mid-shrug, don't force a flip

        feedback = framing_message
        rep_completed = False
        rep_duration = rep_class = rep_form_quality = None
        rep_flaws: list[str] = []
        top_pause_duration = None

        if candidate_phase is not None and candidate_phase == self._pending_phase:
            self._pending_streak += 1
        elif candidate_phase is not None:
            self._pending_phase = candidate_phase
            self._pending_streak = 1
        else:
            self._pending_phase = None
            self._pending_streak = 0

        if (
            candidate_phase is not None
            and self._pending_streak >= CONFIRM_FRAMES
            and candidate_phase != self.phase
        ):
            if candidate_phase == "up":
                self.phase = "up"
                self.top_reached_time = t
                if self.rep_start_time is None:
                    self.rep_start_time = t
                self._rep_start_lean_deg = signed_lean
                self._rep_max_lean_delta = 0.0
                self._rep_min_elbow_angle = None
                self._rep_broke_position = False
                feedback = "Top of the shrug — pause briefly, then lower slowly."

            else:  # candidate_phase == "down": completes a rep if we came from "up"
                if self.phase == "up":
                    duration = (
                        (t - self.rep_start_time)
                        if self.rep_start_time is not None
                        else None
                    )
                    top_pause_duration = (
                        (t - self.top_reached_time)
                        if self.top_reached_time is not None
                        else None
                    )
                    valid = (
                        duration is not None
                        and MIN_REP_DURATION <= duration <= MAX_REP_DURATION
                    )

                    if valid:
                        self.rep_count += 1
                        rep_completed = True
                        rep_duration = duration
                        rep_class = self._classify_tempo(duration)

                        if (
                            self._rep_min_elbow_angle is not None
                            and self._rep_min_elbow_angle < ELBOW_BEND_FLAW_BELOW
                        ):
                            rep_flaws.append("arms_curling")
                        if self._rep_max_lean_delta > TORSO_LEAN_FLAW_DEG:
                            rep_flaws.append("leaning_for_momentum")
                        if self._rep_broke_position:
                            rep_flaws.append("shifted_in_seat")
                        if (
                            top_pause_duration is not None
                            and top_pause_duration < MIN_TOP_PAUSE
                        ):
                            rep_flaws.append("no_pause_at_top")

                        if rep_flaws:
                            rep_form_quality = "needs_improvement"
                            self.flawed_reps += 1
                            flaw_text = {
                                "arms_curling": "keep your arms extended — lift with your traps, not your arms",
                                "leaning_for_momentum": "avoid leaning back — keep your torso still and upright",
                                "shifted_in_seat": "stay seated and still — don't rise up to help the pull",
                                "no_pause_at_top": "pause briefly at the top for a count of 1-3",
                            }
                            feedback = (
                                f"Rep {self.rep_count} counted, but "
                                f"{flaw_text[rep_flaws[0]]}."
                            )
                        else:
                            rep_form_quality = "good"
                            self.good_reps += 1
                            feedback = (
                                f"Clean shrug — {rep_class} tempo "
                                f"({duration:.2f}s). Rep {self.rep_count}."
                            )
                    else:
                        feedback = (
                            "Too fast — that shrug wasn't counted, slow it down."
                            if duration is not None and duration < MIN_REP_DURATION
                            else "Not counted — keep the range of motion continuous."
                        )

                    self.rep_start_time = None
                    self.top_reached_time = None

                self.phase = "down"

        if feedback is None:
            if self.phase == "up":
                feedback = "Hold, then slowly lower back down."
            else:
                feedback = "Shrug your shoulders straight up toward your ears."

        response.update(
            {
                "phase": self.phase,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_duration": rep_duration,
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "rep_flaws": rep_flaws,
                "top_pause_duration": (
                    round(top_pause_duration, 2)
                    if top_pause_duration is not None
                    else None
                ),
                "feedback": feedback,
            }
        )
        return response

    # ---------------------------------------------------------------
    def _invalidate_in_progress_rep(self):
        """Seated position broke (or person left frame) mid-rep — don't
        silently resume and count a rep that spanned an invalid stretch."""
        self._pending_phase = None
        self._pending_streak = 0
        self.rep_start_time = None
        self.top_reached_time = None
        self._rep_min_elbow_angle = None
        self._rep_start_lean_deg = None
        self._rep_max_lean_delta = 0.0
        self._rep_broke_position = False
        self.phase = "down"


class SeatedCableShrugSession:
    """Full seated-cable-shrug session: one shared pose model + one
    analyzer. Same convention as `PushupSession` / `FlutterKicksSession` —
    the coach-assigned plan (`target_reps` / `target_sets` / `set_number`)
    is supplied by the caller (the websocket route, from query params),
    and `session_complete` / `exercise_complete` are computed here, not on
    the frontend.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = SeatedCableShrugAnalyzer(target_reps)
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
