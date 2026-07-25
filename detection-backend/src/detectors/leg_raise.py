"""
Double / lying leg raise — synchronized two-leg rep counter.

Design
------
This is a REP-COUNTING exercise (not a hold, unlike `plank_hold.py` /
`side_plank.py`), so the state machine follows the same "down"/"up"
hysteresis pattern `pushup.py` uses, driven by an angle at a joint rather
than a raw pixel distance:

    left_leg_angle  = angle(LEFT_SHOULDER,  LEFT_HIP,  LEFT_ANKLE)
    right_leg_angle = angle(RIGHT_SHOULDER, RIGHT_HIP, RIGHT_ANKLE)

Lying supine with legs flat and in line with the torso, this angle reads
close to a straight 180°. As the legs lift toward vertical it falls
toward ~90° (less if hip flexion goes past vertical). That is exactly the
same "angle at a joint, hysteresis band drives the rep" technique
`pushup.py` uses for the elbow — reused here instead of a raw pixel
distance because it stays meaningful across side, front, and angled
camera placements (a joint angle degrades gracefully with mild
foreshortening; a raw pixel gap does not).

Both legs must be tracked and averaged together — this deliberately does
NOT alternate left/right the way a marching or high-knees detector would.
`legs_in_sync` and the per-leg angles are exposed so the frontend can
flag "one leg lagging" as a form note, but the rep clock always runs off
the two-leg average, and a single well-tracked leg (the other briefly
occluded) is enough to keep counting — see `_effective_angles` below.

False-negative aversion
------------------------
Per the product requirement, a correct rep must never go uncounted:

    * The top/bottom angle thresholds are deliberately generous (no
      requirement to reach a strict 90°) — see TOP_ANGLE / BOTTOM_ANGLE.
    * Angle smoothing (`_smooth`) absorbs single-frame landmark jitter
      without adding a multi-frame confirmation delay that could clip a
      fast rep.
    * If one leg's ankle/knee briefly drops out of tracking, the other
      leg's angle carries the rep alone instead of stalling the state
      machine (see `_effective_angles`).
    * A short grace window (`GRACE_FRAMES`) keeps `ready` from flapping
      off on a single bad frame of the lying-position gate.

Camera framing
---------------
Works from a side, front, or angled placement — the shared
`_assess_body_position` gate (same technique as `pushup.py`'s floor
check) just needs the torso to read as roughly horizontal in frame. A
front/top-oblique placement is called out in the UI copy because it's
the only angle that reliably shows both legs at once without one
occluding the other, but the angle math itself does not require it.
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

MIN_LANDMARK_VISIBILITY = 0.4
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)

BOTTOM_ANGLE = 160.0
TOP_ANGLE = 130.0
MIN_ANGLE_DELTA = 12.0
MIN_REP_DURATION = 0.35
MAX_REP_DURATION = 12.0

KNEE_STRAIGHT_MIN_DEG = 155.0
SYNC_SOFT_TOLERANCE_DEG = 18.0
SYNC_BLOCK_TOLERANCE_DEG = 60.0

BACK_ARCH_THRESHOLD = 0.16

TORSO_INCLINE_SUPINE_MAX_DEG = 45.0
TORSO_INCLINE_READY_MAX_DEG = 60.0
TORSO_INCLINE_UPRIGHT_MIN_DEG = 70.0
BBOX_ASPECT_SUPINE_MIN = 1.02
BBOX_ASPECT_UPRIGHT_MAX = 0.85

STABLE_FRAMES = 3
GRACE_FRAMES = 5

FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.95
BBOX_TOO_FAR = 0.15


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


def _bbox_aspect(points: list[_Point]) -> Optional[float]:
    if len(points) < 4:
        return None
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    if height <= 1e-6:
        return None
    return width / height


def _assess_lying_position(
    torso_incline_deg: Optional[float],
    bbox_aspect: Optional[float],
) -> tuple[bool, bool]:
    supine_votes = 0
    upright_votes = 0

    if torso_incline_deg is not None:
        if torso_incline_deg <= TORSO_INCLINE_SUPINE_MAX_DEG:
            supine_votes += 2
        elif torso_incline_deg >= TORSO_INCLINE_UPRIGHT_MIN_DEG:
            upright_votes += 2

    if bbox_aspect is not None:
        if bbox_aspect >= BBOX_ASPECT_SUPINE_MIN:
            supine_votes += 1
        elif bbox_aspect <= BBOX_ASPECT_UPRIGHT_MAX:
            upright_votes += 1

    is_supine = supine_votes >= 2 and upright_votes == 0
    is_upright = upright_votes >= 2 and supine_votes == 0
    return is_supine, is_upright


def _framing_feedback(points: list[_Point]) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — reposition so your whole body is visible."
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


class LegRaiseAnalyzer:
    """Stateful double-leg-raise rep counter + supine-position gate."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        variation: str = "straight",
    ):
        self.target_reps = target_reps
        self.variation = (
            variation if variation in ("straight", "bent_knees") else "straight"
        )

        self.stage = "down"
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        self.smoothed_angle: Optional[float] = None
        self.smoothed_left: Optional[float] = None
        self.smoothed_right: Optional[float] = None
        self.last_angle: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None
        self.rep_start_time: Optional[float] = None
        self._rep_angle_acc = 0.0
        self.angle_smooth_alpha = 0.55

        self.session_start_time: Optional[float] = None

        self._floor_streak = 0
        self._bad_streak = 0
        self.ready = False

        self._current_rep_issues: set[str] = set()

    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 4.0:
            return "too_slow"
        if duration >= 2.2:
            return "slow"
        if duration >= 0.8:
            return "good"
        if duration >= 0.35:
            return "fast"
        return "too_fast"

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "ready": self.ready,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "left_leg_angle": None,
            "right_leg_angle": None,
            "legs_in_sync": True,
            "top_reached": False,
            "bottom_reached": False,
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
            "view_mode": None,
            "knee_bend_ok": True,
            "back_control_ok": True,
            "variation": self.variation,
            "rep_duration": None,
            "rep_avg_speed": None,
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = "No person detected — step into frame."
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
        if not torso_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your torso — make sure your shoulders and hips are both in frame."
            )
            return response

        response["pose_detected"] = True

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)
        shoulder_width = _dist(l_shoulder, r_shoulder)
        view_ratio = shoulder_width / torso_length
        view_mode = (
            "front"
            if view_ratio >= 0.85
            else ("side" if view_ratio <= 0.45 else "angled")
        )
        response["view_mode"] = view_mode

        torso_incline = _torso_incline_deg(mid_shoulder, mid_hip)

        bbox_candidates = [
            p
            for p in (
                l_shoulder,
                r_shoulder,
                l_hip,
                r_hip,
                l_knee,
                r_knee,
                l_ankle,
                r_ankle,
            )
            if _visible((p,))
        ]
        bbox_points = [_Point(p.x, p.y) for p in bbox_candidates]
        bbox_aspect = _bbox_aspect(bbox_points)

        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        is_supine, is_upright = _assess_lying_position(torso_incline, bbox_aspect)

        if is_supine or (
            torso_incline is not None and torso_incline <= TORSO_INCLINE_READY_MAX_DEG
        ):
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

        if is_upright:
            position_message = "You're upright — lie down on your back on the mat, legs extended, arms by your sides or under your glutes."
        elif not position_ok:
            position_message = "Get flat on your back — legs extended and together, camera showing your full body from the side or front."
        else:
            position_message = None
        response["position_message"] = position_message

        left_ok = _visible((l_shoulder, l_hip, l_ankle))
        right_ok = _visible((r_shoulder, r_hip, r_ankle))
        left_knee_ok = _visible((l_hip, l_knee, l_ankle))
        right_knee_ok = _visible((r_hip, r_knee, r_ankle))

        left_far = (
            l_ankle
            if _visible((l_ankle,))
            else (l_knee if _visible((l_knee,)) else None)
        )
        right_far = (
            r_ankle
            if _visible((r_ankle,))
            else (r_knee if _visible((r_knee,)) else None)
        )

        left_angle = (
            _angle_deg(l_shoulder, l_hip, left_far) if left_far is not None else None
        )
        right_angle = (
            _angle_deg(r_shoulder, r_hip, right_far) if right_far is not None else None
        )

        if left_angle is None and right_angle is None:
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your legs clearly — adjust the camera so your hips, knees, and ankles are all in frame."
            )
            return response

        if left_angle is None:
            left_angle = right_angle
            response["low_visibility"] = True
        if right_angle is None:
            right_angle = left_angle
            response["low_visibility"] = True

        self.smoothed_left = (
            left_angle
            if self.smoothed_left is None
            else self.angle_smooth_alpha * left_angle
            + (1 - self.angle_smooth_alpha) * self.smoothed_left
        )
        self.smoothed_right = (
            right_angle
            if self.smoothed_right is None
            else self.angle_smooth_alpha * right_angle
            + (1 - self.angle_smooth_alpha) * self.smoothed_right
        )

        response["left_leg_angle"] = round(self.smoothed_left, 1)
        response["right_leg_angle"] = round(self.smoothed_right, 1)

        raw_angle = (left_angle + right_angle) / 2.0
        self.smoothed_angle = (
            raw_angle
            if self.smoothed_angle is None
            else self.angle_smooth_alpha * raw_angle
            + (1 - self.angle_smooth_alpha) * self.smoothed_angle
        )

        angle_diff = abs(self.smoothed_left - self.smoothed_right)
        legs_in_sync = angle_diff <= SYNC_SOFT_TOLERANCE_DEG
        response["legs_in_sync"] = legs_in_sync

        response["top_reached"] = self.smoothed_angle <= TOP_ANGLE
        response["bottom_reached"] = self.smoothed_angle >= BOTTOM_ANGLE

        knee_bend_ok = True
        if self.variation == "straight":
            knee_angles = []
            if left_knee_ok:
                knee_angles.append(_angle_deg(l_hip, l_knee, l_ankle))
            if right_knee_ok:
                knee_angles.append(_angle_deg(r_hip, r_knee, r_ankle))
            if knee_angles and min(knee_angles) < KNEE_STRAIGHT_MIN_DEG:
                knee_bend_ok = False
        response["knee_bend_ok"] = knee_bend_ok

        back_control_ok = True
        leg_far = None
        if left_far is not None and right_far is not None:
            leg_far = _midpoint(left_far, right_far)
        elif left_far is not None:
            leg_far = left_far
        elif right_far is not None:
            leg_far = right_far

        if position_ok and leg_far is not None:
            dx = leg_far.x - mid_shoulder.x
            if abs(dx) > 0.05:
                frac = (mid_hip.x - mid_shoulder.x) / dx
                if 0.0 <= frac <= 1.0:
                    expected_hip_y = mid_shoulder.y + frac * (
                        leg_far.y - mid_shoulder.y
                    )
                    deviation = abs(mid_hip.y - expected_hip_y) / torso_length
                    if deviation > BACK_ARCH_THRESHOLD:
                        back_control_ok = False
        response["back_control_ok"] = back_control_ok

        feedback = framing_message

        rep_completed = False
        rep_duration = rep_avg_speed = rep_class = rep_form_quality = None

        if not position_ok:
            if self.rep_start_time is not None:
                self.rep_start_time = None
                self._rep_angle_acc = 0.0
                self._current_rep_issues = set()
                if feedback is None:
                    feedback = "Lost lying position mid-rep — not counted. Reset flat on your back and try again."
            if feedback is None:
                feedback = position_message
        else:
            if self.stage == "down" and self.smoothed_angle <= TOP_ANGLE:
                self.stage = "up"
                self.rep_start_time = t
                self._rep_angle_acc = 0.0
                self._current_rep_issues = set()

            if self.last_angle is not None:
                self._rep_angle_acc += abs(self.smoothed_angle - self.last_angle)

            if self.stage == "up":
                if angle_diff > SYNC_BLOCK_TOLERANCE_DEG:
                    self._current_rep_issues.add("legs_not_synced")
                elif not legs_in_sync:
                    self._current_rep_issues.add("legs_not_synced")
                if not knee_bend_ok:
                    self._current_rep_issues.add("knees_bent")
                if not back_control_ok:
                    self._current_rep_issues.add("back_arch")

            if self.stage == "up" and self.smoothed_angle >= BOTTOM_ANGLE:
                self.stage = "down"
                rep_completed = True

            if feedback is None and not legs_in_sync:
                feedback = "Move both legs together — one is lagging behind the other."
            if feedback is None and not knee_bend_ok:
                feedback = "Straighten your knees more if possible."
            if feedback is None and not back_control_ok:
                feedback = "Keep your back from arching — brace your core."

            if rep_completed:
                rep_duration = (
                    (t - self.rep_start_time)
                    if self.rep_start_time is not None
                    else None
                )
                if rep_duration and rep_duration > 0:
                    rep_avg_speed = self._rep_angle_acc / rep_duration

                valid = (
                    rep_duration is not None
                    and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                    and self._rep_angle_acc >= MIN_ANGLE_DELTA
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
                        feedback = f"Rep {self.rep_count} counted, but watch your form ({issue_text})."
                    else:
                        rep_form_quality = "good"
                        self.good_reps += 1
                        if rep_class in ("good", "fast"):
                            feedback = f"Clean rep — lifted and lowered with control ({rep_duration:.2f}s)."
                        else:
                            feedback = (
                                f"Good rep, nice and controlled ({rep_duration:.2f}s)."
                            )
                else:
                    rep_completed = False
                    if rep_duration is not None and rep_duration < MIN_REP_DURATION:
                        feedback = (
                            "Too fast — that one wasn't counted, control the movement."
                        )
                    elif rep_duration is not None and rep_duration > MAX_REP_DURATION:
                        feedback = "That rep took too long — not counted. Keep moving."
                    else:
                        feedback = "Not enough range of motion — not counted."

                self.rep_start_time = None
                self._rep_angle_acc = 0.0
                self._current_rep_issues = set()

        self.last_angle = self.smoothed_angle
        self.last_timestamp_s = t

        if feedback is None and not self.ready:
            feedback = "Lie on your back with your legs extended and together to start counting."
        if feedback is None:
            feedback = "Good form — keep going."

        response.update(
            {
                "stage": self.stage,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_duration": rep_duration,
                "rep_avg_speed": rep_avg_speed,
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "feedback": feedback,
            }
        )
        return response


class LegRaiseSession:
    """Full leg-raise session: one shared pose model + one analyzer."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
        variation: str = "straight",
    ):
        self.engine = PoseEngine()
        self.analyzer = LegRaiseAnalyzer(target_reps, variation=variation)
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
