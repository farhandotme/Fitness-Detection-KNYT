"""
Lying hamstring curl — both legs curling together.

User lies face down, filmed from the side. Both legs start mostly
extended, then both knees curl to bring the heels toward the glutes,
then return to an extended position. One rep = both legs' full
extended -> curled -> extended cycle.

The analyzer:

- Confirms a prone, side-on lying position before counting.
- Uses both knee angles together (left/right) to detect curl and extension.
- Counts a rep when both legs curl to depth, then return to a mostly
  extended position (doesn't require perfect lockout).
- Tracks hips lifting, thighs lifting, depth, and tempo as form notes.
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


# Lying gate: torso roughly horizontal, wide bbox
TORSO_INCLINE_LYING_MAX_DEG = 45.0
BBOX_ASPECT_LYING_MIN = 0.95
STABLE_LYING_FRAMES = 3
GRACE_FRAMES = 10

SIDE_VIEW_RATIO_MAX = 0.6
FRONT_VIEW_RATIO_MIN = 0.9

# Knee flexion thresholds (angle at knee: hip-knee-ankle)
EXTENDED_KNEE_ANGLE_MIN = 155.0  # reference "fully extended"
EXTENDED_FOR_COUNT_MIN = 145.0  # softer threshold used to finish a rep
CURL_DETECT_ANGLE_MAX = 140.0  # knees considered "curling" once bent at least this much
CURLED_KNEE_ANGLE_MAX = 105.0  # must reach this depth or less to count as a rep
DEPTH_EXCELLENT_MAX = 80.0  # grading only, not a gate

CONFIRM_FRAMES = 2

MIN_REP_DURATION = 0.5
MAX_REP_DURATION = 6.0

# Partial-rep detection (bounce pattern)
PARTIAL_REP_MARGIN_DEG = 5.0
PARTIAL_REP_MIN_CURL_DEG = 15.0
PARTIAL_REP_BOUNCE_DEG = 8.0

# Anti-cheat thresholds (normalized by torso length)
HIP_LIFT_MAX_NORM = 0.08
THIGH_LIFT_MAX_NORM = 0.10

# Camera framing
FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.95
BBOX_TOO_FAR = 0.15

# -------------------------------------------------------------------------
# Geometry helpers
# -------------------------------------------------------------------------


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
                "You're partly out of frame — reposition so your whole "
                "body, shoulders to feet, is visible from the side."
            )
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


def _assess_lying(
    torso_incline_deg: Optional[float], bbox_aspect: Optional[float]
) -> bool:
    votes = 0
    total = 0
    if torso_incline_deg is not None:
        total += 1
        if torso_incline_deg <= TORSO_INCLINE_LYING_MAX_DEG:
            votes += 1
    if bbox_aspect is not None:
        total += 1
        if bbox_aspect >= BBOX_ASPECT_LYING_MIN:
            votes += 1
    if total == 0:
        return False
    return votes >= 1


# -------------------------------------------------------------------------
# Analyzer
# -------------------------------------------------------------------------


class HamstringCurlAnalyzer:
    """
    Lying hamstring curl with BOTH legs curling together.
    Rep = both knees go from extended -> curled -> extended.

    Counts when you return to the down / extended position. Extension
    doesn't have to be perfectly straight; a little bend is acceptable.
    """

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.in_curl_phase = False  # are we in the down/curl phase

        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.partial_rep_count = 0

        self.rep_start_time: Optional[float] = None
        self.session_start_time: Optional[float] = None

        self._rep_min_left_angle: Optional[float] = None
        self._rep_min_right_angle: Optional[float] = None
        self._rep_start_hip_y: Optional[float] = None
        self._rep_max_hip_lift: float = 0.0
        self._rep_start_knee_y: Optional[float] = None
        self._rep_max_thigh_lift: float = 0.0
        self._rep_issues: set[str] = set()

        self._attempt_min_avg_angle: Optional[float] = None
        self._attempt_flagged = False

        self._lying_streak = 0
        self._bad_streak = 0
        self.ready = False

    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 3.5:
            return "too_slow"
        if duration >= 2.0:
            return "slow"
        if duration >= 0.9:
            return "good"
        if duration >= 0.5:
            return "fast"
        return "too_fast"

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _reset_rep_tracking(self):
        self.rep_start_time = None
        self._rep_min_left_angle = None
        self._rep_min_right_angle = None
        self._rep_start_hip_y = None
        self._rep_max_hip_lift = 0.0
        self._rep_start_knee_y = None
        self._rep_max_thigh_lift = 0.0
        self._rep_issues = set()

    def _invalidate_in_progress(self):
        self.in_curl_phase = False
        self._attempt_min_avg_angle = None
        self._attempt_flagged = False
        self._reset_rep_tracking()

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
            "left_knee_angle": None,
            "right_knee_angle": None,
            "stage": "curl" if self.in_curl_phase else "extended",
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
            self._invalidate_in_progress()
            self.ready = False
            response["feedback"] = (
                "No person detected — lie face down in frame, filmed from the side."
            )
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
        left_leg_ok = _visible((l_hip, l_knee, l_ankle))
        right_leg_ok = _visible((r_hip, r_knee, r_ankle))

        if not torso_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._invalidate_in_progress()
            self.ready = False
            response["feedback"] = (
                "Can't see your torso clearly — make sure your shoulders and hips are both in frame."
            )
            return response

        response["pose_detected"] = True

        if not left_leg_ok or not right_leg_ok:
            response["low_visibility"] = True
            self._invalidate_in_progress()
            self.ready = False
            response["feedback"] = (
                "Can't see both legs clearly — reposition side-on to the camera so both legs are visible."
            )
            return response

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)
        shoulder_width = _dist(l_shoulder, r_shoulder)

        view_mode = _view_mode(shoulder_width, torso_length)
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

        is_lying = _assess_lying(torso_incline, bbox_aspect)

        if is_lying:
            self._lying_streak += 1
            self._bad_streak = 0
        else:
            self._lying_streak = 0
            self._bad_streak += 1

        if self._lying_streak >= STABLE_LYING_FRAMES:
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES:
            self.ready = False

        position_ok = self.ready
        response["position_ok"] = position_ok
        response["ready"] = self.ready

        position_message = (
            None
            if position_ok
            else "Lie face down, filmed from the side — hips and thighs flat on the floor, legs extended."
        )
        response["position_message"] = position_message

        left_knee_angle = _angle_deg(l_hip, l_knee, l_ankle)
        right_knee_angle = _angle_deg(r_hip, r_knee, r_ankle)
        response["left_knee_angle"] = round(left_knee_angle, 1)
        response["right_knee_angle"] = round(right_knee_angle, 1)

        feedback = framing_message

        rep_completed = False
        rep_duration = rep_class = rep_form_quality = depth_quality = None
        completed_rep_flaws: list[str] = []

        if not position_ok:
            self._invalidate_in_progress()
            if feedback is None:
                feedback = position_message
        else:
            avg_angle = (left_knee_angle + right_knee_angle) / 2.0

            in_extended = (
                left_knee_angle >= EXTENDED_FOR_COUNT_MIN
                and right_knee_angle >= EXTENDED_FOR_COUNT_MIN
            )
            in_curl = (
                left_knee_angle <= CURL_DETECT_ANGLE_MAX
                and right_knee_angle <= CURL_DETECT_ANGLE_MAX
            )

            # Track minimum angles and lifts during curl phase
            if self.in_curl_phase:
                if (
                    self._rep_min_left_angle is None
                    or left_knee_angle < self._rep_min_left_angle
                ):
                    self._rep_min_left_angle = left_knee_angle
                if (
                    self._rep_min_right_angle is None
                    or right_knee_angle < self._rep_min_right_angle
                ):
                    self._rep_min_right_angle = right_knee_angle

                if self._rep_start_hip_y is not None:
                    lift = (self._rep_start_hip_y - mid_hip.y) / torso_length
                    if lift > self._rep_max_hip_lift:
                        self._rep_max_hip_lift = lift
                if self._rep_start_knee_y is not None:
                    knee_mid_y = (l_knee.y + r_knee.y) / 2.0
                    thigh_lift = (self._rep_start_knee_y - knee_mid_y) / torso_length
                    if thigh_lift > self._rep_max_thigh_lift:
                        self._rep_max_thigh_lift = thigh_lift

            # Partial-rep detection
            partial_feedback = None
            if self.in_curl_phase and in_curl:
                if (
                    self._attempt_min_avg_angle is None
                    or avg_angle < self._attempt_min_avg_angle
                ):
                    self._attempt_min_avg_angle = avg_angle
                elif (
                    not self._attempt_flagged
                    and self._attempt_min_avg_angle is not None
                    and avg_angle - self._attempt_min_avg_angle > PARTIAL_REP_BOUNCE_DEG
                    and self._attempt_min_avg_angle
                    < CURLED_KNEE_ANGLE_MAX + PARTIAL_REP_MARGIN_DEG
                    and EXTENDED_KNEE_ANGLE_MIN - self._attempt_min_avg_angle
                    > PARTIAL_REP_MIN_CURL_DEG
                ):
                    self._attempt_flagged = True
                    self.partial_rep_count += 1
                    partial_feedback = "Curl deeper — bring both heels further toward your glutes before extending back out."

            # Start curl phase
            if not self.in_curl_phase and in_curl:
                self.in_curl_phase = True
                self.rep_start_time = t
                self._rep_min_left_angle = left_knee_angle
                self._rep_min_right_angle = right_knee_angle
                self._rep_start_hip_y = mid_hip.y
                self._rep_max_hip_lift = 0.0
                knee_mid_y = (l_knee.y + r_knee.y) / 2.0
                self._rep_start_knee_y = knee_mid_y
                self._rep_max_thigh_lift = 0.0
                self._rep_issues = set()
                self._attempt_min_avg_angle = None
                self._attempt_flagged = False

            # Finish rep when returning to extended (allowing slight bend)
            if self.in_curl_phase and in_extended:
                min_left = self._rep_min_left_angle
                min_right = self._rep_min_right_angle
                min_angle = (
                    (min_left + min_right) / 2.0
                    if min_left is not None and min_right is not None
                    else None
                )

                if self._rep_max_hip_lift > HIP_LIFT_MAX_NORM:
                    self._rep_issues.add("hips_lifting")
                if self._rep_max_thigh_lift > THIGH_LIFT_MAX_NORM:
                    self._rep_issues.add("thigh_lifting")

                rep_duration = (
                    (t - self.rep_start_time)
                    if self.rep_start_time is not None
                    else None
                )

                valid = (
                    rep_duration is not None
                    and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                    and min_angle is not None
                    and min_angle <= CURLED_KNEE_ANGLE_MAX
                )

                if valid:
                    self.rep_count += 1
                    rep_completed = True
                    rep_class = self._classify_tempo(rep_duration)
                    depth_quality = (
                        "excellent" if min_angle <= DEPTH_EXCELLENT_MAX else "good"
                    )
                    completed_rep_flaws = sorted(self._rep_issues)

                    if self._rep_issues:
                        rep_form_quality = "needs_improvement"
                        self.flawed_reps += 1
                        issue_text = ", ".join(
                            i.replace("_", " ") for i in completed_rep_flaws
                        )
                        feedback = f"Rep {self.rep_count} counted, but watch your form ({issue_text})."
                    else:
                        rep_form_quality = "good"
                        self.good_reps += 1
                        feedback = (
                            f"Clean curl, {depth_quality} depth ({rep_duration:.2f}s). "
                            f"Rep {self.rep_count} — keep both thighs down and hips heavy."
                        )
                else:
                    if rep_duration is not None and rep_duration < MIN_REP_DURATION:
                        feedback = "Too fast — that curl wasn't counted, slow it down."
                    elif rep_duration is not None and rep_duration > MAX_REP_DURATION:
                        feedback = "That rep took too long — not counted."
                    else:
                        feedback = "Not enough depth — not counted. Curl your heels further toward your glutes."

                self.in_curl_phase = False
                self._attempt_min_avg_angle = None
                self._attempt_flagged = False
                self._reset_rep_tracking()

            if feedback is None:
                feedback = partial_feedback
            if feedback is None:
                if not self.in_curl_phase:
                    feedback = "Curl both legs — bring your heels up toward your glutes together."
                else:
                    feedback = "Keep curling both legs, heels toward your glutes."

        response.update(
            {
                "stage": "curl" if self.in_curl_phase else "extended",
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


# -------------------------------------------------------------------------
# Session wrapper
# -------------------------------------------------------------------------


class HamstringCurlSession:
    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = HamstringCurlAnalyzer(target_reps)
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
