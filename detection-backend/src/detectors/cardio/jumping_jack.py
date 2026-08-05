"""
Jumping jack rep counter.

Design
------
A jumping jack has exactly two moving parts that always happen together:
arms swing from the sides up overhead, and feet jump from together to
apart. Instead of tracking a dozen small signals (which is how counters
end up flaky — one noisy signal misfires and either a rep is missed or a
fake one is added), this detector tracks exactly two numbers:

  * `arm_raise`   — how far the wrists are above the shoulders, scaled by
                     the person's own torso length (so it works whether
                     they're close to the camera or far away).
  * `leg_spread`  — how far apart the ankles are, scaled by the person's
                     own hip width (same reasoning).

A rep is: both numbers climb past an "open" line (arms up, feet apart),
then both drop back past a "closed" line (arms down, feet together).
That's it. The open/closed lines are set with a gap between them
(hysteresis) so a person holding roughly still at the top or bottom can't
cause the count to flicker up and down on tiny frame-to-frame jitter.

Both signals are also smoothed frame-to-frame (a simple moving average)
before they're compared to any threshold, which is what keeps a single
noisy pose-detection frame from breaking a rep in half or adding a phantom
one.

What this detector deliberately does NOT do: grade elbow bend, torso lean,
jump height, or landing softness. Every extra rule is one more way for a
correct jumping jack to get rejected or miscounted, and that's exactly the
failure mode to avoid here. Form feedback is limited to the two things
that actually define the movement — did the arms get overhead, did the
feet get apart — and it never blocks the count, it just tells the person
how to make the next one crisper.
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_HIP,
    LEFT_SHOULDER,
    LEFT_WRIST,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_HIP,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)

# -------------------------------------------------------------------------
# Tunable constants
# -------------------------------------------------------------------------

MIN_LANDMARK_VISIBILITY = 0.4

CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)

# arm_raise = (shoulder.y - wrist.y) / torso_length
#   negative  -> wrist below shoulder (arm down at the side)
#   ~0        -> wrist level with shoulder
#   positive  -> wrist above shoulder (arm raised)
ARM_OPEN = 0.20  # wrists comfortably above the shoulders
ARM_CLOSE = -0.05  # wrists back down near/below the shoulders

# leg_spread = ankle-to-ankle distance / hip width
#   ~1.0-1.3  -> feet roughly under the hips (standing normally)
#   2.0+      -> feet jumped out wide
LEG_OPEN = 1.7  # feet clearly jumped apart
LEG_CLOSE = 1.3  # feet back together

# "Full extension" targets used only for the coaching message, not for
# whether the rep counts at all.
ARM_FULL_TARGET = 0.35
LEG_FULL_TARGET = 2.0

MIN_REP_DURATION = 0.25  # seconds — faster than this is almost certainly noise
MAX_REP_DURATION = 4.0  # seconds — slower than this is a pause, not one jack

SMOOTH_ALPHA = 0.5  # moving-average weight for the newest frame

STABLE_FRAMES = 4  # consecutive good frames before counting turns on
GRACE_FRAMES = 10  # consecutive bad frames tolerated before counting turns off

# Camera framing
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


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _visible(points) -> bool:
    for p in points:
        if p is None:
            return False
        v = getattr(p, "visibility", None)
        if v is not None and v < MIN_LANDMARK_VISIBILITY:
            return False
    return True


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 3


def _framing_feedback(points: list[_Point]) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "Part of you is out of frame — step back so your whole body is visible."
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
        return "You're too far from the camera — move a bit closer."

    return None


class JumpingJackAnalyzer:
    """Stateful jumping-jack rep counter."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.stage = (
            "closed"  # "closed" = feet together/arms down, "open" = jack extended
        )
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        self.smoothed_arm: Optional[float] = None
        self.smoothed_leg: Optional[float] = None

        self.last_timestamp_s: Optional[float] = None
        self.rep_start_time: Optional[float] = None
        self.session_start_time: Optional[float] = None

        # Best (highest) arm/leg values reached during the current "open"
        # phase — used only to grade how crisp the rep was.
        self._open_peak_arm: Optional[float] = None
        self._open_peak_leg: Optional[float] = None

        # Simple visibility/framing gate — same idea as the other
        # detectors: only count once tracking has been solid for a few
        # frames in a row, and give it some slack before giving up again.
        self._good_streak = 0
        self._bad_streak = 0
        self.ready = False

    # ---------------------------------------------------------------
    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 2.2:
            return "too_slow"
        if duration >= 1.4:
            return "slow"
        if duration >= 0.5:
            return "good"
        if duration >= 0.25:
            return "fast"
        return "too_fast"

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
            "position_ok": False,
            "position_message": None,
            "ready": self.ready,
            "arm_raise": None,
            "leg_spread_ratio": None,
            "smoothed_arm_raise": None,
            "smoothed_leg_spread_ratio": None,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_duration": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = "No person detected — step into frame."
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
        arms_visible = _visible((l_wrist, r_wrist))
        legs_visible = _visible((l_ankle, r_ankle))

        response["pose_detected"] = True

        if not torso_visible:
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your shoulders and hips clearly — step back "
                "so your whole body is in frame."
            )
            return response

        if not arms_visible or not legs_visible:
            response["low_visibility"] = True
            missing = []
            if not arms_visible:
                missing.append("hands")
            if not legs_visible:
                missing.append("feet")
            response["feedback"] = (
                f"Can't see your {' and '.join(missing)} clearly — move back "
                "so your whole body, hands to feet, fits in the camera."
            )
            return response

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)
        hip_width = max(_dist(l_hip, r_hip), 1e-6)

        # ---- framing check ----
        bbox_points = [
            _Point(p.x, p.y)
            for p in (
                l_shoulder,
                r_shoulder,
                l_wrist,
                r_wrist,
                l_hip,
                r_hip,
                l_ankle,
                r_ankle,
            )
        ]
        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        # ---- the two signals that define a jumping jack ----
        arm_raise = (
            ((l_shoulder.y - l_wrist.y) + (r_shoulder.y - r_wrist.y))
            / 2.0
            / torso_length
        )
        leg_spread_ratio = _dist(l_ankle, r_ankle) / hip_width

        if self.smoothed_arm is None:
            self.smoothed_arm = arm_raise
            self.smoothed_leg = leg_spread_ratio
        else:
            self.smoothed_arm = (
                SMOOTH_ALPHA * arm_raise + (1 - SMOOTH_ALPHA) * self.smoothed_arm
            )
            self.smoothed_leg = (
                SMOOTH_ALPHA * leg_spread_ratio + (1 - SMOOTH_ALPHA) * self.smoothed_leg
            )

        # ---- tracking-quality gate: only count once it's been solid for
        # a handful of frames in a row, same idea as the other detectors ----
        good_frame = framing_message is None
        if good_frame:
            self._good_streak += 1
            self._bad_streak = 0
        else:
            self._good_streak = 0
            self._bad_streak += 1

        if self._good_streak >= STABLE_FRAMES:
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES:
            self.ready = False

        position_ok = self.ready
        response["position_ok"] = position_ok
        response["ready"] = self.ready
        response["position_message"] = None if position_ok else framing_message

        feedback = framing_message
        rep_completed = False
        rep_duration = rep_class = rep_form_quality = None

        if position_ok:
            is_open = self.smoothed_arm >= ARM_OPEN and self.smoothed_leg >= LEG_OPEN
            is_closed = (
                self.smoothed_arm <= ARM_CLOSE and self.smoothed_leg <= LEG_CLOSE
            )

            if self.stage == "closed" and is_open:
                self.stage = "open"
                self.rep_start_time = t
                self._open_peak_arm = self.smoothed_arm
                self._open_peak_leg = self.smoothed_leg
            elif self.stage == "open":
                if (
                    self._open_peak_arm is None
                    or self.smoothed_arm > self._open_peak_arm
                ):
                    self._open_peak_arm = self.smoothed_arm
                if (
                    self._open_peak_leg is None
                    or self.smoothed_leg > self._open_peak_leg
                ):
                    self._open_peak_leg = self.smoothed_leg

                if is_closed:
                    self.stage = "closed"
                    rep_completed = True

            if rep_completed:
                rep_duration = (
                    (t - self.rep_start_time)
                    if self.rep_start_time is not None
                    else None
                )
                valid = (
                    rep_duration is not None
                    and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                )

                if valid:
                    self.rep_count += 1
                    rep_class = self._classify_tempo(rep_duration)

                    reached_full_arms = (
                        self._open_peak_arm is not None
                        and self._open_peak_arm >= ARM_FULL_TARGET
                    )
                    reached_full_legs = (
                        self._open_peak_leg is not None
                        and self._open_peak_leg >= LEG_FULL_TARGET
                    )

                    if reached_full_arms and reached_full_legs:
                        rep_form_quality = "good"
                        self.good_reps += 1
                        feedback = (
                            f"Clean rep — nice full extension ({rep_duration:.2f}s)."
                        )
                    else:
                        rep_form_quality = "needs_improvement"
                        self.flawed_reps += 1
                        tips = []
                        if not reached_full_arms:
                            tips.append("raise your arms all the way overhead")
                        if not reached_full_legs:
                            tips.append("jump your feet out a bit wider")
                        feedback = (
                            f"Rep {self.rep_count} counted — next time, "
                            + " and ".join(tips)
                            + "."
                        )
                else:
                    rep_completed = False
                    if rep_duration is not None and rep_duration < MIN_REP_DURATION:
                        feedback = "That was too fast to count — keep a steady pace."
                    else:
                        feedback = "Not counted — keep the movement continuous."

                self.rep_start_time = None
                self._open_peak_arm = None
                self._open_peak_leg = None

        else:
            if self.rep_start_time is not None:
                self.rep_start_time = None
                self._open_peak_arm = None
                self._open_peak_leg = None

        self.last_timestamp_s = t

        if feedback is None and not self.ready:
            feedback = "Get your whole body in frame, standing, to start counting."
        if feedback is None:
            feedback = "Good — keep going."

        response.update(
            {
                "arm_raise": arm_raise,
                "leg_spread_ratio": leg_spread_ratio,
                "smoothed_arm_raise": self.smoothed_arm,
                "smoothed_leg_spread_ratio": self.smoothed_leg,
                "stage": self.stage,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_duration": rep_duration,
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "feedback": feedback,
            }
        )
        return response


class JumpingJackSession:
    """Full jumping-jack session: one shared pose model + one analyzer.

    Same `target_reps` / `target_sets` / `set_number` convention as every
    other exercise session in this backend — the coach-assigned plan is
    supplied by the caller (the websocket route) and this class is the
    only thing that decides `session_complete` / `exercise_complete`.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = JumpingJackAnalyzer(target_reps)
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
