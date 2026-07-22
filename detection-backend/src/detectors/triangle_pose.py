"""
Triangle Pose (Trikonasana) hold timing + posture correction — both sides.

Design
------
Same family as `SidePlankAnalyzer` / `PlankHoldAnalyzer`: there are no reps
here, it's a continuous timed hold, so the **hold timer only advances while
the person is verified, frame by frame, to actually be in a correct
Triangle Pose**. The instant the position breaks (or framing goes bad, or
the person leaves frame), the timer pauses — `hold_seconds` never resets,
it just stops accumulating until good form resumes.

Why this needs its own geometry (not reused from push-up/plank/side-plank)
----------------------------------------------------------------------------
Every other hold/rep exercise in this backend is judged from a side-on
(profile) camera view. Triangle Pose is a **standing, wide-legged lateral
bend** — it is judged from a front-on view instead, because that's the
only angle that actually shows the pose's defining shape: feet spread
wide, front leg dead straight, torso hinged sideways over the front leg
(not forward, not twisted), one arm reaching down toward the front shin,
the other arm reaching straight up, both arms forming one open vertical
line. None of the existing straight-body-line or elbow-bend heuristics
apply here.

Hard gate — ALL of the following must hold simultaneously for the frame to
count as a verified Triangle Pose (this is an AND, not a fuzzy vote,
specifically so a genuinely wrong position — e.g. Warrior II, which shares
the wide stance but bends the front *knee* instead of the torso — can
never slip through and start the timer):

    1. `front_knee_angle` (hip-knee-ankle, on whichever leg the torso is
       leaning over) is close to straight. This is the single biggest
       differentiator from Warrior II / a lunge.
    2. `torso_tilt_angle` (angle of the hip->shoulder line from vertical)
       is a genuine lateral bend, in the *same direction* as the front
       leg — rules out just standing up straight, and rules out leaning
       away from the front leg.
    3. `stance_ratio` (ankle-to-ankle distance / shoulder width) shows a
       wide-legged stance.
    4. Both arms are extended (elbow angle near straight) with the
       front-side wrist reaching down toward hip height or below, and the
       back-side wrist raised clearly above the shoulder — the open
       "vertical line" arm position.

Which side (left leg forward vs. right leg forward) is currently being
held is auto-detected every frame from which ankle the torso is actually
leaning over (`_pick_front_side`), with light hysteresis so it doesn't
flicker mid-hold. If the session was given an `expected_side` (set by
`TrianglePoseSession` from which set number this connection is for — set
1 = left, set 2 = right, alternating), the timer additionally requires the
detected side to match. This is what makes "for both sides" actually
correct instead of trivially satisfiable by doing the same side twice.

Softer form notes (flag the hold's quality but never pause the timer):
front knee not perfectly straight, back knee bent, shallow torso bend,
arms not stacked in a clean vertical line.
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


# ---- front (weight-bearing) knee angle, degrees — hysteresis band ----
FRONT_KNEE_BROKEN = 145.0  # once holding, drop below this breaks the hold
FRONT_KNEE_RESUME = 155.0  # once broken, must climb back above this to resume
FRONT_KNEE_IDEAL = 165.0  # at/above this, front-leg straightness is "good" tier

# ---- back knee (soft flaw only, not a hard gate) ----
BACK_KNEE_IDEAL_MIN = 150.0

# ---- torso lateral-tilt angle from vertical, degrees — hysteresis band ----
TORSO_TILT_BROKEN_MIN = 15.0  # once holding, straightening below this breaks
TORSO_TILT_RESUME_MIN = 22.0  # once broken, must lean back past this to resume
TORSO_TILT_HARD_MAX = 100.0  # collapsed past horizontal — always invalid
TORSO_TILT_IDEAL_MIN = 35.0  # soft flaw ("go deeper") below this

# ---- stance width: ankle-to-ankle distance / shoulder width ----
STANCE_MIN_RATIO = 1.3

# ---- arms: elbow angle (shoulder-elbow-wrist) + wrist placement ----
ARM_EXTENDED_MIN_DEG = 140.0
UPPER_ARM_RAISE_MIN_RATIO = 0.15  # back wrist above shoulder by this much of torso_length
LOWER_ARM_REACH_SLACK_RATIO = 0.05  # front wrist allowed to sit slightly above hip line
ARM_STACK_IDEAL_MAX_RATIO = 0.35  # soft flaw: |wrist dx| / shoulder_width beyond this

STABLE_FRONT_SIDE_MARGIN_RATIO = 0.15  # hysteresis margin (x shoulder_width) before flipping active leg

# Form-quality scoring
MISTAKE_PENALTY = {
    "front_knee_bent": 20,
    "back_knee_bent": 10,
    "shallow_bend": 15,
    "arms_not_stacked": 12,
}
SCORE_HISTORY = 30
SCORE_SAMPLE_INTERVAL = 1.0

# Camera framing (front-on, standing, arms spread — tall + wide bbox)
FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.95
BBOX_TOO_FAR_HEIGHT = 0.35


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


def _framing_feedback(points: list[_Point]) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — step back so your whole body, "
                "head to feet with arms spread, fits in the shot."
            )

    if len(points) < 4:
        return None

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "You're too close to the camera — step back for the full pose to be visible."
    # Triangle Pose is a wide, laterally-hinged stance — its bbox is
    # naturally wide and short (unlike an upright pose), so height alone
    # is not a reliable "too far" signal. Only flag "too far" if neither
    # dimension shows the person filling a reasonable share of the frame.
    if height < BBOX_TOO_FAR_HEIGHT and width < BBOX_TOO_FAR_HEIGHT:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class TrianglePoseAnalyzer:
    """Stateful Triangle Pose hold timer + posture checker.

    `target_seconds` is the coach-assigned hold duration for THIS side.
    `expected_side` ("left" / "right" / None) is which leg is supposed to
    be forward for this set — pass None to accept whichever side the user
    actually holds (no enforcement).
    """

    def __init__(
        self,
        target_seconds: Optional[int] = None,
        expected_side: Optional[str] = None,
    ):
        self.target_seconds = target_seconds
        self.expected_side = expected_side

        self.front_side: Optional[str] = None

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

        self.form_scores: deque[int] = deque(maxlen=SCORE_HISTORY)
        self._last_score_sample_time: Optional[float] = None

    # ---------------------------------------------------------------
    def _is_complete(self) -> bool:
        return (
            self.target_seconds is not None
            and self.hold_seconds >= self.target_seconds
        )

    def _pick_front_side(self, mid_shoulder, l_ankle, r_ankle, shoulder_width) -> str:
        d_left = abs(mid_shoulder.x - l_ankle.x)
        d_right = abs(mid_shoulder.x - r_ankle.x)
        candidate = "left" if d_left < d_right else "right"

        if self.front_side is None:
            return candidate

        margin = STABLE_FRONT_SIDE_MARGIN_RATIO * max(shoulder_width, 1e-6)
        prev_d = d_left if self.front_side == "left" else d_right
        other_d = d_right if self.front_side == "left" else d_left
        if other_d + margin < prev_d:
            return candidate
        return self.front_side

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "active_side": self.front_side,
            "expected_side": self.expected_side,
            "side_matches": True,
            "front_knee_angle": None,
            "back_knee_angle": None,
            "torso_tilt_angle": None,
            "stance_ratio": None,
            "front_elbow_angle": None,
            "back_elbow_angle": None,
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
            response["feedback"] = (
                "No person detected — step into frame, facing the camera."
            )
            response.update(self._progress_fields())
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        required = (
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
        if not _visible(required):
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._register_broken_frame()
            response["feedback"] = (
                "Can't see your full body clearly — step back so both arms, "
                "both legs, and your torso are all visible."
            )
            response.update(self._progress_fields())
            return response

        response["pose_detected"] = True

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        shoulder_width = max(_dist(l_shoulder, r_shoulder), 1e-6)
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)
        stance_width = _dist(l_ankle, r_ankle)
        stance_ratio = stance_width / shoulder_width

        framing_points = [
            _Point(p.x, p.y)
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
        ]
        framing_message = _framing_feedback(framing_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        self.front_side = self._pick_front_side(
            mid_shoulder, l_ankle, r_ankle, shoulder_width
        )
        response["active_side"] = self.front_side
        side_matches = (
            self.expected_side is None or self.front_side == self.expected_side
        )
        response["side_matches"] = side_matches

        is_left = self.front_side == "left"
        front_hip, front_knee, front_ankle = (
            (l_hip, l_knee, l_ankle) if is_left else (r_hip, r_knee, r_ankle)
        )
        back_hip, back_knee, back_ankle = (
            (r_hip, r_knee, r_ankle) if is_left else (l_hip, l_knee, l_ankle)
        )
        front_shoulder, front_elbow, front_wrist = (
            (l_shoulder, l_elbow, l_wrist) if is_left else (r_shoulder, r_elbow, r_wrist)
        )
        back_shoulder, back_elbow, back_wrist = (
            (r_shoulder, r_elbow, r_wrist) if is_left else (l_shoulder, l_elbow, l_wrist)
        )

        front_knee_angle = _angle_deg(front_hip, front_knee, front_ankle)
        back_knee_angle = _angle_deg(back_hip, back_knee, back_ankle)
        front_elbow_angle = _angle_deg(front_shoulder, front_elbow, front_wrist)
        back_elbow_angle = _angle_deg(back_shoulder, back_elbow, back_wrist)

        dx = mid_shoulder.x - mid_hip.x
        dy = mid_shoulder.y - mid_hip.y
        torso_tilt_angle = math.degrees(math.atan2(abs(dx), max(abs(dy), 1e-6)))
        lean_dx = front_ankle.x - mid_hip.x
        direction_ok = dx == 0 or lean_dx == 0 or (dx * lean_dx > 0)

        response["front_knee_angle"] = round(front_knee_angle, 1)
        response["back_knee_angle"] = round(back_knee_angle, 1)
        response["torso_tilt_angle"] = round(torso_tilt_angle, 1)
        response["stance_ratio"] = round(stance_ratio, 2)
        response["front_elbow_angle"] = round(front_elbow_angle, 1)
        response["back_elbow_angle"] = round(back_elbow_angle, 1)

        # ---- hard gate: hysteresis on the two primary signals ----
        if self.hold_active:
            front_knee_broken = front_knee_angle < FRONT_KNEE_BROKEN
            torso_tilt_broken = (
                torso_tilt_angle < TORSO_TILT_BROKEN_MIN
                or torso_tilt_angle > TORSO_TILT_HARD_MAX
                or not direction_ok
            )
        else:
            front_knee_broken = front_knee_angle < FRONT_KNEE_RESUME
            torso_tilt_broken = (
                torso_tilt_angle < TORSO_TILT_RESUME_MIN
                or torso_tilt_angle > TORSO_TILT_HARD_MAX
                or not direction_ok
            )

        stance_ok = stance_ratio >= STANCE_MIN_RATIO

        upper_arm_raised = back_wrist.y <= mid_shoulder.y - UPPER_ARM_RAISE_MIN_RATIO * torso_length
        lower_arm_reaching = front_wrist.y >= mid_hip.y - LOWER_ARM_REACH_SLACK_RATIO * torso_length
        arms_extended = (
            front_elbow_angle >= ARM_EXTENDED_MIN_DEG
            and back_elbow_angle >= ARM_EXTENDED_MIN_DEG
        )
        arms_ok = arms_extended and upper_arm_raised and lower_arm_reaching

        holding_now = (
            framing_message is None
            and side_matches
            and not front_knee_broken
            and not torso_tilt_broken
            and stance_ok
            and arms_ok
        )

        # ---- form tiering (only meaningful while holding) ----
        issues: list[str] = []
        messages: list[str] = []
        if holding_now:
            if front_knee_angle < FRONT_KNEE_IDEAL:
                issues.append("front_knee_bent")
                messages.append(
                    "Straighten your front leg fully — press through the "
                    "front thigh, don't let the knee bend."
                )
            if back_knee_angle < BACK_KNEE_IDEAL_MIN:
                issues.append("back_knee_bent")
                messages.append(
                    "Straighten your back leg too — keep both legs strong and straight."
                )
            if torso_tilt_angle < TORSO_TILT_IDEAL_MIN:
                issues.append("shallow_bend")
                messages.append(
                    "Hinge deeper from your hip over your front leg — reach "
                    "your lower hand further down your shin."
                )
            wrist_dx = abs(front_wrist.x - back_wrist.x) / shoulder_width
            if wrist_dx > ARM_STACK_IDEAL_MAX_RATIO:
                issues.append("arms_not_stacked")
                messages.append(
                    "Stack your arms into one straight vertical line — open "
                    "your chest so your top arm is directly above your bottom arm."
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

        # ---- feedback priority: framing > side mismatch > hard break > flaws > praise ----
        feedback = framing_message
        if feedback is None and not side_matches:
            feedback = (
                f"This hold is for your {self.expected_side} side — "
                f"switch which leg is forward."
            )
        if feedback is None and (front_knee_broken or torso_tilt_broken or not stance_ok or not arms_ok):
            feedback = (
                "That's not quite Triangle Pose yet — wide stance, front leg "
                "straight, hinge sideways at the hip, one hand reaching down "
                "toward your shin, the other reaching straight up."
            )
        if feedback is None and messages:
            feedback = messages[0]
        if feedback is None and target_reached:
            feedback = f"Target reached — {self.target_seconds}s held on your {self.front_side} side!"
        if feedback is None and holding_now:
            feedback = "Great Triangle Pose — keep holding!"
        if feedback is None:
            feedback = "Get back into Triangle Pose to resume the timer."

        response.update(
            {
                "hold_state": "holding" if holding_now else "broken",
                "is_holding": holding_now,
                "target_reached": target_reached,
                "hold_quality": hold_quality,
                "posture_ok": len(issues) == 0,
                "posture_issues": issues,
                "posture_messages": messages,
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


def _side_for_set(set_number: int, target_sets: int) -> Optional[str]:
    """Set 1 = left leg forward, set 2 = right leg forward, alternating.
    A single-set session (target_sets == 1) doesn't enforce a side."""
    if target_sets < 2:
        return None
    return "left" if set_number % 2 == 1 else "right"


class TrianglePoseSession:
    """Full Triangle Pose session: one shared pose model + one analyzer.

    `target_seconds` / `target_sets` / `set_number` are the coach-assigned
    plan, supplied by the caller (the websocket route, from query params) —
    same convention as `SidePlankSession`. `side` can be passed explicitly
    (overrides the left/right-alternating default derived from
    `set_number`). The frontend does not decide on its own whether a
    side/set/exercise is done — `session_complete` and `exercise_complete`
    are both computed here.
    """

    def __init__(
        self,
        target_seconds: Optional[int] = None,
        target_sets: int = 2,
        set_number: int = 1,
        side: Optional[str] = None,
    ):
        self.engine = PoseEngine()
        self.target_sets = max(1, target_sets)
        self.set_number = max(1, min(set_number, self.target_sets))
        expected_side = side if side in ("left", "right") else _side_for_set(
            self.set_number, self.target_sets
        )
        self.analyzer = TrianglePoseAnalyzer(target_seconds, expected_side)

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
