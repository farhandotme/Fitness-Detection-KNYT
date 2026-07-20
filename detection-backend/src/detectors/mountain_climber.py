"""
Mountain climber counter.

Design
------
A mountain climber is the *leg* equivalent of the jab: thrown from a
held plank base (not a standing guard), one knee drives fast toward the
chest and snaps back to extended, while the other leg stays planted. So
this analyzer is deliberately built the same way `JabAnalyzer` is, just
with the roles swapped — legs instead of arms, a plank base instead of a
standing guard:

    * Tracks the left and right leg completely independently (two small
      `_LegTracker` state machines) — only one leg drives at a time in a
      real mountain climber, and tracking them separately means the
      planted leg can never accidentally register a rep just because the
      driving leg is moving.
    * Uses hip flexion angle (shoulder-hip-knee) as the primary signal:
      close to straight (~155°+) when the leg is extended back in plank,
      collapsing well below that (~125° or less) when the knee is driven
      toward the chest.
    * Requires the movement to actually start from a **held plank base**
      — torso roughly horizontal, arms roughly locked — not just "hip
      angle changed", so someone shifting around on the floor without a
      real plank doesn't rack up free reps. This is a beginner-coaching
      exercise: the priority is telling a beginner to hold their plank
      and drive with pace, not nitpicking form once the base is good.
    * Requires the knee to actually travel a meaningful distance toward
      the torso (not just the angle opening from noise), using
      knee-to-shoulder distance normalized by torso length.

Like the jab and push-up analyzers, counting is gated behind a `ready`
flag that only turns on once a stable plank base is confirmed for several
consecutive frames (and turns off only after several consecutive bad
frames), so single-frame tracking glitches can't flicker it on and off.
"""

import math
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

# Hip flexion angle (shoulder-hip-knee) thresholds driving each leg's
# state machine.
EXTENDED_ANGLE = 150.0  # leg reads as "extended back in plank" at/above this
DRIVEN_ANGLE = 135.0  # leg reads as "knee driven toward chest" at/below this
MIN_ANGLE_DELTA = 10.0  # total angle travel required for a drive to "count"

# A real mountain-climber knee-drive is fast, but beginners are often
# slower and less sharp than an experienced lifter — these windows are
# deliberately generous so a genuine, if unhurried, knee drive still counts.
MIN_DRIVE_DURATION = 0.08  # seconds — faster = probably a tracking glitch
MAX_DRIVE_DURATION = 2.5  # seconds — slower = a slow knee tuck, not a drive

# Forward-travel requirement: the knee has to actually get close to the
# torso (normalized by torso length) to count as a real drive, not just
# hip-angle noise while stationary. Loosened from a stricter "knee to
# chest" bar so a beginner's shorter knee drive still registers.
MAX_CLOSE_RATIO = 1.6

# -------------------------------------------------------------------------
# Plank-base detection (mirrors the plank-hold analyzer's body-alignment
# idea, simplified: here we only need "is this roughly a held plank right
# now", not a strict, continuously-graded hold).
# -------------------------------------------------------------------------
TORSO_INCLINE_PLANK_MAX_DEG = 55.0  # torso should read as roughly horizontal
ELBOW_LOCK_MIN_DEG = 120.0  # arms should be roughly straight, not collapsed
STABLE_STANCE_FRAMES = 3
GRACE_FRAMES = 15

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


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    # Mountain climber is filmed side-on, like a plank — the far
    # shoulder/hip is routinely occluded by the body itself, so (unlike
    # the standing, front-facing jab) this can't require 3-of-4 core
    # landmarks. 2-of-4 matches what the plank-hold analyzer uses for the
    # same reason.
    return visible_core >= 2


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
            return "You're partly out of frame — step back so your full body is visible."

    if len(points) < 4:
        return None

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "You're too close to the camera — back up so your whole body fits."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


def _classify_tempo(duration: Optional[float]) -> Optional[str]:
    """Mountain-climber-specific tempo bands — fast, like the jab's."""
    if duration is None:
        return None
    if duration >= 0.9:
        return "too_slow"
    if duration >= 0.5:
        return "slow"
    if duration >= 0.18:
        return "sharp"
    return "too_fast"


class _LegTracker:
    """Independent extended -> driven -> extended state machine for one leg."""

    def __init__(self, label: str):
        self.label = label  # "left" or "right"
        self.stage = "extended"
        self.count = 0
        self.smoothed_angle: Optional[float] = None
        self.drive_start_time: Optional[float] = None
        self._min_close_ratio = float("inf")
        self.last_drive_duration: Optional[float] = None
        self.last_drive_classification: Optional[str] = None

    def update(
        self,
        t: float,
        shoulder,
        hip,
        knee,
        torso_length: float,
        ready: bool,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "drive_completed": False,
            "duration": None,
            "classification": None,
            "close_ratio": None,
        }

        if not _visible((shoulder, hip, knee)):
            return result

        raw_angle = _angle_deg(shoulder, hip, knee)
        if self.smoothed_angle is None:
            self.smoothed_angle = raw_angle
        else:
            self.smoothed_angle = 0.6 * raw_angle + 0.4 * self.smoothed_angle

        close_ratio = _dist(knee, shoulder) / max(torso_length, 1e-6)
        result["close_ratio"] = close_ratio

        if not ready:
            # Plank base isn't confirmed — don't progress the state
            # machine, but keep smoothing so there's no jump on resume.
            return result

        if self.stage == "extended":
            if self.smoothed_angle <= DRIVEN_ANGLE:
                self.stage = "driven"
                self.drive_start_time = t
                self._min_close_ratio = close_ratio
        elif self.stage == "driven":
            self._min_close_ratio = min(self._min_close_ratio, close_ratio)
            if self.smoothed_angle >= EXTENDED_ANGLE:
                duration = (
                    (t - self.drive_start_time)
                    if self.drive_start_time is not None
                    else None
                )
                angle_delta = EXTENDED_ANGLE - DRIVEN_ANGLE
                valid = (
                    duration is not None
                    and MIN_DRIVE_DURATION <= duration <= MAX_DRIVE_DURATION
                    and self._min_close_ratio <= MAX_CLOSE_RATIO
                    and angle_delta >= MIN_ANGLE_DELTA
                )
                if valid:
                    self.count += 1
                    classification = _classify_tempo(duration)
                    self.last_drive_duration = duration
                    self.last_drive_classification = classification
                    result["drive_completed"] = True
                    result["duration"] = duration
                    result["classification"] = classification
                    result["close_ratio"] = self._min_close_ratio
                self.stage = "extended"
                self.drive_start_time = None
                self._min_close_ratio = float("inf")

        return result


class MountainClimberAnalyzer:
    """Stateful mountain-climber counter — tracks both legs independently."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps
        self.left = _LegTracker("left")
        self.right = _LegTracker("right")

        self._plank_streak = 0
        self._bad_streak = 0
        self.ready = False

        self.session_start_time: Optional[float] = None

    def _is_complete(self) -> bool:
        total = self.left.count + self.right.count
        return self.target_reps is not None and total >= self.target_reps

    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        total_reps = self.left.count + self.right.count

        response: dict[str, Any] = {
            "pose_detected": False,
            "ready": self.ready,
            "stance_ok": False,
            "stance_message": None,
            "framing_ok": True,
            "framing_message": None,
            "left_hip_angle": None,
            "right_hip_angle": None,
            "left_stage": self.left.stage,
            "right_stage": self.right.stage,
            "left_count": self.left.count,
            "right_count": self.right.count,
            "rep_count": total_reps,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "drive_completed": False,
            "drive_leg": None,
            "drive_duration": None,
            "drive_classification": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = "No person detected — step into frame."
            return response

        response["pose_detected"] = True

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]

        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
        if not torso_visible:
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your torso clearly — make sure your shoulders "
                "and hips are both in frame, from the side."
            )
            return response

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)

        torso_incline = _torso_incline_deg(mid_shoulder, mid_hip)
        is_horizontal = (
            torso_incline is not None
            and torso_incline <= TORSO_INCLINE_PLANK_MAX_DEG
        )

        # Arms should read as roughly locked/straight if visible — a
        # collapsed elbow means the person isn't actually holding a plank
        # base (e.g. resting on forearms or lying down). Only enforced
        # when at least one arm is confidently visible, since a side-on
        # camera angle can occlude the far arm entirely.
        arm_ok = True
        if _visible((l_shoulder, l_elbow, l_wrist)):
            arm_ok = arm_ok and _angle_deg(l_shoulder, l_elbow, l_wrist) >= ELBOW_LOCK_MIN_DEG
        if _visible((r_shoulder, r_elbow, r_wrist)):
            arm_ok = arm_ok and _angle_deg(r_shoulder, r_elbow, r_wrist) >= ELBOW_LOCK_MIN_DEG

        is_plank = is_horizontal and arm_ok

        bbox_candidates = [
            p
            for p in (
                l_shoulder, r_shoulder, l_elbow, r_elbow, l_wrist, r_wrist,
                l_hip, r_hip, l_knee, r_knee, l_ankle, r_ankle,
            )
            if _visible((p,))
        ]
        bbox_points = [_Point(p.x, p.y) for p in bbox_candidates]
        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        if is_plank:
            self._plank_streak += 1
            self._bad_streak = 0
        else:
            self._plank_streak = 0
            self._bad_streak += 1

        if self._plank_streak >= STABLE_STANCE_FRAMES:
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES:
            self.ready = False

        response["ready"] = self.ready
        response["stance_ok"] = self.ready
        if not is_horizontal:
            response["stance_message"] = (
                "Get into a plank — hands under shoulders, body in a "
                "straight line, filmed from the side."
            )
        elif not arm_ok:
            response["stance_message"] = "Lock your arms out — keep your elbows straight in plank."
        elif not self.ready:
            response["stance_message"] = "Hold your plank steady to start counting…"

        # ---- run both leg state machines ----
        left_result = self.left.update(t, l_shoulder, l_hip, l_knee, torso_length, self.ready)
        right_result = self.right.update(t, r_shoulder, r_hip, r_knee, torso_length, self.ready)

        response["left_hip_angle"] = self.left.smoothed_angle
        response["right_hip_angle"] = self.right.smoothed_angle
        response["left_stage"] = self.left.stage
        response["right_stage"] = self.right.stage
        response["left_count"] = self.left.count
        response["right_count"] = self.right.count
        response["rep_count"] = self.left.count + self.right.count
        response["session_complete"] = self._is_complete()

        feedback = framing_message

        for leg, r in (("left", left_result), ("right", right_result)):
            if r["drive_completed"]:
                response["drive_completed"] = True
                response["drive_leg"] = leg
                response["drive_duration"] = r["duration"]
                response["drive_classification"] = r["classification"]
                tempo = r["classification"] or "n/a"
                if tempo == "sharp":
                    feedback = f"Sharp {leg} knee drive — great pace."
                elif tempo == "slow":
                    feedback = f"{leg.capitalize()} knee drive counted, but pick up the pace."
                elif tempo == "too_slow":
                    feedback = f"{leg.capitalize()} drive counted — try driving the knee in faster."
                else:
                    feedback = f"{leg.capitalize()} knee drive counted."

        if feedback is None and not self.ready:
            feedback = response["stance_message"] or (
                "Get into a plank, filmed from the side, to start counting."
            )
        if feedback is None:
            feedback = "Good plank — drive a knee toward your chest when ready."

        response["feedback"] = feedback
        return response


class MountainClimberSession:
    """Full mountain-climber session: one shared pose model + one analyzer.

    Mirrors `JabSession` / `PushupSession` — `target_reps` / `target_sets`
    / `set_number` are the coach-assigned plan, supplied by the websocket
    route from query params. `session_complete` / `exercise_complete` are
    computed here, never on the frontend.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = MountainClimberAnalyzer(target_reps)
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
