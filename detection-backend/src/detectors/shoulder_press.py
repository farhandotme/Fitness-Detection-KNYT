"""
Overhead shoulder-press rep counting + full-body form correction.

Design
------
`ShoulderPressAnalyzer` is a pure, stateful, whole-body analyzer, structured
the same way as the other detectors in this package (`squat.py`,
`high_knees.py`, `mountain_climber.py`) — it knows nothing about the camera
or the MediaPipe model; `ShoulderPressSession` owns a single shared
`PoseEngine` and feeds it landmarks every frame.

Rep counting
------------
Driven by the average shoulder-elbow-wrist ("elbow") angle across both arms
(falling back to whichever single arm is visible). The rest position is the
"rack" — elbows bent near shoulder height (`RACK_ANGLE`); a rep is a full
press to lockout overhead (`LOCKOUT_ANGLE`) and back down to the rack. This
mirrors `high_knees.py`'s "start grounded, drive up, return completes the
rep" state machine, just applied to a bilateral (both-arms-together) press
instead of an alternating-leg movement.

Form tracking — this is the point of the exercise, so it's checked hard
------------------------------------------------------------------------
Four independent issues are tracked every single frame, each with its own
plain-language correction, and each contributes to a per-rep `form_score`:

  1. **`poor_posture`** — torso lean/arch. Overhead pressing invites
     leaning back or arching the lower back to help drive the weight up
     instead of pressing strictly vertically. Measured the same way as
     `high_knees.py`/`lunge.py`: the shoulder-hip line's angle off vertical,
     compared against a personal baseline captured at rest (rack position),
     so it adapts to each person's natural stance/camera angle instead of
     assuming one "correct" absolute lean.
  2. **`wrist_not_stacked`** — the wrist should stay roughly stacked over
     the elbow (a vertical forearm) through the whole press, not drift
     forward/back, which is a common wrist-strain cause. Measured as the
     wrist's horizontal offset from the elbow, normalized by shoulder
     width.
  3. **`elbows_flared`** — at the rack (bottom), the elbows shouldn't flare
     out dramatically wider than the shoulders before driving up. Measured
     as elbow-to-elbow width vs shoulder width.
  4. **`asymmetric_press`** — both arms should press together. Measured as
     the max gap between the left and right elbow angle during the "up"
     phase of a rep; one arm lagging/leading the other by a wide margin
     means the bar/weight is tilting.

A rep still counts the moment it meets range-of-motion and tempo
requirements even with a form issue flagged (a flawed rep still counts —
"perfect or nothing" is discouraging), tagged `rep_form_quality:
"needs_improvement"`, with `posture_issues`/`posture_messages` telling the
user exactly what to fix on the next rep. A press that never reaches
lockout is tracked as a "half rep" (same bounce-detection heuristic as
`high_knees.py`) instead of being silently dropped.
"""

import math
from collections import deque
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_SHOULDER,
    LEFT_WRIST,
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


# Elbow angle (shoulder-elbow-wrist), degrees. Rack position (bottom, elbows
# bent near shoulder height) => angle near 90. Full overhead lockout
# (arms extended straight up) => angle near 170-180.
RACK_ANGLE = 95.0
LOCKOUT_ANGLE = 160.0

PRESS_RAISED_THRESH = 99.5  # press_score at/above this = genuinely locked out
PRESS_GROUNDED_THRESH = 15.0
MIN_ANGLE_DELTA = 35.0  # total travel required for a rep to "count"
MIN_REP_DURATION = 0.25  # seconds — faster than this = uncontrolled/momentum
MAX_REP_DURATION = 6.0  # seconds — slower than this = probably a pause

CALIBRATION_FRAMES = 15

# "Half rep" partial-rep heuristic (same family as high_knees.py).
PARTIAL_REP_MARGIN = 10.0
PARTIAL_REP_MIN_RISE = 18.0
PARTIAL_REP_BOUNCE = 7.0

# ---- form-correction thresholds ----
TORSO_LEAN_DELTA_DEG = 14.0  # leaning/arching back off your calibrated baseline
WRIST_OFFSET_RATIO = 0.30  # |wrist.x - elbow.x| / shoulder_width
ELBOW_FLARE_RATIO = 1.9  # elbow-to-elbow width / shoulder width, checked at rack
ASYMMETRY_DEG = 20.0  # max allowed gap between left/right elbow angle mid-press

PACE_SLOW_RPM = 15.0
PACE_FAST_RPM = 55.0

MISTAKE_PENALTY = {
    "poor_posture": 15,
    "wrist_not_stacked": 10,
    "elbows_flared": 10,
    "asymmetric_press": 15,
}

SCORE_HISTORY = 10
RPM_WINDOW = 6

# -------------------------------------------------------------------------
# Camera framing thresholds
# -------------------------------------------------------------------------
FRAME_EDGE_MARGIN = 0.03
TORSO_SPAN_TOO_CLOSE = 0.55
TORSO_SPAN_TOO_FAR = 0.10
CENTER_X_TOLERANCE = 0.28


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


def _clip(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _press_score(angle: float) -> float:
    """Map an elbow angle to a 0-100 'how close to full lockout' score."""
    return 100.0 * _clip((angle - RACK_ANGLE) / (LOCKOUT_ANGLE - RACK_ANGLE))


def _framing_feedback(l_shoulder, r_shoulder, l_hip, r_hip) -> Optional[str]:
    mid_shoulder = _midpoint(l_shoulder, r_shoulder)
    mid_hip = _midpoint(l_hip, r_hip)

    for p in (l_shoulder, r_shoulder, l_hip, r_hip):
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
        ):
            return "You're partly out of frame — center yourself with space above your head."

    torso_span = abs(mid_hip.y - mid_shoulder.y)
    if torso_span > TORSO_SPAN_TOO_CLOSE:
        return "You're too close to the camera — step back so your arms fit fully overhead in frame."
    if torso_span < TORSO_SPAN_TOO_FAR:
        return "You're too far from the camera — move a bit closer for accurate tracking."

    if abs(mid_hip.x - 0.5) > CENTER_X_TOLERANCE:
        side = "left" if mid_hip.x < 0.5 else "right"
        return f"Move to the center of frame — you're too far to the {side}."

    return None


class ShoulderPressAnalyzer:
    """Stateful overhead-press rep counter + posture/wrist/flare/symmetry checker."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.stage = "down"  # "down" = rack (rest), "up" = locked out overhead
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.partial_rep_count = 0

        self.smoothed_press: Optional[float] = None
        self.last_press: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None
        self.press_smooth_alpha = 0.5

        self.rep_start_time: Optional[float] = None
        self._press_acc = 0.0

        self.session_start_time: Optional[float] = None

        # "Half rep" partial-rep detection (tracked while stage == "down")
        self._attempt_peak_press: Optional[float] = None
        self._attempt_flagged = False

        # Personal posture baseline, captured at rest (rack position).
        self._calib_samples: list[float] = []
        self.calibrated = False
        self._baseline_torso_lean = 0.0

        self._current_rep_issues: set[str] = set()
        self._rep_max_torso_lean_delta = 0.0
        self._rep_max_wrist_offset = 0.0
        self._rep_max_asymmetry = 0.0
        self._rep_elbow_flare_at_rack = False

        self.form_scores: deque = deque(maxlen=SCORE_HISTORY)
        self._rep_complete_times: deque = deque(maxlen=RPM_WINDOW)

    # ---------------------------------------------------------------
    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _finish_calibration(self):
        n = len(self._calib_samples)
        self._baseline_torso_lean = sum(self._calib_samples) / n
        self.calibrated = True

    @staticmethod
    def _avg(d: deque) -> Optional[float]:
        return round(sum(d) / len(d), 1) if d else None

    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration < 0.5:
            return "fast"
        if duration < 1.3:
            return "good"
        if duration < 2.5:
            return "slow"
        return "too_slow"

    def _classify_pace(self, rpm: Optional[float]) -> Optional[str]:
        if rpm is None:
            return None
        if rpm < PACE_SLOW_RPM:
            return "slow"
        if rpm > PACE_FAST_RPM:
            return "fast"
        return "steady"

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
            "angle": None,
            "press": None,
            "smoothed_press": None,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "partial_rep_count": self.partial_rep_count,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_duration": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "calibrated": self.calibrated,
            "posture_ok": True,
            "posture_issues": [],
            "posture_messages": [],
            "framing_ok": True,
            "framing_message": None,
            "form_score": None,
            "avg_form_score": self._avg(self.form_scores),
            "reps_per_minute": None,
            "pace_classification": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = "No person detected — step into frame."
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]

        left_arm_ok = _visible((l_shoulder, l_elbow, l_wrist))
        right_arm_ok = _visible((r_shoulder, r_elbow, r_wrist))
        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))

        if not left_arm_ok and not right_arm_ok:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your arms clearly — adjust the camera so your "
                "shoulders, elbows, and wrists are all in frame, arms overhead."
            )
            return response

        if not torso_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your torso — make sure your shoulders and hips "
                "are both in frame."
            )
            return response

        response["pose_detected"] = True

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        shoulder_width = max(_dist(l_shoulder, r_shoulder), 1e-6)

        # ---- camera framing (every frame) ----
        framing_message = _framing_feedback(l_shoulder, r_shoulder, l_hip, r_hip)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        # ---- elbow angle per arm (drives rep counting) ----
        left_angle = _angle_deg(l_shoulder, l_elbow, l_wrist) if left_arm_ok else None
        right_angle = (
            _angle_deg(r_shoulder, r_elbow, r_wrist) if right_arm_ok else None
        )
        response["left_elbow_angle"] = (
            round(left_angle, 1) if left_angle is not None else None
        )
        response["right_elbow_angle"] = (
            round(right_angle, 1) if right_angle is not None else None
        )

        angles = [a for a in (left_angle, right_angle) if a is not None]
        raw_angle = sum(angles) / len(angles)
        response["angle"] = round(raw_angle, 1)

        arm_gap = (
            abs(left_angle - right_angle)
            if left_angle is not None and right_angle is not None
            else 0.0
        )

        raw_press = _press_score(raw_angle)
        if self.smoothed_press is None:
            self.smoothed_press = raw_press
        else:
            self.smoothed_press = (
                self.press_smooth_alpha * raw_press
                + (1 - self.press_smooth_alpha) * self.smoothed_press
            )

        # ---- torso lean/arch + calibration (captured while racked) ----
        vertical_ref = _Point(mid_hip.x, mid_hip.y - 1.0)
        torso_lean = _angle_deg(vertical_ref, mid_hip, mid_shoulder)

        if self.stage == "down" and not self.calibrated:
            self._calib_samples.append(torso_lean)
            if len(self._calib_samples) >= CALIBRATION_FRAMES:
                self._finish_calibration()

        lean_delta = (
            abs(torso_lean - self._baseline_torso_lean) if self.calibrated else 0.0
        )

        # ---- wrist-stacked-over-elbow check (every frame) ----
        wrist_offsets = []
        if left_arm_ok:
            wrist_offsets.append(abs(l_wrist.x - l_elbow.x) / shoulder_width)
        if right_arm_ok:
            wrist_offsets.append(abs(r_wrist.x - r_elbow.x) / shoulder_width)
        wrist_offset = max(wrist_offsets) if wrist_offsets else 0.0

        # ---- elbow-flare check (only meaningful near the rack) ----
        elbow_width = (
            _dist(l_elbow, r_elbow) if left_arm_ok and right_arm_ok else None
        )
        flare_ratio = (
            elbow_width / shoulder_width if elbow_width is not None else None
        )

        rep_completed = False

        if self.stage == "down":
            if (
                self._attempt_peak_press is None
                or self.smoothed_press > self._attempt_peak_press
            ):
                self._attempt_peak_press = self.smoothed_press
            elif (
                not self._attempt_flagged
                and self._attempt_peak_press is not None
                and self._attempt_peak_press - self.smoothed_press > PARTIAL_REP_BOUNCE
                and self._attempt_peak_press < PRESS_RAISED_THRESH - PARTIAL_REP_MARGIN
                and self._attempt_peak_press - PRESS_GROUNDED_THRESH
                > PARTIAL_REP_MIN_RISE
            ):
                self._attempt_flagged = True
                self.partial_rep_count += 1
                response["feedback"] = (
                    f"Half rep — only got to {self._attempt_peak_press:.0f}/100 of "
                    "full lockout, press all the way overhead."
                )

            if self.smoothed_press < PRESS_GROUNDED_THRESH - 3:
                self._attempt_peak_press = None
                self._attempt_flagged = False

            if flare_ratio is not None and flare_ratio > ELBOW_FLARE_RATIO:
                self._rep_elbow_flare_at_rack = True

            if self.smoothed_press >= PRESS_RAISED_THRESH:
                self.stage = "up"
                self.rep_start_time = t
                self._press_acc = 0.0
                self._current_rep_issues = set()
                self._rep_max_torso_lean_delta = lean_delta
                self._rep_max_wrist_offset = wrist_offset
                self._rep_max_asymmetry = arm_gap

        else:  # self.stage == "up"
            self._rep_max_torso_lean_delta = max(
                self._rep_max_torso_lean_delta, lean_delta
            )
            self._rep_max_wrist_offset = max(self._rep_max_wrist_offset, wrist_offset)
            self._rep_max_asymmetry = max(self._rep_max_asymmetry, arm_gap)

            if self.last_press is not None:
                self._press_acc += abs(self.smoothed_press - self.last_press)

            if self.smoothed_press <= PRESS_GROUNDED_THRESH:
                self.stage = "down"
                rep_completed = True

        response["press"] = round(raw_press, 1)
        response["smoothed_press"] = round(self.smoothed_press, 1)

        rep_duration = rep_class = rep_form_quality = None
        form_score = None
        feedback = response.get("feedback") or framing_message

        if rep_completed:
            rep_duration = (
                (t - self.rep_start_time) if self.rep_start_time is not None else None
            )
            valid = (
                rep_duration is not None
                and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                and self._press_acc >= MIN_ANGLE_DELTA
            )

            if valid:
                self.rep_count += 1
                rep_class = self._classify_tempo(rep_duration)

                if self._rep_max_torso_lean_delta > TORSO_LEAN_DELTA_DEG:
                    self._current_rep_issues.add("poor_posture")
                if self._rep_max_wrist_offset > WRIST_OFFSET_RATIO:
                    self._current_rep_issues.add("wrist_not_stacked")
                if self._rep_elbow_flare_at_rack:
                    self._current_rep_issues.add("elbows_flared")
                if self._rep_max_asymmetry > ASYMMETRY_DEG:
                    self._current_rep_issues.add("asymmetric_press")

                form_score = 100
                for issue in self._current_rep_issues:
                    form_score -= MISTAKE_PENALTY.get(issue, 10)
                form_score = max(0, form_score)
                self.form_scores.append(form_score)
                self._rep_complete_times.append(t)

                issue_messages = {
                    "poor_posture": "Keep your torso upright — don't lean back or arch to press the weight up.",
                    "wrist_not_stacked": "Stack your wrists over your elbows — don't let them drift forward or back.",
                    "elbows_flared": "Bring your elbows in closer to your body at the bottom, not flared way out wide.",
                    "asymmetric_press": "Press both arms together evenly — one side is leading the other.",
                }
                messages = [issue_messages[i] for i in sorted(self._current_rep_issues)]

                if self._current_rep_issues:
                    rep_form_quality = "needs_improvement"
                    self.flawed_reps += 1
                    feedback = (
                        f"Rep {self.rep_count} counted, but watch your form: "
                        + " ".join(messages)
                    )
                else:
                    rep_form_quality = "good"
                    self.good_reps += 1
                    feedback = f"Clean overhead press — {rep_class} tempo, full lockout."

                response["posture_ok"] = len(self._current_rep_issues) == 0
                response["posture_issues"] = sorted(self._current_rep_issues)
                response["posture_messages"] = messages
            else:
                rep_completed = False
                if rep_duration is not None and rep_duration < MIN_REP_DURATION:
                    feedback = "Too fast — that one wasn't counted, control the movement."
                elif rep_duration is not None and rep_duration > MAX_REP_DURATION:
                    feedback = "That rep took too long — not counted. Keep moving."
                else:
                    feedback = "Not enough press range — not counted."

            self.rep_start_time = None
            self._press_acc = 0.0
            self._current_rep_issues = set()
            self._rep_max_torso_lean_delta = 0.0
            self._rep_max_wrist_offset = 0.0
            self._rep_max_asymmetry = 0.0
            self._rep_elbow_flare_at_rack = False
        else:
            # Live, every-frame posture feedback even mid-rep, so the user
            # gets corrected in real time instead of only after the fact.
            live_issues = []
            live_messages = []
            if lean_delta > TORSO_LEAN_DELTA_DEG:
                live_issues.append("poor_posture")
                live_messages.append(
                    "Keep your torso upright — don't lean back or arch to press the weight up."
                )
            if wrist_offset > WRIST_OFFSET_RATIO:
                live_issues.append("wrist_not_stacked")
                live_messages.append(
                    "Stack your wrists over your elbows — don't let them drift forward or back."
                )
            if (
                self.stage == "down"
                and flare_ratio is not None
                and flare_ratio > ELBOW_FLARE_RATIO
            ):
                live_issues.append("elbows_flared")
                live_messages.append(
                    "Bring your elbows in closer to your body before pressing."
                )
            response["posture_ok"] = len(live_issues) == 0
            response["posture_issues"] = live_issues
            response["posture_messages"] = live_messages
            if feedback is None and live_messages:
                feedback = live_messages[0]

        self.last_press = self.smoothed_press
        self.last_timestamp_s = t

        reps_per_minute = None
        if len(self._rep_complete_times) >= 2:
            span = self._rep_complete_times[-1] - self._rep_complete_times[0]
            if span > 0:
                reps_per_minute = round(
                    (len(self._rep_complete_times) - 1) / span * 60.0, 1
                )
        pace_classification = self._classify_pace(reps_per_minute)

        if feedback is None and not self.calibrated:
            feedback = (
                "Hold the rack position (elbows bent, hands at shoulder "
                "height) for a second — calibrating your posture."
            )
        if feedback is None:
            feedback = "Good position — press straight up to full lockout."

        response.update(
            {
                "rep_completed": rep_completed,
                "rep_duration": round(rep_duration, 2) if rep_duration is not None else None,
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "form_score": form_score,
                "avg_form_score": self._avg(self.form_scores),
                "reps_per_minute": reps_per_minute,
                "pace_classification": pace_classification,
                "session_complete": self._is_complete(),
                "stage": self.stage,
                "feedback": feedback,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "partial_rep_count": self.partial_rep_count,
            }
        )
        return response


class ShoulderPressSession:
    """Full shoulder-press session: one shared pose model + one analyzer.

    `target_reps` / `target_sets` / `set_number` are the coach-assigned plan
    for this user, supplied by the caller (the websocket route, from query
    params) — same convention as the other exercises. The frontend does not
    decide on its own whether a set/exercise is done; `session_complete`
    (this set's reps are done) and `exercise_complete` (the whole assigned
    plan — all sets — is done) are computed here.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = ShoulderPressAnalyzer(target_reps)
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
