"""
Skandha Chakra (shoulder rotation / "shoulder wheel") — continuous
circular-motion rep counter.

What this exercise actually is
-------------------------------
Fingertips stay near the shoulders the whole time; the elbows trace a
large circle — up overhead, out to the sides, back down, and around
again. That's fundamentally different from every other exercise in this
codebase: there's no "down" position and "up" position to build a
hysteresis state machine around, because the motion is a continuous loop
with no natural start/end point.

Why elbow, not wrist
---------------------
The wrist barely moves (it stays near the shoulder throughout), so it
would give a tiny, noisy, ill-defined radius to measure an angle from.
The elbow is the joint that actually sweeps the circle, and
shoulder-to-elbow distance is a fixed rigid-body length (the upper arm),
so it traces a clean, consistent-radius circle regardless of camera
distance or the exact hand position.

How a "rep" is counted
------------------------
Not with position checkpoints — with the same technique a rotary encoder
uses to count revolutions: accumulate the signed angular change of the
elbow around the shoulder, frame to frame, correctly handling the ±180°
wraparound. When that accumulator's magnitude passes `REP_ROTATION_DEG`
(deliberately less than a full 360° — see constants below for why), one
revolution counts, and the threshold's worth is subtracted back out
(keeping the remainder) so a continuous flow of rotations keeps counting
smoothly instead of needing to "reset" between reps.

This is really the same `_rep_angle_acc` technique `pushup.py` /
`leg_raise.py` / `single_leg_squat.py` all already use (accumulate
absolute angle travel, require it clears a minimum before trusting a
rep) — just generalized from a bounded joint angle to an unbounded
rotational one. It has a useful property for free: genuine back-and-forth
wobble never accumulates net rotation in one direction, so it can't
falsely trigger a rep the way a simple "did the angle cross a threshold"
check could.

Both arms, soft sync
----------------------
Both arms rotate together, so — same as `leg_raise.py` (both legs) and
`arnold_press.py` (both arms) — the rep clock runs off the AVERAGE of
both arms' angular delta, `arms_in_sync` is a soft note rather than a
blocker, and if one elbow briefly drops out of tracking the other arm's
motion alone keeps the accumulator moving instead of stalling it.

Direction
----------
Skandha Chakra is commonly done as a set of forward rotations followed
by a set of backward rotations. `direction` ("forward" / "backward" /
"either") lets a caller restrict counting to one rotational sense; left
at "either" (the default), any completed revolution counts regardless of
which way it went, and `rotation_direction` in the response reports which
way the current motion is going for the UI.

Position gate
--------------
Standing or seated both work — this is a warm-up mobility drill, not a
balance or strength exercise — so, same permissive-by-default reasoning
as `arnold_press.py`'s gate, this only disqualifies a frame on clear
evidence the torso is folded over / not upright. It doesn't care about
standing vs. seated at all.

Hips are optional, deliberately. Every other exercise in this codebase
treats shoulders+hips together as "is a person even here" — but this is
a shoulder-only drill, and framing tight on the upper body (cropping the
hips out) is completely normal for it. Requiring hip visibility here
would reject that normal framing outright: the person-detection and
torso-visibility checks only require the shoulders, and the upright
check (which needs a shoulder-to-hip line to measure an incline) simply
defaults to "acceptable" when hips aren't in frame, rather than treating
their absence as a problem to penalize.
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_SHOULDER,
    PoseEngine,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_SHOULDER,
)

# -------------------------------------------------------------------------
# Tunable constants
# -------------------------------------------------------------------------

MIN_LANDMARK_VISIBILITY = 0.4

# A full revolution is 360 degrees, but requiring literally all of it
# rejects a slightly-imperfect circle (arm length differences, camera
# angle, a person who doesn't quite close the loop) the same way an
# overly strict joint-angle threshold rejected valid reps elsewhere in
# this codebase. 300 degrees is generous enough that "clearly did a
# rotation" always counts without being so loose that a big wobble could
# pass as one.
REP_ROTATION_DEG = 300.0

MIN_REP_DURATION = 0.6  # seconds — a real circle isn't instantaneous
MAX_REP_DURATION = 12.0  # this is a slow, deliberate mobility drill

# A per-frame angular-delta cap only makes sense at an assumed, fixed
# frame rate — and this backend's actual inference rate is whatever the
# hardware delivers, which for CPU-bound MediaPipe is very often well
# under 30fps. A fixed "reject deltas over 60 degrees" cap silently
# discards genuine motion whenever a frame takes longer than expected
# (a slower frame covers proportionally more real rotation, not more
# glitch) — which can mean the accumulator never advances no matter how
# correctly the exercise is performed. Capping angular VELOCITY instead,
# using the actual elapsed time between frames, scales correctly
# regardless of the real frame rate.
MAX_TRUSTED_ANGULAR_VELOCITY_DEG_PER_SEC = (
    900.0  # 2.5 full rotations/sec — generous ceiling
)
MIN_TRUSTED_FRAME_DT = (
    1.0 / 60.0
)  # floor so a near-zero dt can't make the cap collapse to ~0

# Left/right symmetry — "arms out of sync" soft note, not a blocker.
SYNC_SOFT_TOLERANCE_DEG = 35.0

VALID_DIRECTIONS = ("forward", "backward", "either")

# Position gate — permissive by default, standing or seated both valid.
# Same reasoning as `arnold_press.py`'s gate.
TORSO_INCLINE_NOT_UPRIGHT_MAX_DEG = 40.0
STABLE_FRAMES = 3
GRACE_FRAMES = 24  # ~0.8s at 30fps — absorbs real tracking noise/occlusion

# Camera framing
FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.95
BBOX_TOO_FAR = 0.15


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

def nameFunction():
    for y in VALID_DIRECTIONS:
        return 


def _midpoint(a, b) -> _Point:
    return _Point((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _looks_like_a_person(landmarks) -> bool:
    # Deliberately shoulders-only, not the shoulders+hips check the other
    # exercises use. Skandha Chakra is commonly filmed tighter on the
    # upper body (it's a shoulder drill — there's no reason to frame the
    # hips), so requiring hip visibility here would reject perfectly
    # normal framing and silently block every frame before it ever
    # reaches the rotation-counting logic.
    return (
        landmarks[LEFT_SHOULDER].visibility is not None
        and landmarks[LEFT_SHOULDER].visibility > 0.6
        and landmarks[RIGHT_SHOULDER].visibility is not None
        and landmarks[RIGHT_SHOULDER].visibility > 0.6
    )


def _torso_incline_deg(mid_shoulder, mid_hip) -> Optional[float]:
    """0deg = torso lying flat/horizontal, 90deg = torso perfectly vertical."""
    dx = mid_hip.x - mid_shoulder.x
    dy = mid_hip.y - mid_shoulder.y
    if dx == 0 and dy == 0:
        return None
    return math.degrees(math.atan2(abs(dy), max(abs(dx), 1e-9)))


def _assess_upright_position(torso_incline_deg: Optional[float]) -> tuple[bool, bool]:
    """(is_acceptable, is_clearly_not_upright) — permissive by default,
    same reasoning as `arnold_press.py`'s gate."""
    not_upright = (
        torso_incline_deg is not None
        and torso_incline_deg <= TORSO_INCLINE_NOT_UPRIGHT_MAX_DEG
    )
    return (not not_upright), not_upright


def _framing_feedback(points) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return "You're partly out of frame — step back, arms need room to circle fully."

    if len(points) < 4:
        return None

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "You're too close to the camera — step back so your arms have room to circle."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


def _angle_delta_deg(new_deg: float, old_deg: float) -> float:
    """Minimal signed angular step from old to new, correctly handling
    the wraparound at +/-180 degrees. This is the crux of the whole
    rotation-counting approach — see module docstring."""
    delta = new_deg - old_deg
    while delta > 180.0:
        delta -= 360.0
    while delta < -180.0:
        delta += 360.0
    return delta


class SkandhaChakraAnalyzer:
    """Stateful bilateral shoulder-rotation ("arm circle") rep counter."""

    def __init__(self, target_reps: Optional[int] = None, direction: str = "either"):
        self.target_reps = target_reps
        self.direction = direction if direction in VALID_DIRECTIONS else "either"

        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        self._last_left_theta: Optional[float] = None
        self._last_right_theta: Optional[float] = None
        self._last_left_theta_t: Optional[float] = None
        self._last_right_theta_t: Optional[float] = None
        self.left_theta: Optional[float] = None
        self.right_theta: Optional[float] = None

        self.cumulative_rotation = (
            0.0  # signed, degrees, resets by +/-REP_ROTATION_DEG per rep
        )
        self.rep_start_time: Optional[float] = None
        self._current_rep_issues: set[str] = set()

        self.session_start_time: Optional[float] = None

        self._floor_streak = 0
        self._bad_streak = 0
        self.ready = False

    # ---------------------------------------------------------------
    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 5.0:
            return "too_slow"
        if duration >= 3.0:
            return "slow"
        if duration >= 1.2:
            return "good"
        if duration >= 0.6:
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
            "ready": self.ready,
            "stage": "rotating" if self.ready else "waiting",
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "rep_completed": False,
            "rep_classification": None,
            "rep_form_quality": None,
            "position_ok": False,
            "position_message": None,
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
            # extra fields
            "left_arm_angle": None,
            "right_arm_angle": None,
            "arms_in_sync": True,
            "rotation_progress": 0.0,
            "rotation_direction": None,
            "target_direction": self.direction,
            "rep_duration": None,
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = "No person detected — step into frame."
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]

        # Shoulders are the anchor point this whole exercise is measured
        # from; hips are optional (see `_looks_like_a_person` above) —
        # used for the upright check when visible, but their absence must
        # not block anything.
        shoulders_visible = _visible((l_shoulder, r_shoulder))
        if not shoulders_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your shoulders clearly — make sure both are in frame."
            )
            return response

        response["pose_detected"] = True

        hips_visible = _visible((l_hip, r_hip))
        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        if hips_visible:
            mid_hip = _midpoint(l_hip, r_hip)
            torso_incline = _torso_incline_deg(mid_shoulder, mid_hip)
        else:
            # Can't measure incline without hips — default to acceptable
            # rather than penalizing what simply isn't in frame, same
            # permissive-by-default reasoning as the rest of this gate.
            torso_incline = None

        bbox_points = [
            p
            for p in (l_shoulder, r_shoulder, l_hip, r_hip, l_elbow, r_elbow)
            if _visible((p,))
        ]
        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        is_acceptable, not_upright = _assess_upright_position(torso_incline)

        if is_acceptable:
            self._floor_streak += 1
            self._bad_streak = 0
        else:
            self._floor_streak = 0
            self._bad_streak += 1

        if self._floor_streak >= STABLE_FRAMES:
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES:
            self.ready = False

        position_ok = self.ready
        response["position_ok"] = position_ok
        response["ready"] = self.ready
        response["stage"] = "rotating" if position_ok else "waiting"

        if not_upright and not position_ok:
            position_message = (
                "Sit or stand upright, facing the camera, to begin — "
                "standing or seated both work."
            )
        elif not position_ok:
            position_message = (
                "Get into an upright standing or seated position to begin."
            )
        else:
            position_message = None
        response["position_message"] = position_message

        # ---- per-arm elbow angle around the shoulder ----
        left_ok = _visible((l_shoulder, l_elbow))
        right_ok = _visible((r_shoulder, r_elbow))

        left_theta = (
            math.degrees(math.atan2(l_elbow.y - l_shoulder.y, l_elbow.x - l_shoulder.x))
            if left_ok
            else None
        )
        right_theta = (
            math.degrees(math.atan2(r_elbow.y - r_shoulder.y, r_elbow.x - r_shoulder.x))
            if right_ok
            else None
        )

        if left_theta is None and right_theta is None:
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your arms clearly — adjust the camera so both "
                "shoulders and elbows are in frame."
            )
            return response

        response["left_arm_angle"] = (
            round(left_theta, 1) if left_theta is not None else None
        )
        response["right_arm_angle"] = (
            round(right_theta, 1) if right_theta is not None else None
        )

        if left_theta is not None and right_theta is not None:
            circular_diff = abs(_angle_delta_deg(left_theta, right_theta))
            response["arms_in_sync"] = circular_diff <= SYNC_SOFT_TOLERANCE_DEG
        else:
            response["arms_in_sync"] = True  # can't judge with only one arm visible

        feedback = framing_message

        if not position_ok:
            if self.rep_start_time is not None:
                self.rep_start_time = None
                self.cumulative_rotation = 0.0
                self._current_rep_issues = set()
                if feedback is None:
                    feedback = (
                        "Lost upright position mid-rotation — not counted."
                        "Reset and try again."
                    )
            if feedback is None:
                feedback = position_message
            self._last_left_theta = None
            self._last_right_theta = None
            self._last_left_theta_t = None
            self._last_right_theta_t = None
        else:
            # ---- accumulate signed angular delta (the actual rep-counting logic) ----
            deltas = []
            if left_theta is not None and self._last_left_theta is not None:
                dt = max(t - (self._last_left_theta_t or t), MIN_TRUSTED_FRAME_DT)
                d = _angle_delta_deg(left_theta, self._last_left_theta)
                if abs(d) <= MAX_TRUSTED_ANGULAR_VELOCITY_DEG_PER_SEC * dt:
                    deltas.append(d)
            if right_theta is not None and self._last_right_theta is not None:
                dt = max(t - (self._last_right_theta_t or t), MIN_TRUSTED_FRAME_DT)
                d = _angle_delta_deg(right_theta, self._last_right_theta)
                if abs(d) <= MAX_TRUSTED_ANGULAR_VELOCITY_DEG_PER_SEC * dt:
                    deltas.append(d)

            if deltas:
                avg_delta = sum(deltas) / len(deltas)

                if self.rep_start_time is None and abs(avg_delta) > 1e-6:
                    self.rep_start_time = t
                    self._current_rep_issues = set()

                self.cumulative_rotation += avg_delta

                if not response["arms_in_sync"]:
                    self._current_rep_issues.add("arms_not_synced")

                progress = min(1.0, abs(self.cumulative_rotation) / REP_ROTATION_DEG)
                response["rotation_progress"] = round(progress, 2)
                response["rotation_direction"] = (
                    "forward"
                    if self.cumulative_rotation > 0
                    else ("backward" if self.cumulative_rotation < 0 else None)
                )

                if abs(self.cumulative_rotation) >= REP_ROTATION_DEG:
                    rep_completed = True
                    going_direction = (
                        "forward" if self.cumulative_rotation > 0 else "backward"
                    )

                    rep_duration = (
                        (t - self.rep_start_time)
                        if self.rep_start_time is not None
                        else None
                    )

                    direction_ok = (
                        self.direction == "either" or self.direction == going_direction
                    )

                    valid = (
                        direction_ok
                        and rep_duration is not None
                        and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                    )

                    if valid:
                        self.rep_count += 1
                        rep_class = self._classify_tempo(rep_duration)

                        if self._current_rep_issues:
                            rep_form_quality = "needs_improvement"
                            self.flawed_reps += 1
                            issue_text = ", ".join(
                                i.replace("_", " ")
                                for i in sorted(self._current_rep_issues)
                            )
                            feedback = (
                                f"Rep {self.rep_count} counted ({going_direction}), "
                                f"but watch your form ({issue_text})."
                            )
                        else:
                            rep_form_quality = "good"
                            self.good_reps += 1
                            feedback = (
                                f"Clean {going_direction} rotation — full circle "
                                f"({rep_duration:.2f}s)."
                            )
                    else:
                        rep_completed = False
                        rep_class = None
                        rep_form_quality = None
                        if not direction_ok:
                            feedback = (
                                f"That was a {going_direction} rotation, but this set "
                                f"is {self.direction} only — not counted."
                            )
                        elif (
                            rep_duration is not None and rep_duration < MIN_REP_DURATION
                        ):
                            feedback = (
                                "Too fast — that circle wasn't counted, slow it down."
                            )
                        else:
                            feedback = "That circle took too long — not counted. Keep it flowing."

                    # Keep the overshoot as a head start on the next
                    # revolution instead of hard-resetting to zero — same
                    # "encoder" behavior a continuous rotation should have.
                    self.cumulative_rotation -= REP_ROTATION_DEG * (
                        1 if self.cumulative_rotation > 0 else -1
                    )
                    self.rep_start_time = t
                    self._current_rep_issues = set()

                    response.update(
                        {
                            "rep_count": self.rep_count,
                            "good_reps": self.good_reps,
                            "flawed_reps": self.flawed_reps,
                            "session_complete": self._is_complete(),
                            "rep_completed": rep_completed,
                            "rep_classification": rep_class,
                            "rep_form_quality": rep_form_quality,
                            "feedback": feedback,
                        }
                    )

            if response["feedback"] is None and feedback is not None:
                response["feedback"] = feedback
            elif response["feedback"] is None and not response["arms_in_sync"]:
                response["feedback"] = "Keep both arms circling together, same pace."

            if left_theta is not None:
                self._last_left_theta = left_theta
                self._last_left_theta_t = t
            if right_theta is not None:
                self._last_right_theta = right_theta
                self._last_right_theta_t = t

        if response["feedback"] is None and not self.ready:
            response["feedback"] = (
                "Get upright, arms relaxed, to start — I'll count each full "
                "circle automatically."
            )
        if response["feedback"] is None:
            response["feedback"] = "Good — keep the circle going."

        return response


class SkandhaChakraSession:
    """Full Skandha Chakra session: one shared pose model + one analyzer.

    Same convention as `ArnoldPressSession` / `LegRaiseSession` —
    `target_reps` / `target_sets` / `set_number` are the coach-assigned
    plan, and `direction` pins which rotational sense counts (or "either"
    for both). The frontend never decides on its own whether a
    set/exercise is done; `session_complete` and `exercise_complete` are
    computed here.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
        direction: str = "either",
    ):
        self.engine = PoseEngine()
        self.analyzer = SkandhaChakraAnalyzer(target_reps, direction=direction)
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
