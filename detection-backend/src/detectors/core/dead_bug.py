"""
Dead bug counter.

Design
------
A dead bug rep isn't "did a limb move" — it's a specific coordinated
movement: lying on your back, tabletop position (knees bent over hips,
arms reaching straight up), you extend ONE arm overhead and the
*opposite-side* leg straight out, together, while everything else stays
put and your lower back stays flat on the floor, then return to tabletop.
That's the whole exercise, and every common way to cheat it maps to one
specific piece of that definition being skipped:

  * Moving only one limb (e.g. just an arm) -> not a rep.
  * Moving the *same-side* arm and leg together -> not a rep (this is a
    dead bug done backwards; the point is the diagonal/contralateral
    connection).
  * Moving all four limbs at once (turning it into a static superman-ish
    reach) -> not a rep.
  * Letting the lower back arch / hips lift or shift as the limbs extend
    (the #1 real-world dead bug cheat, since it lets hip flexors take
    over instead of the core) -> not a rep.
  * Flailing the limbs out and back in an instant -> not a rep (too fast
    to be a controlled, core-braced movement).

So instead of counting per-limb like the jab (per-arm) or mountain
climber (per-leg), this analyzer runs two **diagonal-pair** state
machines — right-arm+left-leg, and left-arm+right-leg — and a rep is only
counted for a diagonal once *both* of its limbs have gone
tabletop -> extended -> tabletop together, inside a normal tempo, with
the hips staying essentially planted, and without the other diagonal's
limbs joining in. Get the movement right and it counts; skip any one of
those pieces and it quietly doesn't, with feedback saying which piece.

Per-limb signal
----------------
  * Arm: `shoulder_angle` = angle(hip, shoulder, elbow). Tabletop (arm
    reaching straight up off the shoulder) reads as a smallish angle
    between the hip-shoulder line and the shoulder-elbow line; reaching
    the arm back overhead opens that angle up a lot.
  * Leg: `hip_angle` = angle(shoulder, hip, knee) — the same joint angle
    the mountain-climber analyzer uses, just with rest/extended flipped:
    tabletop (thigh raised, hip flexed) is the *small*-angle state here,
    and reaching the leg out straight is the *large*-angle state.

Anti-cheat checks
------------------
  * **Pairing**: a diagonal only enters its "extended" stage once *both*
    of its limbs individually read as extended — a single limb moving
    can never satisfy that on its own, and the wrong pairing (same-side
    arm+leg) never satisfies *either* diagonal's condition, so it's
    structurally impossible to count, not just penalized after the fact.
  * **Cross-contamination**: while one diagonal is in its extended stage,
    if either limb of the *other* diagonal also reads as extended, the
    attempt is invalidated (all-four-limbs-moving doesn't count).
  * **Hip stability**: the mid-hip point's position is snapshotted the
    instant a diagonal starts extending; if it drifts more than a small
    tolerance (normalized by torso length) before the diagonal returns to
    tabletop, the attempt is invalidated — this is the back-arch /
    hip-shift catch.
  * **Tempo**: too fast (a flick, not a controlled rep) or too slow (not
    a continuous movement) invalidates the attempt.

All of this is evaluated only once the movement *finishes* (back to
tabletop) — a rep is never counted mid-motion, so there's nothing to
silently reverse.
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    LEFT_WRIST,
    PoseEngine,
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

# Arm signal: angle(hip, shoulder, elbow), degrees.
ARM_REST_ANGLE_MAX = 110.0  # at/below this, arm reads as "tabletop" (reaching up)
ARM_EXTENDED_ANGLE_MIN = 150.0  # at/above this, arm reads as "extended" overhead

# Leg signal: angle(shoulder, hip, knee), degrees.
LEG_REST_ANGLE_MAX = 110.0  # at/below this, leg reads as "tabletop" (hip flexed)
LEG_EXTENDED_ANGLE_MIN = 150.0  # at/above this, leg reads as "extended" out straight

# A controlled dead bug rep is slower than a jab or mountain-climber
# drive — it's a braced, deliberate reach, not an explosive movement.
MIN_REP_DURATION = 0.35  # seconds — faster reads as a flick, not a controlled rep
MAX_REP_DURATION = 6.0  # seconds — slower than this isn't one continuous movement

# How far the mid-hip point is allowed to drift (normalized by torso
# length) between a diagonal starting to extend and returning to
# tabletop, before it reads as the lower back arching / hips shifting.
HIP_DRIFT_TOLERANCE = 0.14

# -------------------------------------------------------------------------
# Lying-down base position gating (same idea as the mountain-climber's
# plank gate: only progress the rep state machines once the person is
# confirmed horizontal, filmed from the side).
# -------------------------------------------------------------------------
TORSO_INCLINE_MAX_DEG = 55.0
STABLE_STANCE_FRAMES = 3
GRACE_FRAMES = 15

FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.97
BBOX_TOO_FAR = 0.10


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
    # Filmed side-on, lying down — the far shoulder/hip is routinely
    # occluded, same reasoning as the plank-hold / mountain-climber gates.
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
            return "You're partly out of frame — reposition so your whole body and reach are visible."

    if len(points) < 4:
        return None

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return (
            "You're too close to the camera — back up so your full reach fits in frame."
        )
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class _LimbTracker:
    """Tracks one limb's rest/extended state off a single joint angle.

    Generic over arm-vs-leg: the caller passes in which thresholds apply
    (arm angles read low-at-rest/high-extended, and so do leg angles, so
    both limb kinds share this one implementation).
    """

    def __init__(self, rest_max: float, extended_min: float):
        self.rest_max = rest_max
        self.extended_min = extended_min
        self.smoothed_angle: Optional[float] = None
        self.extended = False
        self.extend_start_time: Optional[float] = None

    def update(self, t: float, a, b, c) -> None:
        if not _visible((a, b, c)):
            return
        raw = _angle_deg(a, b, c)
        self.smoothed_angle = (
            raw
            if self.smoothed_angle is None
            else 0.6 * raw + 0.4 * self.smoothed_angle
        )

        was_extended = self.extended
        if self.extended:
            # Hysteresis: once extended, only drop back to "rest" once
            # clearly back under the rest threshold (not just below the
            # extended threshold), so a value hovering in the middle
            # can't flicker the state twice as fast as it should.
            if self.smoothed_angle <= self.rest_max:
                self.extended = False
        else:
            if self.smoothed_angle >= self.extended_min:
                self.extended = True

        if self.extended and not was_extended:
            self.extend_start_time = t


class _DiagonalTracker:
    """One contralateral pair (e.g. right arm + left leg).

    Only becomes "active" (starts a rep attempt) once *both* limbs read
    as extended — a single limb, or the wrong-side pairing, can never
    trigger this on its own. While active, tracks hip drift and whether
    the *other* diagonal's limbs stayed put; both feed into whether the
    attempt is valid once it finishes.
    """

    def __init__(self, label: str, arm: _LimbTracker, leg: _LimbTracker):
        self.label = label  # e.g. "right_arm_left_leg"
        self.arm = arm
        self.leg = leg
        self.stage = "rest"
        self.count = 0
        self.invalid_attempts = 0
        self.start_time: Optional[float] = None
        self.baseline_hip: Optional[_Point] = None
        self.max_hip_drift = 0.0
        self.cross_contaminated = False
        self.last_invalid_reason: Optional[str] = None

    def update(
        self,
        t: float,
        mid_hip: _Point,
        torso_length: float,
        other_diag_active: bool,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"rep_completed": False, "reason": None}

        both_extended = self.arm.extended and self.leg.extended

        if self.stage == "rest":
            if both_extended:
                self.stage = "extended"
                # Use whichever limb started extending first as the
                # attempt's start time, so tempo is judged on the whole
                # movement, not just the moment the second limb catches up.
                starts = [
                    s
                    for s in (self.arm.extend_start_time, self.leg.extend_start_time)
                    if s is not None
                ]
                self.start_time = min(starts) if starts else t
                self.baseline_hip = _Point(mid_hip.x, mid_hip.y)
                self.max_hip_drift = 0.0
                self.cross_contaminated = False
        elif self.stage == "extended":
            if self.baseline_hip is not None:
                drift = _dist(mid_hip, self.baseline_hip) / max(torso_length, 1e-6)
                self.max_hip_drift = max(self.max_hip_drift, drift)
            if other_diag_active:
                self.cross_contaminated = True

            if not both_extended:
                # Movement finished (at least one limb came back to rest)
                # — judge the whole attempt now.
                duration = (
                    (t - self.start_time) if self.start_time is not None else None
                )
                reason = None
                if duration is None or not (
                    MIN_REP_DURATION <= duration <= MAX_REP_DURATION
                ):
                    reason = "tempo"
                elif self.cross_contaminated:
                    reason = "cross_limb"
                elif self.max_hip_drift > HIP_DRIFT_TOLERANCE:
                    reason = "hip_drift"

                if reason is None:
                    self.count += 1
                    result["rep_completed"] = True
                else:
                    self.invalid_attempts += 1
                    self.last_invalid_reason = reason
                    result["reason"] = reason

                self.stage = "rest"
                self.start_time = None
                self.baseline_hip = None
                self.max_hip_drift = 0.0
                self.cross_contaminated = False

        return result


_INVALID_MESSAGES = {
    "tempo": "Slow down and control the movement — that was too quick to count as a braced rep.",
    "cross_limb": "Keep the other arm and leg still in tabletop while you reach — all four limbs moved together.",
    "hip_drift": "Keep your lower back flat on the floor — your hips shifted, that's the core letting go.",
}


class DeadBugAnalyzer:
    """Stateful dead-bug counter — tracks both contralateral diagonals."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.right_arm = _LimbTracker(ARM_REST_ANGLE_MAX, ARM_EXTENDED_ANGLE_MIN)
        self.left_arm = _LimbTracker(ARM_REST_ANGLE_MAX, ARM_EXTENDED_ANGLE_MIN)
        self.right_leg = _LimbTracker(LEG_REST_ANGLE_MAX, LEG_EXTENDED_ANGLE_MIN)
        self.left_leg = _LimbTracker(LEG_REST_ANGLE_MAX, LEG_EXTENDED_ANGLE_MIN)

        # Standard contralateral dead bug pairing: right arm with left
        # leg, left arm with right leg.
        self.diag_rl = _DiagonalTracker(
            "right_arm_left_leg", self.right_arm, self.left_leg
        )
        self.diag_lr = _DiagonalTracker(
            "left_arm_right_leg", self.left_arm, self.right_leg
        )

        self._lying_streak = 0
        self._bad_streak = 0
        self.ready = False

        self.session_start_time: Optional[float] = None

    def _is_complete(self) -> bool:
        total = self.diag_rl.count + self.diag_lr.count
        return self.target_reps is not None and total >= self.target_reps

    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        total_reps = self.diag_rl.count + self.diag_lr.count

        response: dict[str, Any] = {
            "pose_detected": False,
            "ready": self.ready,
            "stance_ok": False,
            "stance_message": None,
            "framing_ok": True,
            "framing_message": None,
            "rep_count": total_reps,
            "right_arm_left_leg_count": self.diag_rl.count,
            "left_arm_right_leg_count": self.diag_lr.count,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_diagonal": None,
            "invalid_attempt": False,
            "invalid_reason": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = (
                "No person detected — lie down sideways to the camera."
            )
            return response

        response["pose_detected"] = True

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]

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
        is_lying_down = (
            torso_incline is not None and torso_incline <= TORSO_INCLINE_MAX_DEG
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
                l_knee,
                r_knee,
            )
            if _visible((p,))
        ]
        bbox_points = [_Point(p.x, p.y) for p in bbox_candidates]
        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        if is_lying_down:
            self._lying_streak += 1
            self._bad_streak = 0
        else:
            self._lying_streak = 0
            self._bad_streak += 1

        if self._lying_streak >= STABLE_STANCE_FRAMES:
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES:
            self.ready = False

        response["ready"] = self.ready
        response["stance_ok"] = self.ready
        if not is_lying_down:
            response["stance_message"] = (
                "Lie on your back, sideways to the camera, knees stacked "
                "over hips and arms reaching straight up to start."
            )
        elif not self.ready:
            response["stance_message"] = (
                "Hold your tabletop position steady to start counting…"
            )

        # ---- update all four limbs (only progresses state once ready) ----
        if self.ready:
            self.right_arm.update(t, r_hip, r_shoulder, r_elbow)
            self.left_arm.update(t, l_hip, l_shoulder, l_elbow)
            self.right_leg.update(t, r_shoulder, r_hip, r_knee)
            self.left_leg.update(t, l_shoulder, l_hip, l_knee)
        else:
            # Keep angles smoothed even while not ready, but don't let
            # stage transitions happen off a stance that isn't confirmed.
            for limb, pts in (
                (self.right_arm, (r_hip, r_shoulder, r_elbow)),
                (self.left_arm, (l_hip, l_shoulder, l_elbow)),
                (self.right_leg, (r_shoulder, r_hip, r_knee)),
                (self.left_leg, (l_shoulder, l_hip, l_knee)),
            ):
                if _visible(pts):
                    raw = _angle_deg(*pts)
                    limb.smoothed_angle = (
                        raw
                        if limb.smoothed_angle is None
                        else 0.6 * raw + 0.4 * limb.smoothed_angle
                    )

        rl_active = self.diag_rl.stage == "extended"
        lr_active = self.diag_lr.stage == "extended"

        rl_result = self.diag_rl.update(
            t, mid_hip, torso_length, other_diag_active=lr_active
        )
        lr_result = self.diag_lr.update(
            t, mid_hip, torso_length, other_diag_active=rl_active
        )

        response["rep_count"] = self.diag_rl.count + self.diag_lr.count
        response["right_arm_left_leg_count"] = self.diag_rl.count
        response["left_arm_right_leg_count"] = self.diag_lr.count
        response["session_complete"] = self._is_complete()

        feedback = framing_message

        for diag_label, r in (
            ("right_arm_left_leg", rl_result),
            ("left_arm_right_leg", lr_result),
        ):
            if r["rep_completed"]:
                response["rep_completed"] = True
                response["rep_diagonal"] = diag_label
                side = (
                    "right arm + left leg"
                    if diag_label == "right_arm_left_leg"
                    else "left arm + right leg"
                )
                feedback = f"Nice — {side} counted."
            elif r["reason"] is not None:
                response["invalid_attempt"] = True
                response["invalid_reason"] = r["reason"]
                feedback = _INVALID_MESSAGES.get(
                    r["reason"],
                    "That attempt didn't count — reset to tabletop and try again.",
                )

        if feedback is None and not self.ready:
            feedback = response["stance_message"] or (
                "Get into tabletop position, lying on your side to the camera."
            )
        if feedback is None:
            feedback = (
                "Good tabletop — reach one arm and the opposite leg out together."
            )

        response["feedback"] = feedback
        return response


class DeadBugSession:
    """Full dead-bug session: one shared pose model + one analyzer.

    Mirrors `MountainClimberSession` / `JabSession` — `target_reps` /
    `target_sets` / `set_number` are the coach-assigned plan, supplied by
    the websocket route from query params. `session_complete` /
    `exercise_complete` are computed here, never on the frontend.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = DeadBugAnalyzer(target_reps)
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
