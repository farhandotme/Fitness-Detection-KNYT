"""
Chair Pose (Utkatasana) — hold timing + posture correction.

Design
------
Chair Pose has no reps — it's a single continuous held position, exactly
like `SidePlankAnalyzer` / `PlankHoldAnalyzer`. This does **not** run a rep
state machine. It runs the identical **hold timer that only advances while
the person is verified, frame by frame, to actually be in a valid chair
pose**:

    * The instant form breaks (knees straighten out, torso stands back up,
      hips come back up, or framing goes bad, or the person leaves frame),
      the timer **pauses**. It never silently resets to zero, so
      accumulated `hold_seconds` is monotonic for the lifetime of a set.
      `current_streak_seconds` (time since the last break) is what resets,
      giving live feedback on the *current* attempt without punishing
      total progress.
    * The instant valid chair-pose form resumes, the timer picks back up
      from where it left off.

Form signal
-----------
Three hard-gate angles, all three of which must agree for a frame to count
as "in the pose" — checked with hysteresis (a stricter band to *enter* the
hold, a looser band to *stay* in it) so a borderline angle doesn't flicker
holding/broken every other frame, same convention as the alignment-angle
hysteresis in `side_plank.py`:

  * `knee_angle` = angle(hip, knee, ankle). ~180 = straight legs (standing).
    A valid chair pose bends this to roughly 90-125, widened generously
    (70-160 across the enter/hold hysteresis bands) to tolerate real
    differences in height, leg length, and flexibility.
  * `hip_angle` = angle(shoulder, hip, knee). Confirms the hips are
    actually sitting back/down, not just the knees bending.
  * `torso_angle` = incline of the shoulder->hip line from horizontal.
    ~90 = bolt upright (standing). Chair pose leans the torso forward
    somewhat, so this drops, but should never approach horizontal.

Arm position (overhead or hands-together-at-chest) and knee depth beyond
the "ideal" 90-125 band are graded as **form notes only** — same tier as
knee/head position in the side plank — they never pause the hold timer by
themselves. Per the product requirement, it's far better to keep counting
hold time for a recognizably-real chair pose with imperfect arms than to
pause the timer over a soft signal.
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
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 3


# ---- knee angle (hip-knee-ankle), degrees ----
# Hysteresis: once holding, only drifting outside the *_HOLD band pauses
# the timer; once broken/not-started, the angle has to come back inside
# the stricter *_ENTER band to start it again.
KNEE_ENTER_MIN, KNEE_ENTER_MAX = 80.0, 145.0
KNEE_HOLD_MIN, KNEE_HOLD_MAX = 70.0, 158.0
KNEE_IDEAL_MIN, KNEE_IDEAL_MAX = (
    90.0,
    125.0,
)  # spec's "textbook" range, for form grading only

# ---- hip angle (shoulder-hip-knee), degrees ----
HIP_ENTER_MIN, HIP_ENTER_MAX = 55.0, 150.0
HIP_HOLD_MIN, HIP_HOLD_MAX = 45.0, 160.0

# ---- torso incline from horizontal (shoulder->hip vector), degrees ----
# ~90 = vertical torso (standing). Chair pose leans forward, so the angle
# drops, but should never approach horizontal.
TORSO_ENTER_MIN, TORSO_ENTER_MAX = 35.0, 82.0
TORSO_HOLD_MIN, TORSO_HOLD_MAX = 25.0, 88.0
TORSO_IDEAL_MAX = 78.0  # above this while holding = "not leaning forward enough" note

# ---- soft arm check (form note only, never breaks the hold) ----
ARMS_OVERHEAD_ELBOW_MIN = 140.0
ARMS_TOGETHER_MAX_DIST_RATIO = 0.35

# Per-issue form_score penalty (applied per frame while holding).
MISTAKE_PENALTY = {
    "knees_not_bent_enough": 15,
    "lean_forward_more": 12,
    "arms_position": 10,
}

# form_score is sampled into this rolling window roughly once a second
# (not every frame) so `avg_form_score` reflects the last ~SCORE_HISTORY
# seconds of holding rather than being dominated by frame rate.
SCORE_HISTORY = 30
SCORE_SAMPLE_INTERVAL = 1.0  # seconds

# ---- camera framing ----
FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.97
BBOX_TOO_FAR = 0.12


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


def _torso_incline_deg(mid_shoulder, mid_hip) -> Optional[float]:
    """~90 = vertical torso (standing). Lower = leaning forward."""
    dx = mid_hip.x - mid_shoulder.x
    dy = mid_hip.y - mid_shoulder.y
    if dx == 0 and dy == 0:
        return None
    return math.degrees(math.atan2(abs(dy), max(abs(dx), 1e-9)))


def _bbox_points(points: list) -> list[_Point]:
    return [_Point(p.x, p.y) for p in points if _visible((p,))]


def _framing_feedback(points: list[_Point]) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — step back so your whole body is visible."
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


class ChairPoseAnalyzer:
    """Stateful chair-pose-hold timer + posture checker.

    No `target_reps` here — the coach-assigned target is a duration,
    `target_seconds`. `session_complete` is `hold_seconds >= target_seconds`,
    exactly mirroring `SidePlankAnalyzer` / `PlankHoldAnalyzer`.
    """

    def __init__(self, target_seconds: Optional[int] = None):
        self.target_seconds = target_seconds

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

        self.form_scores: deque[int] = deque(maxlen=SCORE_HISTORY)
        self._last_score_sample_time: Optional[float] = None

    # ---------------------------------------------------------------
    def _is_complete(self) -> bool:
        return (
            self.target_seconds is not None and self.hold_seconds >= self.target_seconds
        )

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "knee_angle": None,
            "hip_angle": None,
            "torso_angle": None,
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
            "arms_ok": True,
            "arms_message": None,
            "posture_ok": True,
            "posture_issues": [],
            "posture_messages": [],
            "framing_ok": True,
            "framing_message": None,
            "form_score": None,
            "avg_form_score": self._avg(self.form_scores),
            "confidence": 0,
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
            response["feedback"] = "No person detected — step into frame."
            response.update(self._progress_fields())
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
        left_leg_ok = _visible((l_hip, l_knee, l_ankle))
        right_leg_ok = _visible((r_hip, r_knee, r_ankle))

        if not torso_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._register_broken_frame()
            response["feedback"] = (
                "Can't see your torso clearly — make sure your shoulders "
                "and hips are both in frame."
            )
            response.update(self._progress_fields())
            return response

        if not left_leg_ok and not right_leg_ok:
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._register_broken_frame()
            response["feedback"] = (
                "Can't see your legs clearly — step back so your hips, "
                "knees, and ankles are all in frame."
            )
            response.update(self._progress_fields())
            return response

        response["pose_detected"] = True

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        shoulder_width = _dist(l_shoulder, r_shoulder)

        # ---- framing (independent of pose form) ----
        bbox_points = _bbox_points(
            [
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
            ]
        )
        framing_message = _framing_feedback(bbox_points)

        # ---- knee angle (hip-knee-ankle), averaged across visible legs ----
        knee_angles = []
        if left_leg_ok:
            knee_angles.append(_angle_deg(l_hip, l_knee, l_ankle))
        if right_leg_ok:
            knee_angles.append(_angle_deg(r_hip, r_knee, r_ankle))
        knee_angle = sum(knee_angles) / len(knee_angles)

        # ---- hip angle (shoulder-hip-knee), averaged across visible sides ----
        hip_angles = []
        if left_leg_ok:
            hip_angles.append(_angle_deg(l_shoulder, l_hip, l_knee))
        if right_leg_ok:
            hip_angles.append(_angle_deg(r_shoulder, r_hip, r_knee))
        hip_angle = sum(hip_angles) / len(hip_angles)

        torso_angle = _torso_incline_deg(mid_shoulder, mid_hip)
        if torso_angle is None:
            torso_angle = 90.0

        # ---- resolve hold-validity this frame (with per-signal hysteresis) ----
        if self.hold_active:
            knee_ok = KNEE_HOLD_MIN <= knee_angle <= KNEE_HOLD_MAX
            hip_ok = HIP_HOLD_MIN <= hip_angle <= HIP_HOLD_MAX
            torso_ok = TORSO_HOLD_MIN <= torso_angle <= TORSO_HOLD_MAX
        else:
            knee_ok = KNEE_ENTER_MIN <= knee_angle <= KNEE_ENTER_MAX
            hip_ok = HIP_ENTER_MIN <= hip_angle <= HIP_ENTER_MAX
            torso_ok = TORSO_ENTER_MIN <= torso_angle <= TORSO_ENTER_MAX

        holding_now = framing_message is None and knee_ok and hip_ok and torso_ok

        # ---- soft arm check — form note only, never breaks the hold ----
        arms_ok = True
        arms_message = None
        left_arm_ok = _visible((l_shoulder, l_elbow, l_wrist))
        right_arm_ok = _visible((r_shoulder, r_elbow, r_wrist))
        if holding_now and (left_arm_ok or right_arm_ok):
            overhead = False
            hands_together = False
            if left_arm_ok and l_wrist.y < l_shoulder.y:
                overhead = (
                    _angle_deg(l_shoulder, l_elbow, l_wrist) >= ARMS_OVERHEAD_ELBOW_MIN
                )
            if not overhead and right_arm_ok and r_wrist.y < r_shoulder.y:
                overhead = (
                    _angle_deg(r_shoulder, r_elbow, r_wrist) >= ARMS_OVERHEAD_ELBOW_MIN
                )
            if not overhead and left_arm_ok and right_arm_ok:
                wrist_dist = _dist(l_wrist, r_wrist)
                near_chest = (l_wrist.y + r_wrist.y) / 2.0 <= mid_shoulder.y + 0.15
                if (
                    near_chest
                    and shoulder_width > 1e-6
                    and wrist_dist / shoulder_width <= ARMS_TOGETHER_MAX_DIST_RATIO
                ):
                    hands_together = True
            arms_ok = overhead or hands_together
            if not arms_ok:
                arms_message = (
                    "Raise your arms — reach straight overhead, or press "
                    "your palms together above your chest."
                )

        # ---- form tiering (only meaningful while holding) ----
        issues: list[str] = []
        messages: list[str] = []
        if holding_now:
            if knee_angle > KNEE_IDEAL_MAX:
                issues.append("knees_not_bent_enough")
                messages.append(
                    "Sit back a little more — bend your knees deeper, like "
                    "lowering into a chair."
                )
            if torso_angle > TORSO_IDEAL_MAX:
                issues.append("lean_forward_more")
                messages.append(
                    "Lean your chest forward slightly to keep your balance "
                    "over your feet."
                )
            if not arms_ok:
                issues.append("arms_position")
                messages.append(arms_message)

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

        # ---- confidence score (joint visibility + framing) ----
        joint_samples = [
            v
            for v in (
                getattr(l_hip, "visibility", None),
                getattr(r_hip, "visibility", None),
                getattr(l_knee, "visibility", None),
                getattr(r_knee, "visibility", None),
                getattr(l_ankle, "visibility", None),
                getattr(r_ankle, "visibility", None),
                getattr(l_shoulder, "visibility", None),
                getattr(r_shoulder, "visibility", None),
            )
            if v is not None
        ]
        joint_confidence = (
            (sum(joint_samples) / len(joint_samples)) if joint_samples else 0.0
        )
        pose_confidence = 1.0 if framing_message is None else 0.6
        overall_confidence = joint_confidence * pose_confidence
        if not arms_ok and holding_now:
            overall_confidence *= 0.9

        # ---- feedback priority: framing > hard break > form flaws > praise ----
        feedback = framing_message
        if feedback is None and not holding_now:
            if knee_angle > KNEE_ENTER_MAX and torso_angle > TORSO_ENTER_MAX:
                feedback = "Lower your hips — bend your knees and sit back like you're sitting in a chair."
            elif knee_angle > KNEE_ENTER_MAX:
                feedback = "Bend your knees more to get into Chair Pose."
            elif torso_angle > TORSO_ENTER_MAX:
                feedback = (
                    "Lean your torso forward slightly as you lower into the pose."
                )
            else:
                feedback = "Get into Chair Pose to start the hold timer."
        if feedback is None and messages:
            feedback = messages[0]
        if feedback is None and target_reached:
            feedback = f"Target reached — {self.target_seconds}s held, great work!"
        if feedback is None and holding_now:
            feedback = "Great Chair Pose — keep holding, chest lifted!"
        if feedback is None:
            feedback = "Get back into Chair Pose to resume the timer."

        response.update(
            {
                "pose_detected": True,
                "knee_angle": round(knee_angle, 1),
                "hip_angle": round(hip_angle, 1),
                "torso_angle": round(torso_angle, 1),
                "hold_state": "holding" if holding_now else "broken",
                "is_holding": holding_now,
                "target_reached": target_reached,
                "hold_quality": hold_quality,
                "arms_ok": arms_ok,
                "arms_message": arms_message,
                "posture_ok": len(issues) == 0,
                "posture_issues": issues,
                "posture_messages": messages,
                "framing_ok": framing_message is None,
                "framing_message": framing_message,
                "form_score": form_score,
                "avg_form_score": self._avg(self.form_scores),
                "confidence": round(max(0.0, min(1.0, overall_confidence)) * 100),
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


class ChairPoseSession:
    """Full Chair Pose session: one shared pose model + one analyzer.

    `target_seconds` / `target_sets` / `set_number` are the coach-assigned
    plan for this user, supplied by the caller (the websocket route, from
    query params) — same convention as `SidePlankSession`. The frontend
    does not decide on its own whether a set/exercise is done;
    `session_complete` and `exercise_complete` are both computed here.
    """

    def __init__(
        self,
        target_seconds: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = ChairPoseAnalyzer(target_seconds)
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
