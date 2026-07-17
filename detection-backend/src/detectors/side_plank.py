"""
Side plank hold timing + posture correction.

Design
------
Mirrors PlankHoldAnalyzer: a continuous timed hold, not discrete reps.
The timer only advances while the person is verified, frame by frame,
to be in a correct side plank:

  * Side-lying position, supported on one forearm + feet (or modified
    knee), body in a straight line from head to feet.
  * Elbow directly under shoulder on the supporting side.
  * Hips lifted (not sagging toward floor, not piked too high).
  * Knees straight (or intentionally bent in a modified variation, but
    then flagged as a modification, not a "full" side plank).

Timer behavior:
  * `hold_seconds` only increases while `is_holding` is true.
  * Any form break (or bad framing, or lost pose) pauses the timer.
  * `current_streak_seconds` resets on each break; `hold_seconds` never
    decreases (monotonic), so progress is never unfairly lost.

Camera framing
---------------
Side plank is judged from a **side-on (profile) view** like the front
plank, but now the body is rotated ~90° so the supporting side is down.
The analyzer picks an `active_side` ("left" or "right") based on which
forearm is clearly on the ground and which side’s landmarks are most
visible. It prefers to keep the current side to avoid flicker.

Form signal
-----------
Evaluated on the currently active (supporting) side:

  * `support_angle` = angle(shoulder, elbow, wrist).
    - Elbow should be under shoulder; forearm roughly vertical.
    - Extreme deviation suggests the elbow is too far forward/back.
  * `alignment_angle` = angle(shoulder, hip, ankle).
    - ~180° is a straight line from shoulder to ankle (ideal side plank).
    - Lower values indicate hip sag or piking.
  * `knee_angle` = angle(hip, knee, ankle).
    - Straight legs: knee angle near 180°.
    - Bent knees: flagged as a modification (not a full side plank).
  * `hip_height` = vertical position of hip relative to shoulder–ankle line.
    - Positive = hip sagging down.
    - Negative = hip piked up.

A broken knee angle (very bent when not in modified mode) or a badly
broken alignment pauses the timer. Shoulder/elbow/wrist issues and mild
hip deviations are treated as form flaws (reduce quality, don’t pause).

Head/neck angle is calibrated per-person from the first stretch of
genuinely good holding, similar to PlankHoldAnalyzer.

A broken knee angle or severely broken alignment pauses the timer
outright. Head position and minor hip deviations are lighter-weight form
notes that reduce `hold_quality` and `form_score` but don’t pause.
"""

import math
from collections import deque
from typing import Any, Optional

from src.engines.poseEngine import (
    LEFT_EAR,
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    LEFT_WRIST,
    PoseEngine,
    RIGHT_EAR,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
    LEFT_ANKLE,
    RIGHT_ANKLE,
)

# -------------------------------------------------------------------------
# Tunable constants
# -------------------------------------------------------------------------

MIN_LANDMARK_VISIBILITY = 0.4

# A side (left or right) is usable as `active_side` only if all of
# shoulder, elbow, wrist, hip, knee, ankle are confidently visible.
SIDE_LANDMARKS = {
    "left": (
        LEFT_SHOULDER,
        LEFT_ELBOW,
        LEFT_WRIST,
        LEFT_HIP,
        LEFT_KNEE,
        LEFT_ANKLE,
    ),
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
    return visible_core >= 2


# ---- support angle (shoulder-elbow-wrist), degrees ----
# Forearm should be roughly vertical, elbow under shoulder.
SUPPORT_ANGLE_IDEAL = 90.0  # elbow roughly 90° (shoulder-elbow-wrist)
SUPPORT_ANGLE_TOLERANCE = 35.0  # +/- this much is still "okay"


# ---- body alignment (shoulder-hip-ankle), degrees ----
ALIGN_BROKEN = 140.0
ALIGN_RESUME = 152.0
ALIGN_IDEAL = 165.0  # at/above this, alignment is "good" tier


# ---- knee angle (hip-knee-ankle), degrees ----
KNEE_BROKEN = 100.0  # below this = essentially collapsed, not a side plank
KNEE_MOD_THRESHOLD = 150.0  # below this = knees bent (modified side plank)
KNEE_IDEAL = 165.0  # at/above this, legs are "good" tier (straight)


# ---- hip deviation (hip offset from shoulder-ankle line) ----
HIP_SAG_THRESHOLD = 0.08  # normalized by body length
HIP_PIKE_THRESHOLD = -0.12  # negative = hip too high


# ---- head/neck angle (ear-shoulder-hip), degrees ----
HEAD_ANGLE_DELTA = 20.0  # allowed drift from personal baseline
CALIBRATION_FRAMES = 15


# Per-issue form_score penalty (applied per frame while holding).
MISTAKE_PENALTY = {
    "hip_sag": 22,
    "hip_pike": 18,
    "knees_bent": 12,  # modified, not a hard break
    "shoulder_elbow_misalign": 14,
    "head_position": 10,
}


# form_score rolling window
SCORE_HISTORY = 30
SCORE_SAMPLE_INTERVAL = 1.0  # seconds


# -------------------------------------------------------------------------
# Camera framing / stance-position thresholds (side plank: body should
# read as roughly horizontal, not standing).
# -------------------------------------------------------------------------
FRAME_EDGE_MARGIN = 0.03
BODY_SPAN_TOO_CLOSE = 0.85
BODY_SPAN_TOO_FAR = 0.35
MAX_STANDING_RATIO = 0.65  # |dy|/|dx| of shoulder->ankle


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
    ang = math.degrees(
        math.atan2(c.y - b.y, c.x - b.x) - math.atan2(a.y - b.y, a.x - b.x)
    )
    ang = abs(ang)
    if ang > 180:
        ang = 360 - ang
    return ang


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _hip_deviation(shoulder, hip, ankle) -> float:
    body_len = max(_dist(shoulder, ankle), 1e-6)
    dx = ankle.x - shoulder.x
    if abs(dx) < 1e-6:
        return 0.0
    frac = (hip.x - shoulder.x) / dx
    line_y_at_hip = shoulder.y + frac * (ankle.y - shoulder.y)
    return (hip.y - line_y_at_hip) / body_len


def _framing_feedback(shoulder, hip, ankle) -> Optional[str]:
    for p in (shoulder, hip, ankle):
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — reposition so your whole body, "
                "head to feet, fits in the shot."
            )

    dx = abs(ankle.x - shoulder.x)
    dy = abs(ankle.y - shoulder.y)
    if dx < 1e-6 or (dy / dx) > MAX_STANDING_RATIO:
        return (
            "Turn sideways to the camera and get into side plank position "
            "— I need a side-on view to check your alignment."
        )

    body_span = math.hypot(dx, dy)
    if body_span > BODY_SPAN_TOO_CLOSE:
        return "You're too close to the camera — step back until your whole body fits in frame."
    if body_span < BODY_SPAN_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class SidePlankHoldAnalyzer:
    """Stateful side-plank hold timer + posture checker."""

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

        # Personal head/neck baseline
        self._calib_samples: list[float] = []
        self.calibrated = False
        self._baseline_head_angle = 180.0

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

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "active_side": self.active_side,
            "support_angle": None,
            "alignment_angle": None,
            "knee_angle": None,
            "head_angle": None,
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
                "No person detected — get into frame, sideways to the camera."
            )
            response.update(self._progress_fields())
            return response

        self.active_side = self._pick_active_side(landmarks)
        if self.active_side is None:
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._register_broken_frame()
            response["feedback"] = (
                "Can't see your body clearly from either side — step back and "
                "turn sideways to the camera."
            )
            response.update(self._progress_fields())
            return response

        s_idx, e_idx, w_idx, h_idx, k_idx, a_idx = SIDE_LANDMARKS[self.active_side]
        shoulder = landmarks[s_idx]
        elbow = landmarks[e_idx]
        wrist = landmarks[w_idx]
        hip = landmarks[h_idx]
        knee = landmarks[k_idx]
        ankle = landmarks[a_idx]
        ear = landmarks[LEFT_EAR if self.active_side == "left" else RIGHT_EAR]
        ear_ok = (
            _visible((ear,)) and ear.visibility is not None and ear.visibility > 0.3
        )

        support_angle = _angle_deg(shoulder, elbow, wrist)
        alignment_angle = _angle_deg(shoulder, hip, ankle)
        knee_angle = _angle_deg(hip, knee, ankle)
        head_angle = _angle_deg(ear, shoulder, hip) if ear_ok else None

        framing_message = _framing_feedback(shoulder, hip, ankle)

        # ---- resolve hold-validity this frame (with hysteresis) ----
        knee_collapsed = knee_angle < KNEE_BROKEN

        if self.hold_active:
            align_broken = alignment_angle < ALIGN_BROKEN
        else:
            align_broken = alignment_angle < ALIGN_RESUME

        support_ok = abs(support_angle - SUPPORT_ANGLE_IDEAL) <= SUPPORT_ANGLE_TOLERANCE

        holding_now = (
            framing_message is None
            and not align_broken
            and not knee_collapsed
            and support_ok
        )

        # ---- form tiering (only meaningful while holding) ----
        issues: list[str] = []
        messages: list[str] = []
        if holding_now:
            # Hip height / alignment quality
            if alignment_angle < ALIGN_IDEAL:
                deviation = _hip_deviation(shoulder, hip, ankle)
                if deviation > HIP_SAG_THRESHOLD:
                    issues.append("hip_sag")
                    messages.append(
                        "Lift your hips — you're sagging, squeeze your core and glutes."
                    )
                elif deviation < HIP_PIKE_THRESHOLD:
                    issues.append("hip_pike")
                    messages.append(
                        "Lower your hips slightly — you're piking up too high, flatten out."
                    )

            # Knees bent vs straight
            if knee_angle < KNEE_IDEAL:
                issues.append("knees_bent")
                messages.append(
                    "Straighten your legs for a full side plank (or keep them bent if using a modified variation)."
                )

            # Shoulder-elbow-wrist alignment
            if not support_ok:
                issues.append("shoulder_elbow_misalign")
                messages.append(
                    "Keep your elbow directly under your shoulder and forearm vertical."
                )

            # Head/neck
            if self.calibrated and head_angle is not None:
                if abs(head_angle - self._baseline_head_angle) > HEAD_ANGLE_DELTA:
                    issues.append("head_position")
                    messages.append(
                        "Keep your neck neutral — don't let your head drop or crane up."
                    )

            # Calibrate head baseline from clean holds
            if (
                not self.calibrated
                and head_angle is not None
                and "hip_sag" not in issues
                and "hip_pike" not in issues
                and "knees_bent" not in issues
                and "shoulder_elbow_misalign" not in issues
            ):
                self._calib_samples.append(head_angle)
                if len(self._calib_samples) >= CALIBRATION_FRAMES:
                    self._finish_calibration()

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

        # ---- feedback priority: framing > hard breaks > form flaws > praise ----
        feedback = framing_message
        if feedback is None and knee_collapsed:
            feedback = "Get your hips up and legs straight — that's not a side plank position yet."
        if feedback is None and align_broken:
            feedback = (
                "That's not a side plank position yet — get your body in a straight "
                "line from shoulder to ankle."
            )
        if feedback is None and not support_ok:
            feedback = (
                "Keep your elbow directly under your shoulder and forearm vertical."
            )
        if feedback is None and messages:
            feedback = messages[0]
        if feedback is None and not self.calibrated and holding_now:
            feedback = "Great form — hold it, calibrating your neutral posture."
        if feedback is None and target_reached:
            feedback = f"Target reached — {self.target_seconds}s held, nice work!"
        if feedback is None and holding_now:
            feedback = "Great side plank — keep holding!"
        if feedback is None:
            feedback = "Get back into side plank position to resume the timer."

        response.update(
            {
                "pose_detected": True,
                "active_side": self.active_side,
                "support_angle": round(support_angle, 1),
                "alignment_angle": round(alignment_angle, 1),
                "knee_angle": round(knee_angle, 1),
                "head_angle": round(head_angle, 1) if head_angle is not None else None,
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


class SidePlankHoldSession:
    """Full side-plank hold session: one shared pose model + one analyzer."""

    def __init__(
        self,
        target_seconds: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = SidePlankHoldAnalyzer(target_seconds)
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
