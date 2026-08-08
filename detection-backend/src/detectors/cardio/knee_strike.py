"""
Knee Strikes / Knee Drives detector.

Movement contract
------------------
Stand tall, feet hip-width, torso upright and core engaged. Drive one
knee explosively up toward the chest/hip height, then return it to the
ground, and repeat — either leg, in any order. (Sources: liftmanual.com,
healthline.com, getfitcraft.com, grindergym.com, fitwill.app.) The
defining form cue across every source: the knee must reach at least hip
height, and the torso stays upright rather than leaning back to help
throw the knee up.

Per the request: EITHER knee counts, independently, with no requirement
to alternate — this is a "did a knee strike happen" counter, not a
paired left/right cycle like the lateral lunge.

Design notes (carried forward from the lateral_lunge.py / line_hop.py
debugging — read this before changing thresholds)
----------------------------------------------------
1. The signal is a per-leg HIP-FLEXION ANGLE (shoulder-hip-knee), not a
   raw pixel position. Angles are scale/distance invariant, so this
   isn't sensitive to how far the camera is or how the frame is cropped
   the way a raw-position metric would be.
2. view_mode (front/angled/side) is advisory ONLY, never a hard gate.
   Hard-gating on that heuristic previously caused a detector to get
   permanently stuck because a narrow-looking shoulder measurement
   (e.g. from arm swing) got misread as "side view".
3. Rep confirmation uses a single frame past threshold (not a multi-frame
   streak) plus a wide hysteresis gap between the "confirm" and
   "re-arm" angles — not a strict "must return to the exact standing
   angle" requirement. Fast, explosive knee drives can blow past a
   narrow window in one sampled frame; hysteresis with a generous gap
   survives that, a tight streak requirement doesn't.
4. Frames are NEVER discarded just because visibility dips — motion blur
   is worst exactly at the top of a fast knee drive, which is exactly
   the frame that must be read correctly. Geometry is computed from
   whatever coordinates the pose model returns every frame; visibility
   only feeds the initial lock-on and the on-screen message. Internal
   state only resets on a SUSTAINED loss of tracking, not a single bad
   frame.
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
)

# Bump this string on every edit. Printed at import time and at session
# start, and returned in every response as "detector_version" — check the
# server logs or the live response to confirm a redeploy actually took
# effect instead of silently continuing to run an old process.
DETECTOR_VERSION = "knee_strike-2026-08-08a"
print(f"[KneeStrike] loaded detector_version={DETECTOR_VERSION}")

MIN_VISIBILITY = 0.30
PERSON_VISIBILITY = 0.50
LEG_VISIBILITY = 0.28
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)

# Hip-flexion angle = angle at the hip between shoulder and knee.
# ~175-180 deg = leg hanging straight down (standing). Smaller = knee
# driving up toward the chest.
RAISE_ANGLE_MAX = 125.0  # angle must drop to/below this to confirm "up"
DOWN_RESET_ANGLE_MIN = 150.0  # must rise back above this to re-arm that leg
DEEP_STRIKE_ANGLE = 100.0  # at/below this -> "good" depth quality bonus
CONFIRM_FRAMES = 1

# While one knee strikes, the support leg should stay relatively extended
# — this is what distinguishes a knee strike from a bilateral movement
# (e.g. a squat) where both hip-flexion angles drop together. Kept
# generous on purpose so a naturally soft support knee doesn't block a
# valid rep.
SUPPORT_LEG_MIN_ANGLE = 140.0

MIN_REP_INTERVAL_S = 0.12
MAX_TORSO_LEAN_DEG = 30.0

POSITION_CONFIRM_FRAMES = 4
POSITION_GRACE_FRAMES = 5
FRAME_EDGE_MARGIN = 0.035


def _visible(points: tuple[Any, ...], threshold: float = MIN_VISIBILITY) -> bool:
    return all(
        point is not None
        and (
            getattr(point, "visibility", None) is None
            or getattr(point, "visibility", 0.0) >= threshold
        )
        for point in points
    )


def _looks_like_person(landmarks: list[Any]) -> bool:
    if len(landmarks) < 33:
        return False
    visible_core = sum(
        1
        for index in CORE_LANDMARKS
        if getattr(landmarks[index], "visibility", 0.0) >= PERSON_VISIBILITY
    )
    return visible_core >= 3


def _distance(a: Any, b: Any) -> float:
    return math.hypot(float(a.x) - float(b.x), float(a.y) - float(b.y))


def _midpoint(a: Any, b: Any) -> tuple[float, float]:
    return ((float(a.x) + float(b.x)) / 2.0, (float(a.y) + float(b.y)) / 2.0)


def _angle_at(a: Any, b: Any, c: Any) -> Optional[float]:
    first = (float(a.x) - float(b.x), float(a.y) - float(b.y))
    second = (float(c.x) - float(b.x), float(c.y) - float(b.y))
    first_len = math.hypot(*first)
    second_len = math.hypot(*second)
    if first_len < 1e-7 or second_len < 1e-7:
        return None
    cosine = (first[0] * second[0] + first[1] * second[1]) / (first_len * second_len)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _view_mode(shoulder_width: float, torso_length: float) -> str:
    ratio = shoulder_width / max(torso_length, 1e-7)
    if ratio >= 1.02:
        return "front"
    if ratio <= 0.58:
        return "side"
    return "angled"


def _torso_lean(
    mid_shoulder: tuple[float, float], mid_hip: tuple[float, float]
) -> float:
    dx = mid_hip[0] - mid_shoulder[0]
    dy = mid_hip[1] - mid_shoulder[1]
    return math.degrees(math.atan2(abs(dx), max(abs(dy), 1e-7)))


def _framing_feedback(points: list[Any]) -> Optional[str]:
    for point in points:
        if point.x < FRAME_EDGE_MARGIN or point.x > 1.0 - FRAME_EDGE_MARGIN:
            return (
                "Move back so your knee stays inside the frame at the top of the drive."
            )
        if point.y < FRAME_EDGE_MARGIN or point.y > 1.0 - FRAME_EDGE_MARGIN:
            return "Keep your full body inside the frame, head to feet."
    return None


def _tempo(duration: Optional[float]) -> Optional[str]:
    if duration is None:
        return None
    if duration < 0.15:
        return "too_fast"
    if duration < 0.35:
        return "fast"
    if duration < 1.2:
        return "good"
    if duration < 2.5:
        return "slow"
    return "too_slow"


class _LegState:
    """Independent hysteresis state machine for one leg."""

    __slots__ = ("armed", "last_rep_time")

    def __init__(self):
        self.armed = True
        self.last_rep_time: Optional[float] = None


class KneeStrikeAnalyzer:
    """Stateful front-view knee strike counter — either leg counts."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps
        self.rep_count = 0
        self.left_reps = 0
        self.right_reps = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.stage = "setup"
        self.ready = False

        self._position_good_streak = 0
        self._position_bad_streak = 0
        self._session_start_time: Optional[float] = None

        self._left = _LegState()
        self._right = _LegState()

    def _complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _base_response(self, elapsed: float) -> dict[str, Any]:
        return {
            "detector_version": DETECTOR_VERSION,
            "pose_detected": False,
            "view_mode": None,
            "view_advisory": None,
            "position_ok": False,
            "position_message": None,
            "ready": self.ready,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "left_reps": self.left_reps,
            "right_reps": self.right_reps,
            "target_reps": self.target_reps,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "session_complete": self._complete(),
            "rep_completed": False,
            "rep_duration": None,
            "rep_avg_speed": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "rep_side": None,
            "left_hip_angle": None,
            "right_hip_angle": None,
            "left_angle": None,
            "right_angle": None,
            "torso_lean_deg": None,
            "alignment_ok": False,
            "alignment_issue": None,
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

    def _reset_zone_state(self) -> None:
        self._left = _LegState()
        self._right = _LegState()

    def update(
        self, landmarks: Optional[list[Any]], timestamp_ms: int
    ) -> dict[str, Any]:
        timestamp_s = timestamp_ms / 1000.0
        if self._session_start_time is None:
            self._session_start_time = timestamp_s
        elapsed = max(0.0, timestamp_s - self._session_start_time)
        response = self._base_response(elapsed)

        if landmarks is None or not _looks_like_person(landmarks):
            response["feedback"] = (
                "No person detected — face the camera with your full body visible."
            )
            self._position_good_streak = 0
            self._position_bad_streak += 1
            if self._position_bad_streak >= POSITION_GRACE_FRAMES:
                if self.ready:
                    self._reset_zone_state()
                self.ready = False
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        # Visibility informs messaging/lock-on only — never discards a
        # frame outright. See module docstring point 4.
        legs_visible = _visible((l_hip, l_knee), LEG_VISIBILITY) and _visible(
            (r_hip, r_knee), LEG_VISIBILITY
        )
        core_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip), MIN_VISIBILITY)

        shoulder_width = _distance(l_shoulder, r_shoulder)
        torso_length = max(_distance(l_shoulder, l_hip), _distance(r_shoulder, r_hip))
        view_mode = _view_mode(shoulder_width, torso_length)
        view_advisory = (
            None
            if view_mode in ("front", "angled")
            else "Facing the camera more directly will make tracking more reliable."
        )

        framing_message = _framing_feedback(
            [l_shoulder, r_shoulder, l_hip, r_hip, l_knee, r_knee]
        )
        framing_ok = framing_message is None

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        torso_lean = _torso_lean(mid_shoulder, mid_hip)

        left_hip_angle = _angle_at(l_shoulder, l_hip, l_knee)
        right_hip_angle = _angle_at(r_shoulder, r_hip, r_knee)

        position_now_ok = core_visible and legs_visible and framing_ok
        if position_now_ok:
            self._position_good_streak += 1
            self._position_bad_streak = 0
        else:
            self._position_good_streak = 0
            self._position_bad_streak += 1
        if self._position_good_streak >= POSITION_CONFIRM_FRAMES:
            self.ready = True
        elif self._position_bad_streak >= POSITION_GRACE_FRAMES:
            if self.ready:
                self._reset_zone_state()
            self.ready = False

        position_message: Optional[str] = None
        if not core_visible or not legs_visible:
            position_message = (
                "Face the camera so both legs stay visible, head to feet."
            )
        elif not framing_ok:
            position_message = framing_message
        elif not self.ready:
            position_message = (
                "Stand tall for a moment while I lock onto your position."
            )

        position_ok = self.ready and position_now_ok
        can_track = self.ready and framing_ok

        response.update(
            {
                "pose_detected": True,
                "view_mode": view_mode,
                "view_advisory": view_advisory,
                "position_ok": position_ok,
                "position_message": position_message,
                "ready": self.ready,
                "left_hip_angle": round(left_hip_angle, 1) if left_hip_angle else None,
                "right_hip_angle": (
                    round(right_hip_angle, 1) if right_hip_angle else None
                ),
                "left_angle": round(left_hip_angle, 1) if left_hip_angle else None,
                "right_angle": round(right_hip_angle, 1) if right_hip_angle else None,
                "torso_lean_deg": round(torso_lean, 1),
                "framing_ok": framing_ok,
                "framing_message": framing_message,
                "alignment_ok": position_ok and torso_lean <= MAX_TORSO_LEAN_DEG,
                "alignment_issue": (
                    position_message
                    or (
                        "Keep your torso upright — avoid leaning back to throw the knee up."
                        if torso_lean > MAX_TORSO_LEAN_DEG
                        else view_advisory
                    )
                ),
                "low_visibility": not _visible(
                    (l_shoulder, r_shoulder, l_hip, r_hip, l_knee, r_knee), 0.55
                ),
            }
        )

        if not can_track or left_hip_angle is None or right_hip_angle is None:
            response["feedback"] = (
                position_message or "Getting a lock on your position..."
            )
            return response

        # --- Per-leg hysteresis rep detection (either leg counts) ---
        rep_counted = False
        rep_side = None

        def _maybe_strike(
            side: str,
            angle: float,
            support_angle: float,
            state: _LegState,
        ) -> Optional[dict[str, Any]]:
            if state.armed:
                if angle <= RAISE_ANGLE_MAX and support_angle >= SUPPORT_LEG_MIN_ANGLE:
                    too_soon = (
                        state.last_rep_time is not None
                        and (timestamp_s - state.last_rep_time) < MIN_REP_INTERVAL_S
                    )
                    state.armed = False
                    if too_soon:
                        return None
                    duration = (
                        timestamp_s - state.last_rep_time
                        if state.last_rep_time is not None
                        else None
                    )
                    state.last_rep_time = timestamp_s
                    issues = set()
                    if angle > DEEP_STRIKE_ANGLE:
                        issues.add("shallow_strike")
                    if torso_lean > MAX_TORSO_LEAN_DEG:
                        issues.add("torso_lean")
                    return {
                        "side": side,
                        "duration": duration,
                        "quality": "good" if not issues else "needs_improvement",
                    }
            else:
                if angle >= DOWN_RESET_ANGLE_MIN:
                    state.armed = True
            return None

        left_result = _maybe_strike("left", left_hip_angle, right_hip_angle, self._left)
        if left_result:
            rep_counted, rep_side = True, "left"
            self._apply_rep(response, left_result)
        else:
            right_result = _maybe_strike(
                "right", right_hip_angle, left_hip_angle, self._right
            )
            if right_result:
                rep_counted, rep_side = True, "right"
                self._apply_rep(response, right_result)

        self.stage = (
            "left_up"
            if left_hip_angle <= RAISE_ANGLE_MAX
            else "right_up" if right_hip_angle <= RAISE_ANGLE_MAX else "standing"
        )

        if rep_counted:
            response["feedback"] = (
                f"Rep {self.rep_count} — {rep_side} knee strike counted."
            )
        elif position_message:
            response["feedback"] = position_message
        elif self._complete():
            response["feedback"] = (
                f"Target reached — {self.target_reps} knee strikes completed."
            )
        elif self.stage == "standing":
            response["feedback"] = "Drive a knee up toward your chest, either side."
        else:
            response["feedback"] = "Good height — snap it back down and reset."

        response.update(
            {
                "stage": self.stage,
                "rep_count": self.rep_count,
                "left_reps": self.left_reps,
                "right_reps": self.right_reps,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._complete(),
            }
        )
        return response

    def _apply_rep(self, response: dict[str, Any], result: dict[str, Any]) -> None:
        side = result["side"]
        duration = result["duration"]
        quality = result["quality"]

        self.rep_count += 1
        if side == "left":
            self.left_reps += 1
        else:
            self.right_reps += 1
        if quality == "good":
            self.good_reps += 1
        else:
            self.flawed_reps += 1

        response.update(
            {
                "rep_completed": True,
                "rep_side": side,
                "rep_duration": round(duration, 3) if duration else None,
                "rep_avg_speed": (
                    round(1.0 / duration, 2) if duration and duration > 0 else None
                ),
                "rep_classification": _tempo(duration),
                "rep_form_quality": quality,
            }
        )


class KneeStrikeSession:
    """Standalone detector session using one shared PoseEngine."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = KneeStrikeAnalyzer(target_reps)
        self.target_sets = max(1, target_sets)
        self.set_number = max(1, min(set_number, self.target_sets))
        print(
            f"[KneeStrike] session start detector_version={DETECTOR_VERSION} "
            f"RAISE_ANGLE_MAX={RAISE_ANGLE_MAX} "
            f"DOWN_RESET_ANGLE_MIN={DOWN_RESET_ANGLE_MIN} "
            f"SUPPORT_LEG_MIN_ANGLE={SUPPORT_LEG_MIN_ANGLE} "
            f"MIN_REP_INTERVAL_S={MIN_REP_INTERVAL_S}"
        )

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
