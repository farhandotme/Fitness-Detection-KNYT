"""
Pike push-up rep counting + strict pike-position gating.

Design — why this is NOT just the push-up detector with different angles
--------------------------------------------------------------------------
A pike push-up is filmed from the same rough camera placement as a regular
push-up (side-on, floor level), but the body shape is completely different:

    * Regular push-up  -> body is a straight line, shoulders-to-heels,
      roughly parallel to the floor (a "plank").
    * Pike push-up      -> hips are lifted high into the air, forming an
      inverted V (the same base shape as a downward-dog). The torso angles
      down toward the hands, the legs angle down toward the feet, and the
      hips are the highest point in the frame.

So the plank-detection heuristics in `pushup.py` (leg-vertical ratio,
torso incline, bbox aspect — all tuned to detect a *horizontal straight
line*) are the wrong tool here. Reusing them would either (a) never
recognize a real pike position as "ready", or worse (b) accept a flat
plank as if it were a pike, which is exactly the "counts reps the user
didn't actually do" failure mode this needs to avoid.

Instead, position gating here is built around three independent,
corroborating signals that a real inverted-V pike position produces:

    1. `hip_angle` = angle(shoulder, hip, ankle/knee), vertex at the hip.
       ~180° = straight body (plank or standing). A true pike sharply
       folds this angle — this is the primary, hardest-to-fake signal.
    2. `shoulder_elevation` = how far above the shoulders the hips sit,
       normalized by torso length. Positive and large only when the hips
       are genuinely the high point of the shape.
    3. `leg_elevation` = the same idea measured against the ankles/knees.

All three must agree (see `_assess_pike_position`) before the position is
considered a verified pike — a single noisy signal can never flip it on
its own, mirroring the multi-cue voting approach used by the push-up and
side-plank detectors elsewhere in this backend.

Rep counting itself still uses elbow angle (shoulder-elbow-wrist), exactly
like the push-up detector — bending the elbows to lower the head toward
the floor is the actual work of the exercise, regardless of hip shape.
The critical rule enforced throughout: **the elbow-angle state machine is
only ever allowed to progress while a verified pike position is held.**
If the pike breaks mid-rep (hips drop into a plank, person stands up,
etc.), the in-progress rep is discarded, not counted — same "can't cheat
the counter by faking the position" guarantee the push-up detector gives.
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


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 3


# Elbow angle (shoulder-elbow-wrist) thresholds driving the rep state
# machine — same hysteresis-band convention as the push-up analyzer.
DOWN_ANGLE = 155.0  # arms considered fully extended (top of the rep)
UP_ANGLE = 100.0  # elbows bent enough to count as the bottom of a rep —
# slightly less deep than a flat push-up's 95°, since the pike stance
# shortens the natural elbow-bend range of motion; head-to-floor is the
# real depth target, elbow angle is the measurable proxy for it.
MIN_ANGLE_DELTA = 35.0  # total angle travel required for a rep to "count"
MIN_REP_DURATION = 0.35  # seconds — faster than this = uncontrolled/momentum
MAX_REP_DURATION = 8.0  # seconds — slower than this = probably a pause, not a rep

PARTIAL_REP_MARGIN_DEG = 15.0
PARTIAL_REP_MIN_DESCENT_DEG = 20.0
PARTIAL_REP_BOUNCE_DEG = 8.0

# -------------------------------------------------------------------------
# Pike-position detection (camera-angle independent — see module docstring)
# -------------------------------------------------------------------------
HIP_ANGLE_PIKE_MAX_DEG = 115.0  # shoulder-hip-ankle angle must fold at least
# this sharply for the shape to read as a genuine inverted V.
HIP_ANGLE_STRAIGHT_MIN_DEG = 150.0  # angle at/above this = a straight body
# (plank or standing) — used only for the "you're too flat" feedback copy.

MIN_HIP_ELEVATION_RATIO = 0.12  # (shoulder_y - hip_y) / torso_length and
# (leg_y - hip_y) / leg_length must each clear this — hips must be clearly
# the highest point of the shape, not just "a bit bent".
MIN_WRIST_ELEVATION_RATIO = 0.08  # wrists should sit clearly below the
# hip line (hands planted on the floor), a softer corroborating vote.

STABLE_PIKE_FRAMES = 5  # consecutive good frames before counting turns on
GRACE_FRAMES = 8  # consecutive bad frames tolerated before counting turns off

# View-mode classification (shoulder width / torso length) — a pike
# push-up is only reliably judged from a side-on or angled view, same as
# a regular push-up's plank-straightness check.
SIDE_VIEW_RATIO_MAX = 0.45
FRONT_VIEW_RATIO_MIN = 0.85

# Form-quality flags (do not block counting, but flag the rep)
KNEE_STRAIGHT_MIN_DEG = 150.0  # legs should stay straight throughout
HIP_ANGLE_SOFT_WARN_DEG = HIP_ANGLE_PIKE_MAX_DEG + 15.0  # pike shape
# noticeably degrading (hips drooping toward a plank) during the rep,
# even though it hasn't broken the hard gate yet.

# Camera framing
FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.95  # bbox width or height fraction of frame
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


def _leg_far_point(l_ankle, r_ankle, l_knee, r_knee) -> Optional[_Point]:
    """Whichever leg endpoint we can trust — ankles preferred, knees as a
    fallback for framing that crops the feet out."""
    ankles = [p for p in (l_ankle, r_ankle) if _visible((p,))]
    if len(ankles) == 2:
        return _midpoint(*ankles)
    if len(ankles) == 1:
        return _Point(ankles[0].x, ankles[0].y)
    knees = [p for p in (l_knee, r_knee) if _visible((p,))]
    if len(knees) == 2:
        return _midpoint(*knees)
    if len(knees) == 1:
        return _Point(knees[0].x, knees[0].y)
    return None


def _view_mode(shoulder_width: float, torso_length: float) -> str:
    ratio = shoulder_width / max(torso_length, 1e-6)
    if ratio <= SIDE_VIEW_RATIO_MAX:
        return "side"
    if ratio >= FRONT_VIEW_RATIO_MIN:
        return "front"
    return "angled"


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


def _assess_pike_position(
    hip_angle: Optional[float],
    shoulder_elevation: Optional[float],
    leg_elevation: Optional[float],
    wrist_elevation: Optional[float],
) -> bool:
    """Votes across four independent cues that a genuine inverted-V pike
    shape is held. The hip-angle fold is the primary, hardest-to-fake
    signal (worth 2 votes); each elevation cue corroborates it. Requiring
    >=3 of the possible 5 votes means the hip-angle vote alone is never
    enough on its own — at least one elevation cue must also agree, so a
    momentary angle glitch can't flip the gate on by itself."""
    votes = 0

    if hip_angle is not None and hip_angle <= HIP_ANGLE_PIKE_MAX_DEG:
        votes += 2

    if shoulder_elevation is not None and shoulder_elevation >= MIN_HIP_ELEVATION_RATIO:
        votes += 1

    if leg_elevation is not None and leg_elevation >= MIN_HIP_ELEVATION_RATIO:
        votes += 1

    if wrist_elevation is not None and wrist_elevation >= MIN_WRIST_ELEVATION_RATIO:
        votes += 1

    return votes >= 3


def _framing_feedback(points: list[_Point]) -> Optional[str]:
    """Camera-framing sanity check, independent of pike form."""
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


class PikePushupAnalyzer:
    """Stateful pike push-up rep counter + strict pike-position gate."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        # Rep state machine
        self.stage = (
            "down"  # "down" = arms extended (top/rest), "up" = arms bent (bottom)
        )
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.partial_rep_count = 0

        self.smoothed_angle: Optional[float] = None
        self.last_angle: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None
        self.rep_start_time: Optional[float] = None
        self._rep_angle_acc = 0.0
        self.angle_smooth_alpha = 0.6

        self.session_start_time: Optional[float] = None

        # "Go lower" partial-rep detection
        self._attempt_min_angle: Optional[float] = None
        self._attempt_flagged = False

        # Pike-position gating (see module docstring)
        self._pike_streak = 0
        self._bad_streak = 0
        self.ready = False

        self._current_rep_issues: set[str] = set()

    # ---------------------------------------------------------------
    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 3.0:
            return "too_slow"
        if duration >= 1.8:
            return "slow"
        if duration >= 0.7:
            return "good"
        if duration >= 0.35:
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
            "view_mode": None,
            "position_ok": False,
            "position_message": None,
            "ready": self.ready,
            "angle": None,
            "smoothed_angle": None,
            "left_elbow_angle": None,
            "right_elbow_angle": None,
            "hip_angle": None,
            "angle_velocity": None,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_duration": None,
            "rep_avg_speed": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "alignment_ok": True,
            "alignment_issue": None,
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
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        left_arm_ok = _visible((l_shoulder, l_elbow, l_wrist))
        right_arm_ok = _visible((r_shoulder, r_elbow, r_wrist))
        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))

        if not left_arm_ok and not right_arm_ok:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your arms clearly — adjust the camera so your "
                "shoulders, elbows, and wrists are all in frame."
            )
            return response

        if not torso_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your torso — make sure your shoulders and hips "
                "are both in frame."
            )
            return response

        leg_far = _leg_far_point(l_ankle, r_ankle, l_knee, r_knee)
        if leg_far is None:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your legs or feet — reposition the camera so "
                "your whole body, hands to feet, is in frame."
            )
            return response

        response["pose_detected"] = True

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)
        leg_length = max(_dist(mid_hip, leg_far), 1e-6)
        shoulder_width = _dist(l_shoulder, r_shoulder)

        view_mode = _view_mode(shoulder_width, torso_length)
        response["view_mode"] = view_mode

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
                l_ankle,
                r_ankle,
            )
            if _visible((p,))
        ]
        bbox_points = [_Point(p.x, p.y) for p in bbox_candidates]

        # ---- camera framing (independent of pike form) ----
        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        # ---- THE critical check: are they actually in a pike position? ----
        hip_angle = _angle_deg(mid_shoulder, mid_hip, leg_far)
        shoulder_elevation = (mid_shoulder.y - mid_hip.y) / torso_length
        leg_elevation = (leg_far.y - mid_hip.y) / leg_length

        wrist_candidates = [p for p in (l_wrist, r_wrist) if _visible((p,))]
        wrist_elevation: Optional[float] = None
        if wrist_candidates:
            wrist_y_avg = sum(p.y for p in wrist_candidates) / len(wrist_candidates)
            wrist_elevation = (wrist_y_avg - mid_hip.y) / torso_length

        response["hip_angle"] = round(hip_angle, 1)

        is_pike = _assess_pike_position(
            hip_angle, shoulder_elevation, leg_elevation, wrist_elevation
        )

        if is_pike:
            self._pike_streak += 1
            self._bad_streak = 0
        else:
            self._pike_streak = 0
            self._bad_streak += 1

        if self._pike_streak >= STABLE_PIKE_FRAMES:
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES:
            self.ready = False
        # else: keep previous `ready` state — short grace period for tracking noise

        position_ok = self.ready
        response["position_ok"] = position_ok
        response["ready"] = self.ready

        if not position_ok:
            if hip_angle >= HIP_ANGLE_STRAIGHT_MIN_DEG:
                position_message = (
                    "Raise your hips up into an inverted V — hands and "
                    "feet on the floor, hips lifted high, like the top of "
                    "a downward dog."
                )
            else:
                position_message = (
                    "Get into the full pike position — hips lifted as the "
                    "highest point, straight arms and legs, forming an "
                    "upside-down V."
                )
        else:
            position_message = None
        response["position_message"] = position_message

        # ---- elbow angles (drive rep counting) ----
        left_angle = _angle_deg(l_shoulder, l_elbow, l_wrist) if left_arm_ok else None
        right_angle = _angle_deg(r_shoulder, r_elbow, r_wrist) if right_arm_ok else None
        angles = [a for a in (left_angle, right_angle) if a is not None]
        raw_angle = sum(angles) / len(angles)

        response["left_elbow_angle"] = left_angle
        response["right_elbow_angle"] = right_angle

        if self.smoothed_angle is None:
            self.smoothed_angle = raw_angle
        else:
            self.smoothed_angle = (
                self.angle_smooth_alpha * raw_angle
                + (1 - self.angle_smooth_alpha) * self.smoothed_angle
            )

        angle_velocity = None
        if self.last_angle is not None and self.last_timestamp_s is not None:
            dt = t - self.last_timestamp_s
            if dt > 0:
                angle_velocity = (self.smoothed_angle - self.last_angle) / dt

        # ---- knee straightness (form quality, not a hard gate) ----
        knee_angle: Optional[float] = None
        if _visible((l_hip, l_knee, l_ankle)) and _visible((r_hip, r_knee, r_ankle)):
            knee_angle = (
                _angle_deg(l_hip, l_knee, l_ankle) + _angle_deg(r_hip, r_knee, r_ankle)
            ) / 2.0
        elif _visible((l_hip, l_knee, l_ankle)):
            knee_angle = _angle_deg(l_hip, l_knee, l_ankle)
        elif _visible((r_hip, r_knee, r_ankle)):
            knee_angle = _angle_deg(r_hip, r_knee, r_ankle)

        alignment_issue = None
        alignment_message = None
        if position_ok:
            if knee_angle is not None and knee_angle < KNEE_STRAIGHT_MIN_DEG:
                alignment_issue = "bent_knees"
                alignment_message = (
                    "Keep your legs straight — don't bend your knees to "
                    "hold the pike."
                )
            elif hip_angle > HIP_ANGLE_SOFT_WARN_DEG:
                alignment_issue = "hips_dropping"
                alignment_message = (
                    "Keep your hips lifted high — don't let the pike flatten "
                    "out toward a plank as you move."
                )
        response["alignment_ok"] = alignment_issue is None
        response["alignment_issue"] = alignment_issue

        feedback = framing_message

        # ---- rep state machine — only ever progresses in a verified pike ----
        rep_completed = False
        rep_duration = rep_avg_speed = rep_class = rep_form_quality = None
        partial_feedback = None

        if not position_ok:
            if self.rep_start_time is not None:
                # Mid-rep and the pike broke — the attempt doesn't count.
                self.rep_start_time = None
                self._rep_angle_acc = 0.0
                self._current_rep_issues = set()
                if feedback is None:
                    feedback = (
                        "Lost the pike position mid-rep — not counted. "
                        "Reset your hips up and try again."
                    )
            if feedback is None:
                feedback = position_message
        else:
            if self.stage == "down":
                if (
                    self._attempt_min_angle is None
                    or self.smoothed_angle < self._attempt_min_angle
                ):
                    self._attempt_min_angle = self.smoothed_angle
                elif (
                    not self._attempt_flagged
                    and self._attempt_min_angle is not None
                    and self.smoothed_angle - self._attempt_min_angle
                    > PARTIAL_REP_BOUNCE_DEG
                    and self._attempt_min_angle > UP_ANGLE + PARTIAL_REP_MARGIN_DEG
                    and DOWN_ANGLE - self._attempt_min_angle
                    > PARTIAL_REP_MIN_DESCENT_DEG
                ):
                    self._attempt_flagged = True
                    self.partial_rep_count += 1
                    partial_feedback = (
                        f"Go lower — you stopped around {self._attempt_min_angle:.0f}°, "
                        f"lower your head further toward the floor (aim for "
                        f"{UP_ANGLE:.0f}° or less at the elbow)."
                    )

                if self.smoothed_angle > DOWN_ANGLE - 5:
                    self._attempt_min_angle = None
                    self._attempt_flagged = False

            if self.stage == "down" and self.smoothed_angle < UP_ANGLE:
                self.rep_start_time = t
                self._rep_angle_acc = 0.0
            if self.last_angle is not None:
                self._rep_angle_acc += abs(self.smoothed_angle - self.last_angle)

            if self.stage == "down" and self.smoothed_angle < UP_ANGLE:
                self.stage = "up"
                self._current_rep_issues = set()
            elif self.stage == "up" and self.smoothed_angle > DOWN_ANGLE:
                self.stage = "down"
                rep_completed = True

            if self.stage == "up" and alignment_issue:
                self._current_rep_issues.add(alignment_issue)

            if feedback is None:
                feedback = partial_feedback

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
                        feedback = (
                            f"Rep {self.rep_count} counted, but watch your "
                            f"form ({issue_text})."
                        )
                    else:
                        rep_form_quality = "good"
                        self.good_reps += 1
                        if rep_class in ("good", "fast"):
                            feedback = (
                                f"Clean rep — {rep_class} tempo ({rep_duration:.2f}s)."
                            )
                        elif rep_class in ("slow", "too_slow"):
                            feedback = f"Good depth, nice and controlled ({rep_duration:.2f}s)."
                        else:
                            feedback = f"Clean rep, but control the tempo ({rep_duration:.2f}s)."
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

        if feedback is None and alignment_issue:
            feedback = alignment_message
        if feedback is None and not self.ready:
            feedback = (
                "Hold a steady pike position — hips lifted high, hands "
                "and feet grounded — to start counting."
            )
        if feedback is None:
            feedback = "Good form — keep going."

        response.update(
            {
                "angle": raw_angle,
                "smoothed_angle": self.smoothed_angle,
                "angle_velocity": angle_velocity,
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


class PikePushupSession:
    """Full pike push-up session: one shared pose model + one analyzer.

    `target_reps` / `target_sets` / `set_number` are the coach-assigned plan
    for this user, supplied by the caller (the websocket route, from query
    params) — same convention as the push-up and squat sessions. The
    frontend does not decide on its own whether a set/exercise is done;
    `session_complete` (this set's reps are done) and `exercise_complete`
    (the whole assigned plan — all sets — is done) are computed here.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = PikePushupAnalyzer(target_reps)
        self.target_sets = max(1, target_sets)
        self.set_number = max(1, min(set_number, self.target_sets))

    def detect(self, frame, timestamp_ms: int) -> dict[str, Any]:
        landmarks = self.engine.detect(frame, timestamp_ms)
        result = self.analyzer.update(landmarks, timestamp_ms)
        result["landmarks"] = (
            PoseEngine.landmarks_to_json(landmarks) if landmarks else []
        )

        # Backend-validated plan progress — frontend just reads these, it
        # never computes them itself.
        result["set_number"] = self.set_number
        result["target_sets"] = self.target_sets
        result["exercise_complete"] = bool(
            result["session_complete"] and self.set_number >= self.target_sets
        )
        return result

    def close(self):
        self.engine.close()
