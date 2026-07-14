

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
# machine. Same hysteresis-band naming convention as squat/bicep analyzers.
DOWN_ANGLE = 155.0  # arms considered fully extended (top of push-up)
UP_ANGLE = 95.0  # elbows bent enough to count as the bottom of a rep
MIN_ANGLE_DELTA = 40.0  # total angle travel required for a rep to "count"
MIN_REP_DURATION = 0.35  # seconds — faster than this = uncontrolled/momentum
MAX_REP_DURATION = 8.0  # seconds — slower than this = probably a pause, not a rep

PARTIAL_REP_MARGIN_DEG = 15.0
PARTIAL_REP_MIN_DESCENT_DEG = 25.0
PARTIAL_REP_BOUNCE_DEG = 8.0

# -------------------------------------------------------------------------
# Floor-position detection (camera-angle independent — see module docstring)
# -------------------------------------------------------------------------
LEG_VERTICAL_STANDING_MIN = 0.85  # hip-to-feet vertical gap / torso length
LEG_VERTICAL_FLOOR_MAX = 0.45
TORSO_INCLINE_STANDING_MIN_DEG = 55.0
TORSO_INCLINE_FLOOR_MAX_DEG = 35.0
BBOX_ASPECT_FLOOR_MIN = 1.2  # width/height of visible-landmark bbox
BBOX_ASPECT_STANDING_MAX = 0.75

STABLE_FLOOR_FRAMES = 5  # consecutive good frames before counting turns on
GRACE_FRAMES = 8  # consecutive bad frames tolerated before counting turns off

# View-mode classification (shoulder width / torso length)
SIDE_VIEW_RATIO_MAX = 0.45
FRONT_VIEW_RATIO_MIN = 0.85

# Hip sag / pike (body-line straightness), normalized by torso length.
HIP_SAG_THRESHOLD = 0.18
HIP_PIKE_THRESHOLD = -0.18

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


def _assess_body_position(
    leg_vertical_ratio: Optional[float],
    torso_incline_deg: Optional[float],
    bbox_aspect: Optional[float],
) -> tuple[bool, bool]:
    """Votes across three independent, camera-agnostic cues. Returns
    (is_floor, is_standing) — both require agreement, not just a majority,
    so a lone ambiguous cue can never flip the result on its own."""
    standing_votes = 0
    floor_votes = 0

    if leg_vertical_ratio is not None:
        if leg_vertical_ratio >= LEG_VERTICAL_STANDING_MIN:
            standing_votes += 2
        elif leg_vertical_ratio <= LEG_VERTICAL_FLOOR_MAX:
            floor_votes += 2

    if torso_incline_deg is not None:
        if torso_incline_deg >= TORSO_INCLINE_STANDING_MIN_DEG:
            standing_votes += 1
        elif torso_incline_deg <= TORSO_INCLINE_FLOOR_MAX_DEG:
            floor_votes += 1

    if bbox_aspect is not None:
        if bbox_aspect >= BBOX_ASPECT_FLOOR_MIN:
            floor_votes += 1
        elif bbox_aspect <= BBOX_ASPECT_STANDING_MAX:
            standing_votes += 1

    is_floor = floor_votes >= 2 and standing_votes == 0
    is_standing = standing_votes >= 2 and floor_votes == 0
    return is_floor, is_standing


def _framing_feedback(points: list[_Point]) -> Optional[str]:
    """Camera-framing sanity check, independent of push-up form — checked
    every frame since bad framing is why the floor-position math above may
    be unreliable in the first place."""
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return "You're partly out of frame — reposition so your whole body is visible."

    if len(points) < 4:
        return None

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "You're too close to the camera — back up so your whole body fits in frame."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class PushupAnalyzer:
    """Stateful push-up rep counter + strict floor-position gate."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        # Rep state machine
        self.stage = "down"  # "down" = arms extended (top/rest), "up" = arms bent (bottom)
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

        # Floor-position gating (see module docstring)
        self._floor_streak = 0
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

        response["pose_detected"] = True

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)
        shoulder_width = _dist(l_shoulder, r_shoulder)

        view_mode = _view_mode(shoulder_width, torso_length)
        response["view_mode"] = view_mode

        leg_far = _leg_far_point(l_ankle, r_ankle, l_knee, r_knee)
        leg_vertical_ratio = (
            abs(mid_hip.y - leg_far.y) / torso_length if leg_far is not None else None
        )
        torso_incline = _torso_incline_deg(mid_shoulder, mid_hip)

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
        bbox_aspect = _bbox_aspect(bbox_points)

        # ---- camera framing (independent of push-up form) ----
        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        # ---- THE critical check: are they actually on the floor? ----
        is_floor, is_standing = _assess_body_position(
            leg_vertical_ratio, torso_incline, bbox_aspect
        )

        if is_floor:
            self._floor_streak += 1
            self._bad_streak = 0
        else:
            self._floor_streak = 0
            self._bad_streak += 1

        if self._floor_streak >= STABLE_FLOOR_FRAMES:
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES:
            self.ready = False
        # else: keep previous `ready` state — short grace period for tracking noise

        position_ok = self.ready
        response["position_ok"] = position_ok
        response["ready"] = self.ready

        if is_standing:
            position_message = (
                "You're standing — get down into push-up position: hands "
                "under your shoulders, body straight from head to heels, "
                "facing the floor."
            )
        elif not position_ok:
            position_message = (
                "Get into a full push-up plank position — hands under "
                "shoulders, straight line from head to heels, low and "
                "horizontal to the floor."
            )
        else:
            position_message = None
        response["position_message"] = position_message

        # ---- elbow angles (drive rep counting) ----
        left_angle = _angle_deg(l_shoulder, l_elbow, l_wrist) if left_arm_ok else None
        right_angle = (
            _angle_deg(r_shoulder, r_elbow, r_wrist) if right_arm_ok else None
        )
        angles = [a for a in (left_angle, right_angle) if a is not None]
        raw_angle = sum(angles) / len(angles)

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

        # ---- body-line straightness (hip sag / pike) ----
        # Only meaningful with real horizontal spread between shoulders and
        # legs, so it's skipped in a near head-on "front" view where that
        # spread collapses (see module docstring).
        alignment_issue = None
        alignment_message = None
        if position_ok and view_mode in ("side", "angled") and leg_far is not None:
            dx = leg_far.x - mid_shoulder.x
            if abs(dx) > 0.05:
                frac = (mid_hip.x - mid_shoulder.x) / dx
                expected_hip_y = mid_shoulder.y + frac * (leg_far.y - mid_shoulder.y)
                deviation = (mid_hip.y - expected_hip_y) / torso_length
                if deviation > HIP_SAG_THRESHOLD:
                    alignment_issue = "hip_sag"
                    alignment_message = (
                        "Squeeze your core — your hips are sagging toward "
                        "the floor. Keep a straight line from shoulders to heels."
                    )
                elif deviation < HIP_PIKE_THRESHOLD:
                    alignment_issue = "hip_pike"
                    alignment_message = (
                        "Lower your hips — you're piking up. Keep a "
                        "straight line from shoulders to heels."
                    )
        response["alignment_ok"] = alignment_issue is None
        response["alignment_issue"] = alignment_issue

        feedback = framing_message

        # ---- rep state machine — only ever progresses on the floor ----
        rep_completed = False
        rep_duration = rep_avg_speed = rep_class = rep_form_quality = None
        partial_feedback = None

        if not position_ok:
            if self.rep_start_time is not None:
                # Mid-rep and the plank broke — the attempt doesn't count.
                self.rep_start_time = None
                self._rep_angle_acc = 0.0
                self._current_rep_issues = set()
                if feedback is None:
                    feedback = (
                        "Lost plank position mid-rep — not counted. Reset "
                        "to the top and try again."
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
                        f"bend your elbows further (aim for {UP_ANGLE:.0f}° or less)."
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
                            feedback = (
                                f"Good depth, nice and controlled ({rep_duration:.2f}s)."
                            )
                        else:
                            feedback = (
                                f"Clean rep, but control the tempo ({rep_duration:.2f}s)."
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

        if feedback is None and alignment_issue:
            feedback = alignment_message
        if feedback is None and not self.ready:
            feedback = (
                "Hold a steady push-up plank position — hands under "
                "shoulders, straight line from head to heels — to start counting."
            )
        if feedback is None:
            feedback = "Good form — keep going."

        response.update(
            {
                "angle": raw_angle,
                "smoothed_angle": self.smoothed_angle,
                "left_elbow_angle": left_angle,
                "right_elbow_angle": right_angle,
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


class PushupSession:
    """Full push-up session: one shared pose model + one analyzer."""

    def __init__(self, target_reps: Optional[int] = None):
        self.engine = PoseEngine()
        self.analyzer = PushupAnalyzer(target_reps)

    def detect(self, frame, timestamp_ms: int) -> dict[str, Any]:
        landmarks = self.engine.detect(frame, timestamp_ms)
        result = self.analyzer.update(landmarks, timestamp_ms)
        result["landmarks"] = (
            PoseEngine.landmarks_to_json(landmarks) if landmarks else []
        )
        return result

    def close(self):
        self.engine.close()
