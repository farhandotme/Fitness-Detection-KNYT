"""
Bulgarian Split Squat (rear-foot-elevated split squat) — a unilateral leg
exercise: rear foot rests on a bench behind you (laces down), front leg
takes ~80-90% of the load, you bend the front knee to lower the rear knee
toward the floor until the front thigh is roughly horizontal, then drive
back up through the front heel. One leg at a time, by design — you do a
full set on one leg, then switch.

Working-leg detection — the #1 requirement for this analyzer
---------------------------------------------------------------
This must count correctly whichever leg the person chooses to lead with,
without them having to tell it which one. The exercise's own setup makes
this easy to detect reliably, in ANY camera angle (side-on or front-on):
the rear foot is elevated on a bench roughly knee-height off the ground,
while the front foot stays on the floor. So whichever ankle reads
meaningfully HIGHER in the frame (smaller y, normalized against torso
length so camera distance doesn't matter) is the rear/elevated leg — the
other one is the working front leg. This is purely a vertical comparison,
so it doesn't depend on the person facing left or right, or on which
physical leg (their left or right) is in front.

Once that's been consistent for a short stable window, the analyzer locks
onto it for the rest of the session (so a brief single-frame tracking
glitch can't suddenly relabel which leg is "front" mid-set) — same
lock-on approach `SidePlankAnalyzer` uses for `active_side`. An optional
`working_leg` constructor argument lets a caller *label* which leg this
session is for (useful for logging "left leg, set 2"), but it is
deliberately never allowed to override what the geometry actually shows —
if it disagrees with what's detected, the analyzer reports the mismatch
in the feedback rather than silently trusting a label that could make the
count wrong for the leg the person is actually using.

Rep signal
----------
The front leg's knee angle (hip-knee-ankle) is the rep signal, same
approach as any squat/lunge tracker: near-straight at the top (standing),
drops to roughly a right angle at the bottom ("front thigh nearly
horizontal" is the standard coaching cue, matching a big rear-knee-height
drop toward the floor). Rep completes on the return to standing after a
confirmed bottom — named "up"/"down" to match how the exercise is
actually coached ("go down into it, drive back up"), same
match-the-exercise's-own-language approach used in the shrug and flutter
kicks analyzers, rather than reusing the push-up state machine's
inverted naming.

Form checks, grounded in the standard coaching cues for this exercise
-----------------------------------------------------------------------
  * Insufficient depth ("cutting the rep short") — the single biggest
    form fault called out across every coaching source for this
    exercise. Tracked as a partial-rep bounce, same pattern used in the
    other angle-based analyzers in this project.
  * Knee traveling well past the toes at the bottom — coaching cue is
    "front shin should stay roughly vertical". Measured directly:
    horizontal offset between the front knee and the front foot's toe,
    in the direction the person is facing.
  * Driving up through the back leg instead of the front leg — a
    specifically-named common mistake. If the rear foot slides on the
    bench during the rep instead of staying put, it's generating force
    rather than just stabilizing, so it's flagged.
  * Leaning noticeably backward, away from the front leg — a
    compensation pattern. NOTE: some forward lean (~20-30 degrees) is
    the textbook-correct position for this exercise, not a fault, so
    forward lean is deliberately NOT flagged — only a lean in the wrong
    direction is.
The horizontal-only checks above (knee-past-toes, lean direction) need a
side-on-ish view to mean anything — from a dead-on front view, "forward"
runs toward the camera, not sideways across the frame, so those two
checks are skipped (not guessed at) when the view reads as "front"; rep
counting itself still works fine in any view since the knee angle is a
real 2D angle regardless of viewing direction.
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_FOOT_INDEX,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_FOOT_INDEX,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
)

# -------------------------------------------------------------------------
# Tunable constants
# -------------------------------------------------------------------------

MIN_LANDMARK_VISIBILITY = 0.4
CORE_LANDMARKS = (LEFT_HIP, RIGHT_HIP, LEFT_SHOULDER, RIGHT_SHOULDER)


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 3


# ---- stance gate: one ankle meaningfully higher than the other confirms
# a genuine rear-foot-elevated setup (vs. two feet flat on the ground,
# which would just be a normal stand / regular squat) ----
REAR_FOOT_ELEVATION_MIN = 0.22  # normalized by torso length
STABLE_STANCE_FRAMES = 8  # consecutive good frames before locking the stance
GRACE_FRAMES = 10  # consecutive bad frames tolerated before un-locking

# View-mode classification (shoulder width / torso length) — used to
# decide whether the horizontal-offset form checks are meaningful.
SIDE_VIEW_RATIO_MAX = 0.45
FRONT_VIEW_RATIO_MIN = 0.85

# ---- front-leg knee angle thresholds (angle at knee: hip-knee-ankle) ----
TOP_KNEE_ANGLE_MIN = 160.0  # standing tall
BOTTOM_KNEE_ANGLE_MAX = 105.0  # "front thigh roughly horizontal" — reaching
# this or lower is genuine depth; matches the standard coaching cue far
# better than requiring an exact 90 degrees, which most people's camera
# angle/anthropometry will never read as precisely anyway.
DEPTH_EXCELLENT_MAX = 92.0  # used only to grade depth quality, not to gate counting

# "Go deeper" partial-rep detection (same pattern as the shrug/flutter
# kicks analyzers): track the shallowest point of a descent that never
# reached BOTTOM_KNEE_ANGLE_MAX before bouncing back up.
PARTIAL_REP_MARGIN_DEG = 5.0
PARTIAL_REP_MIN_DESCENT_DEG = 15.0  # must have genuinely started descending
PARTIAL_REP_BOUNCE_DEG = 8.0

MIN_REP_DURATION = 0.5  # seconds — faster than this = bouncing, not a controlled rep
MAX_REP_DURATION = 8.0  # seconds — slower than this = paused, not mid-rep

# ---- form-check thresholds ----
KNEE_PAST_TOES_MAX_NORM = 0.16  # normalized by torso length; forward offset
# of front knee past front toe, measured at the bottom of the rep
BACK_ANKLE_DRIFT_MAX_NORM = 0.055  # normalized by torso length; a passively
# resting rear foot shouldn't slide on the bench — if it drifts more than
# this during the rep, the back leg is generating force, not just
# balancing. (Deliberately NOT based on the rear knee's own angle: that
# angle is measured from the hip, and the hip legitimately drops during
# ANY correctly-performed rep, which would make an angle-based check
# false-flag clean reps purely from normal pelvis movement.)
BACKWARD_LEAN_MAX_DEG = 8.0  # any lean AWAY from the front leg beyond this
# reads as a compensation pattern (forward lean itself is NOT flagged —
# it's the textbook-correct position for this exercise)

CONFIRM_FRAMES = 2  # debounce for the up/down stage transition

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


def _view_mode(shoulder_width: float, torso_length: float) -> str:
    ratio = shoulder_width / max(torso_length, 1e-6)
    if ratio <= SIDE_VIEW_RATIO_MAX:
        return "side"
    if ratio >= FRONT_VIEW_RATIO_MIN:
        return "front"
    return "angled"


def _framing_feedback(points: list[_Point]) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — step back so your whole "
                "body, both legs and the bench, are visible."
            )

    if len(points) < 4:
        return None

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "You're too close to the camera — back up so your whole stance fits in frame."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class BulgarianSplitSquatAnalyzer:
    """Stateful Bulgarian split squat rep counter. Auto-detects which leg
    is the working (front) leg from the rear-foot-elevated stance itself
    — works correctly regardless of which physical leg the person leads
    with, with no configuration required."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        working_leg: Optional[str] = None,
    ):
        self.target_reps = target_reps
        # Label only — see module docstring. Never used to drive counting.
        self.requested_leg = working_leg if working_leg in ("left", "right") else None

        self.front_leg: Optional[str] = None  # "left" / "right" — locked in
        self.rear_leg: Optional[str] = None
        self._stance_streak = 0
        self._stance_bad_streak = 0
        self.ready = False
        self.leg_mismatch = False

        self.stage = "up"  # "up" = standing, "down" = bottom of the squat
        self._pending_stage: Optional[str] = None
        self._pending_streak = 0

        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.partial_rep_count = 0

        self.rep_start_time: Optional[float] = None
        self.session_start_time: Optional[float] = None

        self._rep_min_front_knee: Optional[float] = None
        self._rep_max_forward_offset: Optional[float] = None
        self._rep_rear_ankle_start: Optional[_Point] = None
        self._rep_rear_ankle_drift: float = 0.0
        self._rep_min_torso_lean: Optional[float] = None
        self._rep_issues: set[str] = set()

        self._attempt_min_front_knee: Optional[float] = None
        self._attempt_flagged = False

    # ---------------------------------------------------------------
    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 5.0:
            return "too_slow"
        if duration >= 2.5:
            return "slow"
        if duration >= 1.0:
            return "good"
        if duration >= 0.5:
            return "fast"
        return "too_fast"

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _reset_rep_tracking(self):
        self.rep_start_time = None
        self._rep_min_front_knee = None
        self._rep_max_forward_offset = None
        self._rep_rear_ankle_start = None
        self._rep_rear_ankle_drift = 0.0
        self._rep_min_torso_lean = None
        self._rep_issues = set()

    def _unlock_stance(self):
        self.front_leg = None
        self.rear_leg = None
        self.ready = False
        self._stance_streak = 0
        self.stage = "up"
        self._pending_stage = None
        self._pending_streak = 0
        self._attempt_min_front_knee = None
        self._attempt_flagged = False
        self._reset_rep_tracking()

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "view_mode": None,
            "ready": self.ready,
            "stance_message": None,
            "requested_leg": self.requested_leg,
            "front_leg": self.front_leg,
            "rear_leg": self.rear_leg,
            "leg_mismatch": self.leg_mismatch,
            "elevation_gap": None,
            "front_knee_angle": None,
            "rear_knee_angle": None,
            "torso_lean_deg": None,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "partial_rep_count": self.partial_rep_count,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_duration": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "depth_quality": None,
            "rep_flaws": [],
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            self._unlock_stance()
            response["feedback"] = (
                "No person detected — stand facing the camera (ideally "
                "side-on) with your rear foot up on a bench behind you."
            )
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]
        l_toe, r_toe = landmarks[LEFT_FOOT_INDEX], landmarks[RIGHT_FOOT_INDEX]

        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
        left_leg_ok = _visible((l_hip, l_knee, l_ankle))
        right_leg_ok = _visible((r_hip, r_knee, r_ankle))

        if not torso_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._unlock_stance()
            response["feedback"] = (
                "Can't see your torso clearly — make sure your shoulders "
                "and hips are both in frame."
            )
            return response

        response["pose_detected"] = True

        if not left_leg_ok or not right_leg_ok:
            response["low_visibility"] = True
            self._unlock_stance()
            response["feedback"] = (
                "Can't see both legs clearly — step back so your whole "
                "stance (hips, knees, and both ankles) is visible."
            )
            return response

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)
        shoulder_width = _dist(l_shoulder, r_shoulder)

        view_mode = _view_mode(shoulder_width, torso_length)
        response["view_mode"] = view_mode

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
        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        # ---- stance detection: which ankle is elevated (rear leg)? ----
        elevation_gap = (r_ankle.y - l_ankle.y) / torso_length
        # positive => left ankle is higher (left = rear); negative => right is higher
        response["elevation_gap"] = round(elevation_gap, 3)

        if elevation_gap >= REAR_FOOT_ELEVATION_MIN:
            candidate_rear = "left"
        elif -elevation_gap >= REAR_FOOT_ELEVATION_MIN:
            candidate_rear = "right"
        else:
            candidate_rear = None

        if candidate_rear is not None and (
            self.rear_leg is None or candidate_rear == self.rear_leg
        ):
            self._stance_streak += 1
            self._stance_bad_streak = 0
        elif candidate_rear is not None and self.rear_leg is not None:
            # Disagrees with the locked stance (e.g. genuinely switched
            # feet) — needs its own fresh stable streak before relocking,
            # doesn't just silently flip on one frame.
            self._stance_bad_streak += 1
            self._stance_streak = 0
        else:
            self._stance_streak = 0
            self._stance_bad_streak += 1

        if (
            not self.ready
            and candidate_rear is not None
            and self._stance_streak >= STABLE_STANCE_FRAMES
        ):
            self.rear_leg = candidate_rear
            self.front_leg = "right" if candidate_rear == "left" else "left"
            self.ready = True
            self.leg_mismatch = (
                self.requested_leg is not None and self.requested_leg != self.front_leg
            )
        elif self.ready and self._stance_bad_streak >= GRACE_FRAMES:
            self._unlock_stance()

        response["ready"] = self.ready
        response["front_leg"] = self.front_leg
        response["rear_leg"] = self.rear_leg
        response["leg_mismatch"] = self.leg_mismatch

        if not self.ready:
            response["stance_message"] = (
                "Get into position: rear foot up on a bench behind you "
                "(laces down), front foot planted well ahead of it, "
                "standing tall."
            )
            response["feedback"] = response["stance_message"]
            return response

        if self.leg_mismatch:
            response["feedback"] = (
                f"Heads up — you set working leg to '{self.requested_leg}', "
                f"but it looks like your {self.front_leg} leg is actually "
                f"doing the work here. Counting the {self.front_leg} leg "
                f"since that's what the camera sees."
            )

        # ---- angles, using whichever leg is actually locked in ----
        if self.front_leg == "left":
            f_hip, f_knee, f_ankle, f_toe = l_hip, l_knee, l_ankle, l_toe
            b_hip, b_knee, b_ankle = r_hip, r_knee, r_ankle
        else:
            f_hip, f_knee, f_ankle, f_toe = r_hip, r_knee, r_ankle, r_toe
            b_hip, b_knee, b_ankle = l_hip, l_knee, l_ankle

        front_knee_angle = _angle_deg(f_hip, f_knee, f_ankle)
        rear_knee_angle = _angle_deg(b_hip, b_knee, b_ankle)
        response["front_knee_angle"] = round(front_knee_angle, 1)
        response["rear_knee_angle"] = round(rear_knee_angle, 1)

        torso_lean_deg = None
        forward_dir_sign = 1.0 if (f_ankle.x - mid_hip.x) >= 0 else -1.0
        dx = mid_shoulder.x - mid_hip.x
        dy = mid_hip.y - mid_shoulder.y
        if dx != 0 or dy != 0:
            incline = math.degrees(math.atan2(abs(dx), max(abs(dy), 1e-9)))
            signed = incline if (dx * forward_dir_sign) >= 0 else -incline
            torso_lean_deg = signed
        response["torso_lean_deg"] = (
            round(torso_lean_deg, 1) if torso_lean_deg is not None else None
        )

        feedback = framing_message or response.get("feedback")

        # ---- per-frame rep-attempt tracking ----
        if (
            self._rep_min_front_knee is None
            or front_knee_angle < self._rep_min_front_knee
        ):
            self._rep_min_front_knee = front_knee_angle

        if self._rep_rear_ankle_start is None:
            self._rep_rear_ankle_start = _Point(b_ankle.x, b_ankle.y)
        else:
            drift = _dist(self._rep_rear_ankle_start, b_ankle) / torso_length
            if drift > self._rep_rear_ankle_drift:
                self._rep_rear_ankle_drift = drift

        if torso_lean_deg is not None and (
            self._rep_min_torso_lean is None
            or torso_lean_deg < self._rep_min_torso_lean
        ):
            self._rep_min_torso_lean = torso_lean_deg

        if view_mode != "front" and f_toe is not None and _visible((f_toe,)):
            forward_offset = (f_knee.x - f_toe.x) * forward_dir_sign / torso_length
            if (
                self._rep_max_forward_offset is None
                or forward_offset > self._rep_max_forward_offset
            ):
                self._rep_max_forward_offset = forward_offset

        # ---- "go deeper" partial-rep detection ----
        partial_feedback = None
        if self.stage == "up":
            if (
                self._attempt_min_front_knee is None
                or front_knee_angle < self._attempt_min_front_knee
            ):
                self._attempt_min_front_knee = front_knee_angle
            elif (
                not self._attempt_flagged
                and self._attempt_min_front_knee is not None
                and front_knee_angle - self._attempt_min_front_knee
                > PARTIAL_REP_BOUNCE_DEG
                and self._attempt_min_front_knee
                < BOTTOM_KNEE_ANGLE_MAX + PARTIAL_REP_MARGIN_DEG
                and TOP_KNEE_ANGLE_MIN - self._attempt_min_front_knee
                > PARTIAL_REP_MIN_DESCENT_DEG
            ):
                self._attempt_flagged = True
                self.partial_rep_count += 1
                partial_feedback = (
                    "Go deeper — lower until your front thigh is roughly "
                    "parallel to the floor before driving back up."
                )

            if front_knee_angle >= TOP_KNEE_ANGLE_MIN:
                self._attempt_min_front_knee = None
                self._attempt_flagged = False

        # ---- stage debounce ----
        if self.stage == "up" and front_knee_angle <= BOTTOM_KNEE_ANGLE_MAX:
            candidate_stage = "down"
        elif self.stage == "down" and front_knee_angle >= TOP_KNEE_ANGLE_MIN:
            candidate_stage = "up"
        else:
            candidate_stage = None

        if candidate_stage is not None and candidate_stage == self._pending_stage:
            self._pending_streak += 1
        elif candidate_stage is not None:
            self._pending_stage = candidate_stage
            self._pending_streak = 1
        else:
            self._pending_stage = None
            self._pending_streak = 0

        rep_completed = False
        rep_duration = rep_class = rep_form_quality = depth_quality = None
        completed_rep_flaws: list[str] = []

        if (
            candidate_stage is not None
            and self._pending_streak >= CONFIRM_FRAMES
            and candidate_stage != self.stage
        ):
            if candidate_stage == "down":
                self.stage = "down"
                self.rep_start_time = t
                self._rep_min_front_knee = front_knee_angle
                self._rep_max_forward_offset = None
                self._rep_rear_ankle_start = _Point(b_ankle.x, b_ankle.y)
                self._rep_rear_ankle_drift = 0.0
                self._rep_min_torso_lean = torso_lean_deg
                self._rep_issues = set()
            else:  # candidate_stage == "up" — completes the rep
                self.stage = "up"

                if (
                    self._rep_max_forward_offset is not None
                    and self._rep_max_forward_offset > KNEE_PAST_TOES_MAX_NORM
                ):
                    self._rep_issues.add("knee_past_toes")

                if self._rep_rear_ankle_drift > BACK_ANKLE_DRIFT_MAX_NORM:
                    self._rep_issues.add("pushing_off_back_leg")

                if (
                    view_mode != "front"
                    and self._rep_min_torso_lean is not None
                    and self._rep_min_torso_lean < -BACKWARD_LEAN_MAX_DEG
                ):
                    self._rep_issues.add("leaning_back")

                rep_duration = (
                    (t - self.rep_start_time)
                    if self.rep_start_time is not None
                    else None
                )
                min_knee = self._rep_min_front_knee

                valid = (
                    rep_duration is not None
                    and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                    and min_knee is not None
                    and min_knee <= BOTTOM_KNEE_ANGLE_MAX
                )

                if valid:
                    self.rep_count += 1
                    rep_completed = True
                    rep_class = self._classify_tempo(rep_duration)
                    depth_quality = (
                        "excellent" if min_knee <= DEPTH_EXCELLENT_MAX else "good"
                    )
                    completed_rep_flaws = sorted(self._rep_issues)

                    if self._rep_issues:
                        rep_form_quality = "needs_improvement"
                        self.flawed_reps += 1
                        issue_text = ", ".join(
                            i.replace("_", " ") for i in sorted(self._rep_issues)
                        )
                        feedback = (
                            f"Rep {self.rep_count} counted, but watch your "
                            f"form ({issue_text})."
                        )
                    else:
                        rep_form_quality = "good"
                        self.good_reps += 1
                        if rep_class in ("good", "fast"):
                            feedback = (
                                f"Solid rep — {depth_quality} depth, "
                                f"{rep_class} tempo ({rep_duration:.2f}s). "
                                f"Rep {self.rep_count}."
                            )
                        else:
                            feedback = (
                                f"Clean rep, {depth_quality} depth "
                                f"({rep_duration:.2f}s). Rep {self.rep_count}."
                            )
                else:
                    if rep_duration is not None and rep_duration < MIN_REP_DURATION:
                        feedback = (
                            "Too fast — that rep wasn't counted, control the descent."
                        )
                    elif rep_duration is not None and rep_duration > MAX_REP_DURATION:
                        feedback = "That rep took too long — not counted."
                    else:
                        feedback = (
                            "Not enough depth — not counted. Lower until "
                            "your front thigh is roughly parallel to the floor."
                        )

                self._reset_rep_tracking()

        if feedback is None:
            feedback = partial_feedback
        if feedback is None:
            feedback = (
                "Good — keep going."
                if self.stage == "up"
                else "Drive back up through your front heel."
            )

        response.update(
            {
                "stage": self.stage,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "partial_rep_count": self.partial_rep_count,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_duration": rep_duration,
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "depth_quality": depth_quality,
                "rep_flaws": completed_rep_flaws,
                "feedback": feedback,
            }
        )
        return response


class BulgarianSplitSquatSession:
    """Full Bulgarian split squat session: one shared pose model + one
    analyzer.

    `target_reps` / `target_sets` / `set_number` / `working_leg` are
    supplied by the caller (the websocket route, from query params) —
    same convention as every other session class in this project.
    `session_complete` and `exercise_complete` are computed here, not on
    the frontend.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
        working_leg: Optional[str] = None,
    ):
        self.engine = PoseEngine()
        self.analyzer = BulgarianSplitSquatAnalyzer(target_reps, working_leg)
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
