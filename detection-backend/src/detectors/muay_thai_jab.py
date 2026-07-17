"""
Muay Thai jab rep counting + guard-position validation.

Design
------
`JabAnalyzer` follows the same shape as every other analyzer in this
codebase (see squat.py / mountain_climber.py): one shared `PoseEngine`
(owned by `JabSession`) feeds it the 33-point pose landmark list every
frame; it knows nothing about the camera or the websocket around it.

Both hands are tracked independently and simultaneously, each with its own
guard/punch hysteresis state machine (mirrors mountain_climber.py's
per-leg tracking) — a jab drill legitimately repeats the same hand over
and over ("jab, jab, jab"), unlike mountain climbers, so there is
deliberately NO alternation requirement here.

Why this needs its own anti-misuse gate
------------------------------------------
An elbow simply straightening out isn't a jab — someone could reach for
something on a shelf and it would look identical on an elbow-angle graph
alone. What actually makes a punch a *jab* is that it starts and ends from
a guard (fist up, protecting the face), not from some arbitrary position.
So, same principle as mountain_climber.py's plank gate:

  * `guard_ok(side)` — checked every frame per hand: is that fist
    currently up near head height, within this person's own calibrated
    guard baseline. A punch only counts if the hand was genuinely in
    guard the instant it launched (`_rep_guard_ok_start`) — reaching from
    some other position never counts, no matter how far the elbow
    straightens.
  * The hand must also come back to a valid guard for the "punching ->
    guard" transition to register as a real completed rep at all; a
    punch that never retracts back up doesn't complete.
  * Rejected guard-less attempts are tracked separately
    (`not_counted_no_guard`), same idea as mountain_climber.py's
    `not_counted_no_plank` — visible to a coach as its own signal, not
    silently absorbed into "flawed" reps.

Rep counting
------------
Each hand has its own hip-independent elbow-angle (shoulder-elbow-wrist)
hysteresis state machine:

  * "guard"    — elbow bent, fist near the face (rest position).
  * "punching" — arm thrown out toward full extension.

A rep completes on the "punching" -> "guard" transition (arm snapped back
to guard), mirroring every other exercise in this codebase completing on
the return-to-rest transition, not the extension itself — a jab that's
thrown but never retracted leaves the fighter's face uncovered, so it
isn't "done" until it comes back.

Mistake detection
------------------
Checked live (every frame, once calibrated against the person's own
guard baseline) and rolled into whichever hand's rep is in progress:
  * dropped_guard   — the OTHER (non-punching) hand fell out of guard
                      while this hand was punching — the single most
                      common real mistake (leaving your chin open).
  * looping_punch   — the fist swung out in a curved path instead of
                      travelling in roughly a straight line from guard to
                      full extension (i.e. a hook, not a jab).
  * overreaching    — the whole torso lurched forward into the punch
                      instead of just the arm extending.
  * shallow_punch    (hard gate, not counted) — the elbow never got close
                      enough to full extension this rep — range-of-motion
                      floor, same idea as squat's depth check.
  * half_jab (partial) — the arm started extending but pulled back before
                      crossing the extension threshold; not counted,
                      mirrors squat's "squat lower" nudge.
  * too fast / too slow (hard gate, not counted) — rep duration outside
                      the valid window.

A flawed-form rep still counts (same "perfect or nothing is discouraging"
philosophy as every other exercise here) but is tagged `rep_form_quality:
"needs_improvement"` with the specific issues, and rolls into
`flawed_reps` alongside `good_reps`. A punch thrown from outside a valid
guard is a harder case — it does not count at all, tracked separately in
`not_counted_no_guard`.

Landmark confidence, smoothing, camera framing
-------------------------------------------------
Same posture as the rest of this codebase: every landmark used is
visibility-gated (`_visible`), each hand's angle is EMA-smoothed to reject
jitter, missing limbs degrade gracefully instead of crashing, and
`_framing_feedback` checks edge-clipping / distance-from-camera /
centering every frame. One framing note specific to this exercise: a jab
is best tracked with the fighter turned slightly (roughly 30-45 degrees)
to the camera rather than squared straight-on — that's also just correct
boxing stance, so the coaching copy asks for it rather than working
around it.
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_SHOULDER,
    LEFT_WRIST,
    NOSE,
    PoseEngine,
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


def _clip(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


# Elbow angle (shoulder-elbow-wrist), in degrees — the ONLY quantity that
# drives the guard/punch hysteresis and every ROM check below. Everything
# here is degrees, always, on purpose: mixing a normalized-ratio metric
# with degree-scale thresholds is exactly the kind of bug that silently
# stops an exercise from tracking at all, so this module never does it.
GUARD_ELBOW_ANGLE = 85.0  # elbow bent, fist at guard — at/below this = "guard"
PUNCH_ELBOW_ANGLE = 150.0  # elbow considered "thrown" once angle exceeds this
MIN_ANGLE_DELTA = 45.0  # total travel required for a rep to "count"
MIN_REP_DURATION = 0.12  # seconds — a snappy jab-retract can be well under 0.5s
MAX_REP_DURATION = 2.5  # seconds — slower than this = not a jab anymore, a reach

CALIBRATION_FRAMES = 15

# Range-of-motion floor for a counted rep: the elbow must have travelled at
# least this fraction of the guard->punch range at its peak.
EXTENSION_ROM_MIN = 0.75

PARTIAL_REP_MARGIN = 12.0
PARTIAL_REP_MIN_RISE = 18.0
PARTIAL_REP_BOUNCE = 8.0

# Guard-height check: how far (normalized by torso length) the wrist may
# sit from its own calibrated baseline offset-from-nose and still count as
# "in guard". This is the anti-misuse gate — a punch only counts if the
# hand was genuinely up in guard the instant it launched, and only
# completes once it's genuinely back in guard.
GUARD_HEIGHT_TOLERANCE = 0.30
GUARD_HEIGHT_HARD_TOLERANCE = 0.55  # frame-to-frame hard reject, no calibration needed

# Chin-guard (other hand) check — how much further than its own baseline
# the resting hand's wrist may drop before "dropped_guard" fires.
CHIN_GUARD_DROP_DELTA = 0.28

# Straight-punch check — max perpendicular deviation (normalized by torso
# length) of the wrist's path from the straight line between its guard
# start position and its peak-extension position this rep.
LOOPING_PUNCH_TOLERANCE = 0.22

# Overreach (torso lurch) check — how much the shoulder->hip horizontal
# offset may grow beyond its calibrated baseline during a punch.
OVERREACH_DELTA = 0.20

# -------------------------------------------------------------------------
# Camera framing thresholds — standing, facing (or angled toward) the
# camera; same shape as squat.py's framing check.
# -------------------------------------------------------------------------
FRAME_EDGE_MARGIN = 0.04
TORSO_SPAN_TOO_CLOSE = 0.55
TORSO_SPAN_TOO_FAR = 0.10
CENTER_X_TOLERANCE = 0.30


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


def _perp_deviation(line_a, line_b, point) -> float:
    """Unsigned perpendicular distance of `point` from the line
    line_a -> line_b, normalized by the line segment's own length (a
    body-scale-relative ratio, not raw image coordinates). Used to check
    whether the wrist travelled in roughly a straight line during a punch
    (a jab) rather than curving out to the side (a hook)."""
    vx, vy = line_b.x - line_a.x, line_b.y - line_a.y
    wx, wy = point.x - line_a.x, point.y - line_a.y
    v_len = math.hypot(vx, vy) or 1e-6
    cross = vx * wy - vy * wx
    return abs(cross / v_len) / v_len


def _framing_feedback(
    l_shoulder, r_shoulder, l_hip, r_hip, hands_visible: bool
) -> Optional[str]:
    """Coaches the user into a good spot for the camera — checked every
    frame, independent of exercise form. Returns a short instruction, or
    None if the current framing looks good."""
    mid_shoulder = _midpoint(l_shoulder, r_shoulder)
    mid_hip = _midpoint(l_hip, r_hip)

    for p in (l_shoulder, r_shoulder, l_hip, r_hip):
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — center yourself with space on all sides."
            )

    if not hands_visible:
        return "Can't see your hands — get your guard and whole upper body in frame."

    torso_span = _dist(mid_shoulder, mid_hip)
    if torso_span > TORSO_SPAN_TOO_CLOSE:
        return "You're too close to the camera — step back until your whole upper body fits in frame."
    if torso_span < TORSO_SPAN_TOO_FAR:
        return (
            "You're too far from the camera — move a bit closer for accurate tracking."
        )

    if abs(mid_shoulder.x - 0.5) > CENTER_X_TOLERANCE:
        return "Center yourself in frame, turned slightly toward the camera."

    return None


class JabAnalyzer:
    """Stateful, per-hand independent Muay Thai jab rep counter + guard
    position validator."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.stage = {"left": "guard", "right": "guard"}
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.partial_rep_count = 0
        # Punches thrown from outside a valid guard — rejected outright,
        # tracked separately since these are a harder case than "flawed".
        self.not_counted_no_guard = 0

        self.smoothed_angle: dict[str, Optional[float]] = {"left": None, "right": None}
        self.last_angle: dict[str, Optional[float]] = {"left": None, "right": None}
        self.rep_start_time: dict[str, Optional[float]] = {"left": None, "right": None}
        self._angle_acc = {"left": 0.0, "right": 0.0}
        self.angle_smooth_alpha = 0.6

        self.session_start_time: Optional[float] = None

        # "Extend further" partial-rep detection, per hand.
        self._attempt_max_angle: dict[str, Optional[float]] = {
            "left": None,
            "right": None,
        }
        self._attempt_flagged = {"left": False, "right": False}

        # Personal guard baseline: (wrist.y - nose.y) / torso_ref, captured
        # while both hands rest in guard. Calibrated per-hand since stance
        # and camera angle can put the lead/rear hand at slightly
        # different natural heights.
        self._calib_samples: dict[str, list[float]] = {"left": [], "right": []}
        self._calib_lean_samples: list[float] = []
        self.calibrated = False
        self._baseline_guard_offset = {"left": 0.0, "right": 0.0}
        self._baseline_lean = 0.0

        self._current_rep_issues: dict[str, set] = {"left": set(), "right": set()}
        self._rep_guard_ok_start = {"left": True, "right": True}
        self._rep_peak_extension_frac = {"left": 0.0, "right": 0.0}
        self._rep_start_wrist: dict[str, Optional[_Point]] = {
            "left": None,
            "right": None,
        }
        self._rep_peak_wrist: dict[str, Optional[_Point]] = {
            "left": None,
            "right": None,
        }
        self._rep_max_line_dev = {"left": 0.0, "right": 0.0}

    # ---------------------------------------------------------------
    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 1.4:
            return "too_slow"
        if duration >= 0.8:
            return "slow"
        if duration >= 0.35:
            return "good"
        if duration >= 0.22:
            return "fast"
        return "too_fast"

    def _is_complete(self) -> bool:
        if self.target_reps is None:
            return False
        return self.rep_count >= self.target_reps

    def _finish_calibration(self):
        for side in ("left", "right"):
            samples = self._calib_samples[side]
            if samples:
                self._baseline_guard_offset[side] = sum(samples) / len(samples)
        if self._calib_lean_samples:
            self._baseline_lean = sum(self._calib_lean_samples) / len(
                self._calib_lean_samples
            )
        self.calibrated = True

    def _guard_offset(self, side_wrist, nose, torso_ref: float) -> float:
        return (side_wrist.y - nose.y) / torso_ref

    def _guard_ok(self, side: str, side_wrist, nose, torso_ref: float) -> bool:
        offset = self._guard_offset(side_wrist, nose, torso_ref)
        if abs(offset) > GUARD_HEIGHT_HARD_TOLERANCE:
            return False
        if not self.calibrated:
            return abs(offset) <= GUARD_HEIGHT_HARD_TOLERANCE
        return abs(offset - self._baseline_guard_offset[side]) <= GUARD_HEIGHT_TOLERANCE

    # ---------------------------------------------------------------
    def _update_hand(
        self,
        side: str,
        raw_angle: Optional[float],
        wrist,
        guard_ok_now: bool,
        chin_exposed_now: bool,
        overreach_now: bool,
        torso_ref: float,
        t: float,
    ) -> Optional[dict]:
        """Runs the guard/punching hysteresis state machine for one hand.
        Returns None if the hand wasn't visible this frame (stage untouched)."""
        if raw_angle is None or wrist is None:
            return None

        prev = self.smoothed_angle[side]
        self.smoothed_angle[side] = (
            raw_angle
            if prev is None
            else self.angle_smooth_alpha * raw_angle
            + (1 - self.angle_smooth_alpha) * prev
        )
        smoothed = self.smoothed_angle[side]

        extension_frac = _clip(
            (smoothed - GUARD_ELBOW_ANGLE) / (PUNCH_ELBOW_ANGLE - GUARD_ELBOW_ANGLE)
        )

        outcome: dict[str, Any] = {
            "rep_completed": False,
            "counted": False,
            "rep_duration": None,
            "rep_avg_speed": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "issues": set(),
            "feedback": None,
        }

        # ---- "extend further" partial-rep coaching (pre-transition) ----
        if self.stage[side] == "guard":
            if (
                self._attempt_max_angle[side] is None
                or smoothed > self._attempt_max_angle[side]
            ):
                self._attempt_max_angle[side] = smoothed
            elif (
                not self._attempt_flagged[side]
                and self._attempt_max_angle[side] is not None
                and self._attempt_max_angle[side] - smoothed > PARTIAL_REP_BOUNCE
                and self._attempt_max_angle[side]
                < PUNCH_ELBOW_ANGLE - PARTIAL_REP_MARGIN
                and self._attempt_max_angle[side] - GUARD_ELBOW_ANGLE
                > PARTIAL_REP_MIN_RISE
            ):
                self._attempt_flagged[side] = True
                self.partial_rep_count += 1
                outcome["feedback"] = (
                    f"Extend your {side} jab fully — that one didn't reach "
                    f"full extension to count."
                )
            if smoothed < GUARD_ELBOW_ANGLE + 5:
                self._attempt_max_angle[side] = None
                self._attempt_flagged[side] = False

        # ---- rep-arc accumulator ----
        if self.stage[side] == "guard" and smoothed > PUNCH_ELBOW_ANGLE:
            self.rep_start_time[side] = t
            self._angle_acc[side] = 0.0
        if self.last_angle[side] is not None:
            self._angle_acc[side] += abs(smoothed - self.last_angle[side])

        # ---- state machine ----
        rep_completed = False
        if self.stage[side] == "guard" and smoothed > PUNCH_ELBOW_ANGLE:
            self.stage[side] = "punching"
            self._current_rep_issues[side] = set()
            self._rep_guard_ok_start[side] = guard_ok_now
            self._rep_peak_extension_frac[side] = extension_frac
            self._rep_start_wrist[side] = _Point(wrist.x, wrist.y)
            self._rep_peak_wrist[side] = _Point(wrist.x, wrist.y)
            self._rep_max_line_dev[side] = 0.0
        elif self.stage[side] == "punching" and smoothed < GUARD_ELBOW_ANGLE:
            self.stage[side] = "guard"
            rep_completed = True

        if self.stage[side] == "punching":
            self._current_rep_issues[side].update(
                (["dropped_guard"] if chin_exposed_now else [])
                + (["overreaching"] if overreach_now else [])
            )
            if extension_frac > self._rep_peak_extension_frac[side]:
                self._rep_peak_extension_frac[side] = extension_frac
                self._rep_peak_wrist[side] = _Point(wrist.x, wrist.y)
            start = self._rep_start_wrist[side]
            peak = self._rep_peak_wrist[side]
            if start is not None and peak is not None and _dist(start, peak) > 1e-4:
                dev = _perp_deviation(start, peak, _Point(wrist.x, wrist.y))
                if dev > self._rep_max_line_dev[side]:
                    self._rep_max_line_dev[side] = dev

        if rep_completed:
            rep_duration = (
                (t - self.rep_start_time[side])
                if self.rep_start_time[side] is not None
                else None
            )
            rep_avg_speed = (
                self._angle_acc[side] / rep_duration
                if rep_duration and rep_duration > 0
                else None
            )

            motion_valid = (
                rep_duration is not None
                and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                and self._angle_acc[side] >= MIN_ANGLE_DELTA
            )

            if not motion_valid:
                if rep_duration is not None and rep_duration < MIN_REP_DURATION:
                    outcome["feedback"] = (
                        "Too fast — that one wasn't counted, snap it but stay controlled."
                    )
                elif rep_duration is not None and rep_duration > MAX_REP_DURATION:
                    outcome["feedback"] = (
                        "That one took too long — not counted. Keep it snappy."
                    )
                else:
                    outcome["feedback"] = "Not enough range of motion — not counted."
            elif self._rep_peak_extension_frac[side] < EXTENSION_ROM_MIN:
                outcome["feedback"] = (
                    "Extend your arm fully on the jab — that one was too shallow, not counted."
                )
            elif not self._rep_guard_ok_start[side] or not guard_ok_now:
                # THE anti-misuse gate: a punch that didn't launch from (or
                # return to) a genuine guard never counts as a jab, no
                # matter how far the elbow extended.
                self.not_counted_no_guard += 1
                outcome["feedback"] = (
                    "That didn't count — throw from your guard (fist up, "
                    "protecting your face) and snap it back to guard."
                )
            else:
                self.rep_count += 1
                outcome["counted"] = True
                outcome["rep_completed"] = True
                outcome["rep_duration"] = round(rep_duration, 2)
                outcome["rep_avg_speed"] = (
                    round(rep_avg_speed, 1) if rep_avg_speed else None
                )
                outcome["rep_classification"] = self._classify_tempo(rep_duration)

                issues = set(self._current_rep_issues[side])
                if self._rep_max_line_dev[side] > LOOPING_PUNCH_TOLERANCE:
                    issues.add("looping_punch")
                outcome["issues"] = issues

                if issues:
                    outcome["rep_form_quality"] = "needs_improvement"
                    self.flawed_reps += 1
                    issue_text = ", ".join(i.replace("_", " ") for i in sorted(issues))
                    outcome["feedback"] = (
                        f"Jab {self.rep_count} counted, but watch your form ({issue_text})."
                    )
                else:
                    outcome["rep_form_quality"] = "good"
                    self.good_reps += 1
                    cls = outcome["rep_classification"]
                    if cls in ("good", "fast"):
                        outcome["feedback"] = (
                            f"Clean jab — {cls} tempo ({rep_duration:.2f}s)."
                        )
                    else:
                        outcome["feedback"] = (
                            f"Clean jab, snap it back quicker ({rep_duration:.2f}s)."
                        )

            self.rep_start_time[side] = None
            self._angle_acc[side] = 0.0
            self._current_rep_issues[side] = set()
            self._rep_peak_extension_frac[side] = 0.0
            self._rep_start_wrist[side] = None
            self._rep_peak_wrist[side] = None
            self._rep_max_line_dev[side] = 0.0

        self.last_angle[side] = smoothed
        return outcome

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "left_elbow_angle": None,
            "right_elbow_angle": None,
            "punching_hand": None,
            "phase": "guard",
            "stage": "guard",
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "partial_rep_count": self.partial_rep_count,
            "not_counted_no_guard": self.not_counted_no_guard,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_duration": None,
            "rep_avg_speed": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "calibrated": self.calibrated,
            "guard_ok": False,
            "posture_ok": True,
            "posture_issues": [],
            "posture_messages": [],
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = (
                "No person detected — get into your guard facing the camera."
            )
            return response

        l_sh, r_sh = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_el, r_el = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wr, r_wr = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        nose = landmarks[NOSE]

        left_arm_ok = _visible((l_sh, l_el, l_wr))
        right_arm_ok = _visible((r_sh, r_el, r_wr))
        torso_visible = _visible((l_sh, r_sh, l_hip, r_hip))
        nose_visible = nose is not None and (
            nose.visibility is None or nose.visibility >= MIN_LANDMARK_VISIBILITY
        )

        if not torso_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your shoulders and hips clearly — get your whole "
                "upper body in frame, facing the camera."
            )
            return response

        if not left_arm_ok and not right_arm_ok:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = "Can't see your hands — get your guard in frame."
            return response

        if not nose_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your face — the guard-height check needs your head in frame."
            )
            return response

        mid_shoulder = _midpoint(l_sh, r_sh)
        mid_hip = _midpoint(l_hip, r_hip)
        torso_ref = max(_dist(mid_shoulder, mid_hip), 1e-6)

        framing_message = _framing_feedback(
            l_sh, r_sh, l_hip, r_hip, left_arm_ok or right_arm_ok
        )

        # ---- per-hand guard-height validity (THE anti-misuse gate) ----
        left_guard_ok = left_arm_ok and self._guard_ok("left", l_wr, nose, torso_ref)
        right_guard_ok = right_arm_ok and self._guard_ok("right", r_wr, nose, torso_ref)

        # ---- torso lean (overreach reference) ----
        lean = (mid_shoulder.x - mid_hip.x) / torso_ref

        # ---- calibration (only while both hands rest in guard) ----
        both_guard = self.stage["left"] == "guard" and self.stage["right"] == "guard"
        can_calibrate_left = left_arm_ok
        can_calibrate_right = right_arm_ok
        if (
            both_guard
            and not self.calibrated
            and (can_calibrate_left or can_calibrate_right)
        ):
            if can_calibrate_left:
                self._calib_samples["left"].append(
                    self._guard_offset(l_wr, nose, torso_ref)
                )
            if can_calibrate_right:
                self._calib_samples["right"].append(
                    self._guard_offset(r_wr, nose, torso_ref)
                )
            self._calib_lean_samples.append(lean)
            if (
                len(self._calib_samples["left"]) >= CALIBRATION_FRAMES
                or len(self._calib_samples["right"]) >= CALIBRATION_FRAMES
            ):
                self._finish_calibration()

        # Fallback calibration so we don't stay uncalibrated forever
        if not self.calibrated and elapsed > 8.0:
            for side in ("left", "right"):
                if not self._baseline_guard_offset[side]:
                    self._baseline_guard_offset[side] = 0.0
            if not self._baseline_lean:
                self._baseline_lean = 0.0
            self.calibrated = True

        overreach_now = (
            self.calibrated and abs(lean - self._baseline_lean) > OVERREACH_DELTA
        )

        # ---- per-hand state machines (each hand's "chin exposed" signal
        # comes from the OTHER hand's guard validity while it punches) ----
        left_angle = _angle_deg(l_sh, l_el, l_wr) if left_arm_ok else None
        right_angle = _angle_deg(r_sh, r_el, r_wr) if right_arm_ok else None

        left_chin_exposed = self.calibrated and right_arm_ok and not right_guard_ok
        right_chin_exposed = self.calibrated and left_arm_ok and not left_guard_ok

        left_outcome = self._update_hand(
            "left",
            left_angle,
            l_wr if left_arm_ok else None,
            left_guard_ok,
            left_chin_exposed,
            overreach_now,
            torso_ref,
            t,
        )
        right_outcome = self._update_hand(
            "right",
            right_angle,
            r_wr if right_arm_ok else None,
            right_guard_ok,
            right_chin_exposed,
            overreach_now,
            torso_ref,
            t,
        )

        completed = None
        if left_outcome and left_outcome["rep_completed"]:
            completed = left_outcome
        elif right_outcome and right_outcome["rep_completed"]:
            completed = right_outcome

        punching_hand = None
        if self.stage["left"] == "punching" and self.stage["right"] == "punching":
            punching_hand = "both"
        elif self.stage["left"] == "punching":
            punching_hand = "left"
        elif self.stage["right"] == "punching":
            punching_hand = "right"

        phase = "guard"
        if completed:
            phase = "rep_complete"
        elif punching_hand:
            phase = (
                f"{punching_hand}_punch" if punching_hand != "both" else "both_punching"
            )

        # ---- posture messages (soft, coaching only) ----
        issues: list[str] = []
        messages: list[str] = []
        if left_chin_exposed or right_chin_exposed:
            issues.append("dropped_guard")
            messages.append(
                "Keep your other hand up — protect your chin while you punch."
            )
        if overreach_now:
            issues.append("overreaching")
            messages.append(
                "Extend your arm, not your whole body — don't lunge into the punch."
            )

        feedback = framing_message
        if feedback is None and left_outcome and left_outcome["feedback"]:
            feedback = left_outcome["feedback"]
        if feedback is None and right_outcome and right_outcome["feedback"]:
            feedback = right_outcome["feedback"]
        if completed and completed["feedback"]:
            feedback = completed["feedback"]
        if feedback is None and messages:
            feedback = messages[0]
        if feedback is None and not self.calibrated:
            feedback = "Hold your guard still for a second — calibrating your baseline."
        if feedback is None:
            feedback = "Good guard — snap out your jabs."

        response.update(
            {
                "pose_detected": True,
                "left_elbow_angle": (
                    round(self.smoothed_angle["left"], 1)
                    if self.smoothed_angle["left"] is not None
                    else None
                ),
                "right_elbow_angle": (
                    round(self.smoothed_angle["right"], 1)
                    if self.smoothed_angle["right"] is not None
                    else None
                ),
                "punching_hand": punching_hand,
                "phase": phase,
                "stage": phase,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "partial_rep_count": self.partial_rep_count,
                "not_counted_no_guard": self.not_counted_no_guard,
                "session_complete": self._is_complete(),
                "rep_completed": bool(completed),
                "rep_duration": completed["rep_duration"] if completed else None,
                "rep_avg_speed": completed["rep_avg_speed"] if completed else None,
                "rep_classification": (
                    completed["rep_classification"] if completed else None
                ),
                "rep_form_quality": (
                    completed["rep_form_quality"] if completed else None
                ),
                "calibrated": self.calibrated,
                "guard_ok": bool(
                    (left_arm_ok and left_guard_ok) or (right_arm_ok and right_guard_ok)
                ),
                "posture_ok": len(issues) == 0,
                "posture_issues": issues,
                "posture_messages": messages,
                "framing_ok": framing_message is None,
                "framing_message": framing_message,
                "feedback": feedback,
            }
        )
        return response


class JabSession:
    """Full Muay Thai jab session: one shared pose model + one
    two-handed guard/punch analyzer.

    `target_reps` / `target_sets` / `set_number` are the coach-assigned plan
    for this user, supplied by the caller (the websocket route, from query
    params) — same convention as every other exercise in this codebase.
    The frontend does not decide on its own whether a set/exercise is
    done; `session_complete` (this set's reps are done) and
    `exercise_complete` (the whole assigned plan — all sets — is done) are
    computed here.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = JabAnalyzer(target_reps)
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
            result["session_complete"]
            and self.set_number >= self.target_sets
            and self.analyzer.target_reps is not None
        )
        return result

    def close(self):
        self.engine.close()
