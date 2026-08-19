"""
Muay Thai jab counter.

Design
------
A jab is fundamentally different from a push-up or a squat: it isn't a slow
grind through a range of motion, it's a *fast* guard -> extension -> guard
snap, thrown from a standing stance, and (unlike push-ups) either arm can
throw it independently at any moment. So this analyzer:

    * Tracks the left and right arm completely independently (two small
      `_ArmTracker` state machines), instead of averaging L/R like the
      push-up analyzer does — you can jab with either hand, or both.
    * Uses elbow angle (shoulder-elbow-wrist) as the primary signal, same
      convention as the push-up/bicep-curl analyzers, but with much looser
      timing windows: a real jab snaps out and back in well under a
      second, so the duration gates here are far tighter than a push-up's.
    * Requires the punch to actually *start from a guard* — wrist near
      head/shoulder height right before the arm fires — not just "elbow
      was bent". This is a beginner-coaching exercise, so a beginner
      throwing haymakers from their hips shouldn't get free reps; they
      should get told to keep their hands up.
    * Requires a minimum forward reach (wrist moving away from the
      shoulder, normalized by shoulder width) in addition to the elbow
      angle, so a stationary elbow twitch can't register as a punch.

Like the push-up analyzer, counting is gated behind a `ready` flag that
only turns on once a stable standing stance is confirmed for several
consecutive frames (and turns off only after several consecutive bad
frames), so single-frame tracking glitches can't flicker it on and off.
"""

import math
import time
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

# Elbow angle (shoulder-elbow-wrist) thresholds driving each arm's state
# machine. Looser than a push-up's 155/95 split — a jab doesn't need to
# lock out completely straight to count, just clearly extend.
GUARD_ANGLE = 110.0  # elbow bent this much or less = "guard" (cocked)
EXTEND_ANGLE = 150.0  # elbow opened this much or more = "extended" (punch out)
MIN_ANGLE_DELTA = 30.0  # total angle travel required for a punch to "count"

# A real jab is fast. These bounds are per-punch (guard -> extend -> guard),
# not per-half — much tighter than a push-up's 0.35s-8s window.
MIN_PUNCH_DURATION = 0.10  # seconds — faster = probably a tracking glitch
MAX_PUNCH_DURATION = 1.6  # seconds — slower = a slow arm raise, not a jab

# Forward reach requirement: how far the wrist has to travel away from the
# shoulder (normalized by shoulder width) to count as an actual extension,
# not just elbow noise. ~0.7x shoulder width is a light, beginner-friendly
# bar for "the hand went somewhere".
MIN_REACH_RATIO = 0.55

# Guard-height requirement: wrist must be at or above this height (in
# normalized image coords, smaller y = higher on screen) relative to the
# shoulder, measured at the *start* of the punch attempt, to count as
# "hands up" rather than a punch thrown from down at the hip.
GUARD_MAX_WRIST_DROP = 0.30  # fraction of torso length below shoulder line

# -------------------------------------------------------------------------
# Standing-stance detection (mirrors the push-up analyzer's floor check,
# but the polarity we actually gate on here is simply "upright").
# -------------------------------------------------------------------------
TORSO_INCLINE_STANDING_MIN_DEG = 55.0
STABLE_STANCE_FRAMES = 5
GRACE_FRAMES = 8

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
    return visible_core >= 3


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
            return "You're partly out of frame — step back so your upper body is fully visible."

    if len(points) < 4:
        return None

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "You're too close to the camera — back up a step."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


def _classify_tempo(duration: Optional[float]) -> Optional[str]:
    """Jab-specific tempo bands — much faster than the push-up ones."""
    if duration is None:
        return None
    if duration >= 0.9:
        return "too_slow"
    if duration >= 0.5:
        return "slow"
    if duration >= 0.18:
        return "sharp"
    return "too_fast"


class _ArmTracker:
    """Independent guard -> extend -> guard state machine for one arm."""

    def __init__(self, label: str):
        self.label = label  # "left" or "right"
        self.stage = "guard"
        self.count = 0
        self.smoothed_angle: Optional[float] = None
        self.last_angle: Optional[float] = None
        self.punch_start_time: Optional[float] = None
        self._punch_started_from_guard = False
        self._max_reach_ratio = 0.0
        self.last_punch_duration: Optional[float] = None
        self.last_punch_speed: Optional[float] = None
        self.last_punch_classification: Optional[str] = None
        self.last_extension_angle: Optional[float] = None

    def update(
        self,
        t: float,
        shoulder,
        elbow,
        wrist,
        torso_length: float,
        shoulder_width: float,
        ready: bool,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "punch_completed": False,
            "duration": None,
            "classification": None,
            "reach_ratio": None,
        }

        if not _visible((shoulder, elbow, wrist)):
            return result

        raw_angle = _angle_deg(shoulder, elbow, wrist)
        if self.smoothed_angle is None:
            self.smoothed_angle = raw_angle
        else:
            self.smoothed_angle = 0.6 * raw_angle + 0.4 * self.smoothed_angle

        reach_ratio = _dist(shoulder, wrist) / max(shoulder_width, 1e-6)
        result["reach_ratio"] = reach_ratio

        if not ready:
            # Stance isn't confirmed — don't progress the state machine,
            # but keep smoothing the angle so there's no jump on resume.
            self.last_angle = self.smoothed_angle
            return result

        wrist_drop = (wrist.y - shoulder.y) / max(torso_length, 1e-6)

        if self.stage == "guard":
            if self.smoothed_angle >= EXTEND_ANGLE and reach_ratio >= MIN_REACH_RATIO:
                # Only a genuine "started from guard" attempt (hands were
                # up recently) gets to count when it snaps back.
                self._punch_started_from_guard = wrist_drop <= GUARD_MAX_WRIST_DROP
                self.stage = "extended"
                self.punch_start_time = t
                self._max_reach_ratio = reach_ratio
            elif self.smoothed_angle < GUARD_ANGLE:
                # Still resting in guard — remember whether hands are up,
                # so the *next* extension attempt can check it retroactively
                # isn't needed since we check at the transition instant above.
                pass
        elif self.stage == "extended":
            self._max_reach_ratio = max(self._max_reach_ratio, reach_ratio)
            if self.smoothed_angle <= GUARD_ANGLE:
                duration = (
                    (t - self.punch_start_time)
                    if self.punch_start_time is not None
                    else None
                )
                angle_delta = EXTEND_ANGLE - GUARD_ANGLE  # guaranteed by thresholds
                valid = (
                    duration is not None
                    and MIN_PUNCH_DURATION <= duration <= MAX_PUNCH_DURATION
                    and self._max_reach_ratio >= MIN_REACH_RATIO
                    and angle_delta >= MIN_ANGLE_DELTA
                    and self._punch_started_from_guard
                )
                if valid:
                    self.count += 1
                    classification = _classify_tempo(duration)
                    self.last_punch_duration = duration
                    self.last_punch_speed = (
                        self._max_reach_ratio / duration if duration else None
                    )
                    self.last_punch_classification = classification
                    self.last_extension_angle = self.smoothed_angle
                    result["punch_completed"] = True
                    result["duration"] = duration
                    result["classification"] = classification
                    result["reach_ratio"] = self._max_reach_ratio
                self.stage = "guard"
                self.punch_start_time = None
                self._punch_started_from_guard = False
                self._max_reach_ratio = 0.0

        self.last_angle = self.smoothed_angle
        return result


class JabAnalyzer:
    """Stateful Muay Thai jab counter — tracks both arms independently."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps
        self.left = _ArmTracker("left")
        self.right = _ArmTracker("right")

        self.good_reps = 0
        self.flawed_reps = 0

        self._stance_streak = 0
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
            "left_elbow_angle": None,
            "right_elbow_angle": None,
            "left_stage": self.left.stage,
            "right_stage": self.right.stage,
            "left_count": self.left.count,
            "right_count": self.right.count,
            "rep_count": total_reps,
            "target_reps": self.target_reps,
            "good_reps": self.good_reps,  # NEW: Universal key
            "flawed_reps": self.flawed_reps,  # NEW: Universal key
            "rep_completed": False,  # NEW: Universal key
            "rep_form_quality": None,  # NEW: Universal key
            "session_complete": self._is_complete(),
            "punch_completed": False,
            "punch_hand": None,
            "punch_duration": None,
            "punch_avg_speed": None,
            "punch_classification": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = "No person detected — step into frame."
            return response

        response["pose_detected"] = True

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]

        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
        if not torso_visible:
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your torso clearly — make sure your shoulders "
                "and hips are both in frame."
            )
            return response

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)
        shoulder_width = max(_dist(l_shoulder, r_shoulder), 1e-6)

        torso_incline = _torso_incline_deg(mid_shoulder, mid_hip)
        is_standing = (
            torso_incline is not None
            and torso_incline >= TORSO_INCLINE_STANDING_MIN_DEG
        )

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
            )
            if _visible((p,))
        ]
        bbox_points = [_Point(p.x, p.y) for p in bbox_candidates]
        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        if is_standing:
            self._stance_streak += 1
            self._bad_streak = 0
        else:
            self._stance_streak = 0
            self._bad_streak += 1

        if self._stance_streak >= STABLE_STANCE_FRAMES:
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES:
            self.ready = False

        response["ready"] = self.ready
        response["stance_ok"] = self.ready
        if not is_standing:
            response["stance_message"] = (
                "Stand up into a boxing stance, facing the camera, so your "
                "shoulders, elbows and wrists are all visible."
            )
        elif not self.ready:
            response["stance_message"] = "Hold your stance steady to start counting…"

        # ---- run both arm state machines ----
        left_result = self.left.update(
            t, l_shoulder, l_elbow, l_wrist, torso_length, shoulder_width, self.ready
        )
        right_result = self.right.update(
            t, r_shoulder, r_elbow, r_wrist, torso_length, shoulder_width, self.ready
        )

        response["left_elbow_angle"] = self.left.smoothed_angle
        response["right_elbow_angle"] = self.right.smoothed_angle
        response["left_stage"] = self.left.stage
        response["right_stage"] = self.right.stage

        feedback = framing_message

        for hand, r in (("left", left_result), ("right", right_result)):
            if r["punch_completed"]:
                response["punch_completed"] = True
                response["rep_completed"] = True  # NEW: Trigger standard frontend rep
                response["punch_hand"] = hand
                response["punch_duration"] = r["duration"]
                response["punch_avg_speed"] = (
                    r["reach_ratio"] / r["duration"] if r["duration"] else None
                )
                response["punch_classification"] = r["classification"]

                tempo = r["classification"] or "n/a"

                # NEW: Categorize into good vs flawed reps
                if tempo == "sharp":
                    self.good_reps += 1
                    response["rep_form_quality"] = "good"
                    feedback = f"Sharp {hand} jab — nice snap back to guard."
                elif tempo in ("slow", "too_slow"):
                    self.flawed_reps += 1
                    response["rep_form_quality"] = "needs_improvement"
                    if tempo == "slow":
                        feedback = (
                            f"{hand.capitalize()} jab counted, but snap it back faster."
                        )
                    else:
                        feedback = f"{hand.capitalize()} jab counted — try to retract quicker next time."
                else:
                    self.good_reps += 1
                    response["rep_form_quality"] = "good"
                    feedback = f"{hand.capitalize()} jab counted."

        # Update the final rep counts after checking both arms
        response["left_count"] = self.left.count
        response["right_count"] = self.right.count
        response["rep_count"] = self.left.count + self.right.count
        response["good_reps"] = self.good_reps
        response["flawed_reps"] = self.flawed_reps
        response["session_complete"] = self._is_complete()

        if feedback is None and not self.ready:
            feedback = response["stance_message"] or (
                "Get into a boxing stance — hands up, facing the camera."
            )
        if feedback is None:
            # Give a nudge about guard height if a hand is drifting low.
            l_drop = (
                (l_wrist.y - l_shoulder.y) / torso_length
                if _visible((l_wrist, l_shoulder))
                else 0
            )
            r_drop = (
                (r_wrist.y - r_shoulder.y) / torso_length
                if _visible((r_wrist, r_shoulder))
                else 0
            )
            if max(l_drop, r_drop) > GUARD_MAX_WRIST_DROP and self.ready:
                feedback = "Keep your hands up near your chin between jabs."
            else:
                feedback = "Good guard — throw a jab when ready."

        response["feedback"] = feedback
        return response


class JabSession:
    """Full jab session: one shared pose model + one analyzer.

    Mirrors `PushupSession` — `target_reps` / `target_sets` / `set_number`
    are the coach-assigned plan, supplied by the websocket route from
    query params. `session_complete` / `exercise_complete` are computed
    here, never on the frontend.
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

        result["set_number"] = self.set_number
        result["target_sets"] = self.target_sets
        result["exercise_complete"] = bool(
            result["session_complete"] and self.set_number >= self.target_sets
        )
        return result

    def close(self):
        self.engine.close()
