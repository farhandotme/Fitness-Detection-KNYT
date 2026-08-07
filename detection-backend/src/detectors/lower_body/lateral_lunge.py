"""
Alternating Lateral Lunge detector.

Movement contract
------------------
The reference movement is a standing, alternating side (lateral) lunge:

    stand tall, feet close -> step one foot out to the side and bend that
    knee, pushing the hips back while the other leg stays straight ->
    push off the bent leg back to standing -> repeat, alternating legs

The detector needs a front or three-quarter view because both legs must be
visible at once to tell the bent (lunging) leg apart from the straight
(support) leg and to measure how far the feet spread apart. A shallow dip,
a squat where both knees bend together, or a session that starts mid-lunge
cannot count as a rep.

Form rules this detector is built from (standard coaching cues):
  - Start standing, feet roughly hip-width, chest up, back straight.
  - Step well out to the side; the lunging knee bends to roughly a right
    angle while tracking over the toes; the trailing leg stays straight.
  - Hips push back rather than the torso pitching forward.
  - Push off the bent leg to return both feet back together to standing —
    that full return is what closes a rep.
  - Reps alternate sides; repeating the same side twice in a row is a
    coaching flag, not grounds to refuse counting the rep.
"""

import math
from typing import Any, Optional

# Bump this string on every edit. Printed at import time and returned in
# every response as "detector_version" — check the server logs / this
# field to confirm a redeploy actually picked up the latest file instead
# of silently continuing to run a cached/old process.
DETECTOR_VERSION = "lateral_lunge-2026-08-07c-loosened-thresholds"
print(f"[LateralLunge] loaded detector_version={DETECTOR_VERSION}")

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

MIN_VISIBILITY = 0.30
PERSON_VISIBILITY = 0.50
LEG_VISIBILITY = 0.28
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)

# Depth is tracked as depth_angle = min(left_knee_angle, right_knee_angle),
# i.e. the more-bent leg. 180 deg = fully straight, smaller = deeper bend.
# These are intentionally forgiving: a webcam filming a monitor (screen
# capture of a workout video, off-axis, compressed) reads shallower knee
# bends than a direct in-person camera would, so overly strict angles here
# just cause real reps to go uncounted.
STANDING_KNEE_MIN_DEG = 155.0
LUNGE_BENT_KNEE_MAX_DEG = 145.0
LUNGE_BENT_KNEE_MIN_DEG = 55.0
LUNGE_STRAIGHT_LEG_MIN_DEG = 135.0
DEEP_LUNGE_KNEE_DEG = 125.0
MIN_TRAVEL_DEG = 20.0

# Stance width relative to shoulder width (normalized image coordinates).
STANDING_STANCE_MAX_RATIO = 1.35
LUNGE_STANCE_MIN_RATIO = 1.40

MAX_TORSO_LEAN_DEG = 32.0
ANGLE_SMOOTH_ALPHA = 0.58

POSITION_CONFIRM_FRAMES = 4
POSITION_GRACE_FRAMES = 5
START_CONFIRM_FRAMES = 2
TOP_CONFIRM_FRAMES = 2
MIN_REP_DURATION = 0.55
MAX_REP_DURATION = 8.0
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
    # Degrees from vertical: 0 = upright torso, 90 = fully horizontal.
    dx = mid_hip[0] - mid_shoulder[0]
    dy = mid_hip[1] - mid_shoulder[1]
    return math.degrees(math.atan2(abs(dx), max(abs(dy), 1e-7)))


def _framing_feedback(points: list[Any]) -> Optional[str]:
    for point in points:
        if point.x < FRAME_EDGE_MARGIN or point.x > 1.0 - FRAME_EDGE_MARGIN:
            return "Move back so both feet stay inside the frame as you step out."
        if point.y < FRAME_EDGE_MARGIN or point.y > 1.0 - FRAME_EDGE_MARGIN:
            return "Keep your full body inside the frame, head to feet."
    return None


def _tempo(duration: Optional[float]) -> Optional[str]:
    if duration is None:
        return None
    if duration < 0.55:
        return "too_fast"
    if duration < 1.0:
        return "fast"
    if duration < 3.0:
        return "good"
    if duration < 5.0:
        return "slow"
    return "too_slow"


class LateralLungeAnalyzer:
    """Stateful front-view alternating lateral lunge counter."""

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
        self._start_streak = 0
        self._top_streak = 0
        self._seen_start = False
        self._rep_start_time: Optional[float] = None
        self._rep_start_angle: Optional[float] = None
        self._rep_peak_angle: Optional[float] = None
        self._rep_peak_side: Optional[str] = None
        self._smoothed_angle: Optional[float] = None
        self._last_angle: Optional[float] = None
        self._last_timestamp_s: Optional[float] = None
        self._angle_acc = 0.0
        self._issues: set[str] = set()
        self._session_start_time: Optional[float] = None
        self._last_rep_side: Optional[str] = None
        self._pending_side: Optional[str] = None

    def _complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _base_response(self, elapsed: float) -> dict[str, Any]:
        return {
            "detector_version": DETECTOR_VERSION,
            "pose_detected": False,
            "view_mode": None,
            "position_ok": False,
            "position_message": None,
            "ready": self.ready,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "left_reps": self.left_reps,
            "right_reps": self.right_reps,
            "pending_side": self._pending_side,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": self._complete(),
            "lunge_completed": False,
            "rep_completed": False,
            "rep_duration": None,
            "rep_avg_speed": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "rep_side": None,
            "same_side_repeat": None,
            "left_knee_angle": None,
            "right_knee_angle": None,
            "left_angle": None,
            "right_angle": None,
            "depth_angle": None,
            "smoothed_depth_angle": None,
            "depth_angle_velocity": None,
            "stance_ratio": None,
            "torso_lean_deg": None,
            "lunge_side": None,
            "standing_position": False,
            "lunge_position": False,
            "alignment_ok": False,
            "alignment_issue": None,
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

    def _reset_rep(self) -> None:
        self._rep_start_time = None
        self._rep_start_angle = None
        self._rep_peak_angle = None
        self._rep_peak_side = None
        self._angle_acc = 0.0
        self._issues = set()

    def _finish_rep(
        self,
        response: dict[str, Any],
        timestamp_s: float,
        current_angle: float,
    ) -> None:
        duration = (
            max(0.0, timestamp_s - self._rep_start_time)
            if self._rep_start_time is not None
            else None
        )
        # Depth angle drops as the lunge deepens, so travel is measured as
        # start (near-straight) minus peak (most bent) — the inverse sign
        # convention from an "upright" metric like torso angle.
        travel = (self._rep_start_angle or current_angle) - (
            self._rep_peak_angle if self._rep_peak_angle is not None else current_angle
        )
        if (
            duration is None
            or duration < MIN_REP_DURATION
            or duration > MAX_REP_DURATION
            or travel < MIN_TRAVEL_DEG
            or self._rep_peak_side is None
        ):
            response["feedback"] = (
                "Step further out and bend that knee to a real lunge depth before returning to standing."
            )
            self._reset_rep()
            return

        side = self._rep_peak_side
        same_side_repeat = self._pending_side is not None and self._pending_side == side
        if same_side_repeat:
            self._issues.add("same_side_repeat")
        if (
            self._rep_peak_angle is not None
            and self._rep_peak_angle > DEEP_LUNGE_KNEE_DEG
        ):
            self._issues.add("shallow_lunge")
        if duration > 5.0:
            self._issues.add("slow_rep")

        if side == "left":
            self.left_reps += 1
        else:
            self.right_reps += 1
        self._last_rep_side = side

        # One rep = one right lunge + one left lunge. A single side alone
        # only logs — the counter advances once the opposite side lands.
        paired = self._pending_side is not None and not same_side_repeat
        if paired:
            self.rep_count += 1
            self._pending_side = None
        else:
            self._pending_side = side

        response["lunge_completed"] = True
        response["rep_completed"] = paired
        response["rep_side"] = side
        response["same_side_repeat"] = same_side_repeat
        response["rep_duration"] = round(duration, 3)
        response["rep_avg_speed"] = (
            round(self._angle_acc / duration, 2) if duration else None
        )
        response["rep_classification"] = _tempo(duration)
        response["rep_form_quality"] = (
            "good" if not self._issues else "needs_improvement"
        )
        if response["rep_form_quality"] == "good":
            self.good_reps += 1
        else:
            self.flawed_reps += 1
        self._reset_rep()

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
                self.ready = False
            return response

        left_pts = (
            landmarks[LEFT_HIP],
            landmarks[LEFT_KNEE],
            landmarks[LEFT_ANKLE],
        )
        right_pts = (
            landmarks[RIGHT_HIP],
            landmarks[RIGHT_KNEE],
            landmarks[RIGHT_ANKLE],
        )
        legs_visible = _visible(left_pts, LEG_VISIBILITY) and _visible(
            right_pts, LEG_VISIBILITY
        )
        if not legs_visible:
            response.update(
                {
                    "pose_detected": True,
                    "feedback": "Face the camera so both legs are fully visible, head to feet.",
                }
            )
            self._position_good_streak = 0
            self._position_bad_streak += 1
            if self._position_bad_streak >= POSITION_GRACE_FRAMES:
                self.ready = False
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        shoulder_width = _distance(l_shoulder, r_shoulder)
        torso_length = max(_distance(l_shoulder, l_hip), _distance(r_shoulder, r_hip))
        view_mode = _view_mode(shoulder_width, torso_length)
        side_view_ok = view_mode in ("front", "angled")

        left_knee_angle = _angle_at(l_hip, l_knee, l_ankle)
        right_knee_angle = _angle_at(r_hip, r_knee, r_ankle)
        framing_message = _framing_feedback(
            [l_shoulder, r_shoulder, l_hip, r_hip, l_knee, r_knee, l_ankle, r_ankle]
        )
        framing_ok = framing_message is None
        core_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip), MIN_VISIBILITY)

        if left_knee_angle is None or right_knee_angle is None:
            response.update({"pose_detected": True, "view_mode": view_mode})
            response["feedback"] = (
                "Can't read both knees clearly — face the camera and step back."
            )
            self._position_good_streak = 0
            self._position_bad_streak += 1
            if self._position_bad_streak >= POSITION_GRACE_FRAMES:
                self.ready = False
            return response

        ankle_distance = _distance(l_ankle, r_ankle)
        stance_ratio = ankle_distance / max(shoulder_width, 1e-7)
        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        torso_lean = _torso_lean(mid_shoulder, mid_hip)

        raw_depth_angle = min(left_knee_angle, right_knee_angle)
        if self._smoothed_angle is None:
            self._smoothed_angle = raw_depth_angle
        else:
            self._smoothed_angle = (
                ANGLE_SMOOTH_ALPHA * raw_depth_angle
                + (1.0 - ANGLE_SMOOTH_ALPHA) * self._smoothed_angle
            )
        current_angle = self._smoothed_angle
        bent_side = "left" if left_knee_angle <= right_knee_angle else "right"
        straight_leg_angle = (
            right_knee_angle if bent_side == "left" else left_knee_angle
        )

        angle_velocity = None
        if self._last_angle is not None and self._last_timestamp_s is not None:
            dt = max(timestamp_s - self._last_timestamp_s, 1e-6)
            angle_velocity = (current_angle - self._last_angle) / dt

        # NOTE: view_mode (front/angled/side) is intentionally NOT a gate here.
        # It's a coarse heuristic from shoulder-width vs torso-length and can
        # misfire (e.g. arms crossed over the chest narrows the shoulders and
        # reads as "side"). Gating rep counting on it caused sessions to get
        # stuck on "Setup" forever even with a clean, fully-visible lunge.
        # The real signal for this exercise is the knee angles + stance
        # width computed below, which work across front/angled views. We
        # still surface view_mode/side_view_ok for UI feedback, but only
        # framing and landmark visibility block counting.
        position_now_ok = core_visible and framing_ok
        if position_now_ok:
            self._position_good_streak += 1
            self._position_bad_streak = 0
        else:
            self._position_good_streak = 0
            self._position_bad_streak += 1
        if self._position_good_streak >= POSITION_CONFIRM_FRAMES:
            self.ready = True
        elif self._position_bad_streak >= POSITION_GRACE_FRAMES:
            self.ready = False

        standing_now = bool(
            left_knee_angle >= STANDING_KNEE_MIN_DEG
            and right_knee_angle >= STANDING_KNEE_MIN_DEG
            and stance_ratio <= STANDING_STANCE_MAX_RATIO
        )
        lunge_now = bool(
            LUNGE_BENT_KNEE_MIN_DEG <= current_angle <= LUNGE_BENT_KNEE_MAX_DEG
            and straight_leg_angle >= LUNGE_STRAIGHT_LEG_MIN_DEG
            and stance_ratio >= LUNGE_STANCE_MIN_RATIO
        )
        self._start_streak = self._start_streak + 1 if standing_now else 0
        self._top_streak = self._top_streak + 1 if lunge_now else 0
        start_confirmed = self._start_streak >= START_CONFIRM_FRAMES
        top_confirmed = self._top_streak >= TOP_CONFIRM_FRAMES

        position_message: Optional[str] = None
        if not core_visible:
            position_message = "Keep both shoulders and hips clearly visible."
        elif not framing_ok:
            position_message = framing_message
        elif not self.ready:
            position_message = "Hold a tall standing position, feet together, while I confirm your setup."

        # Advisory only — a poor view angle is coached, not blocked, since
        # the knee-angle/stance-width signal still works from most angles.
        view_advisory = (
            None
            if side_view_ok
            else "Facing the camera more directly will make tracking more reliable."
        )

        position_ok = self.ready and position_now_ok
        response.update(
            {
                "pose_detected": True,
                "view_mode": view_mode,
                "position_ok": position_ok,
                "position_message": position_message,
                "view_advisory": view_advisory,
                "ready": self.ready,
                "left_knee_angle": round(left_knee_angle, 1),
                "right_knee_angle": round(right_knee_angle, 1),
                "left_angle": round(left_knee_angle, 1),
                "right_angle": round(right_knee_angle, 1),
                "depth_angle": round(raw_depth_angle, 1),
                "smoothed_depth_angle": round(current_angle, 1),
                "depth_angle_velocity": (
                    round(angle_velocity, 2) if angle_velocity is not None else None
                ),
                "stance_ratio": round(stance_ratio, 2),
                "torso_lean_deg": round(torso_lean, 1),
                "lunge_side": bent_side if lunge_now else None,
                "standing_position": start_confirmed,
                "lunge_position": top_confirmed,
                "alignment_ok": position_ok and torso_lean <= MAX_TORSO_LEAN_DEG,
                "alignment_issue": (
                    position_message
                    or (
                        "Keep your chest up — hinge at the hips instead of leaning your torso forward."
                        if torso_lean > MAX_TORSO_LEAN_DEG
                        else view_advisory
                    )
                ),
                "framing_ok": framing_ok,
                "framing_message": framing_message,
                "low_visibility": not _visible(
                    (
                        l_shoulder,
                        r_shoulder,
                        l_hip,
                        r_hip,
                        l_knee,
                        r_knee,
                        l_ankle,
                        r_ankle,
                    ),
                    0.55,
                ),
            }
        )

        if position_ok:
            if self.stage in ("lunging",) and torso_lean > MAX_TORSO_LEAN_DEG:
                self._issues.add("forward_lean")

            if start_confirmed:
                self._seen_start = True
                if self.stage == "lunging":
                    self._finish_rep(response, timestamp_s, current_angle)
                    self.stage = "standing"
                    self._rep_start_time = timestamp_s
                    self._rep_start_angle = current_angle
                    self._rep_peak_angle = current_angle
                    self._rep_peak_side = None
                    self._angle_acc = 0.0
                    self._issues = set()
                elif self.stage == "setup":
                    self.stage = "standing"
                    self._rep_start_time = timestamp_s
                    self._rep_start_angle = current_angle
                    self._rep_peak_angle = current_angle
                    self._rep_peak_side = None
                    self._angle_acc = 0.0
                    self._issues = set()
            elif top_confirmed and self._seen_start and self.stage == "standing":
                self.stage = "lunging"
                if self._rep_peak_angle is None or current_angle < self._rep_peak_angle:
                    self._rep_peak_angle = current_angle
                    self._rep_peak_side = bent_side

            if self._last_angle is not None:
                self._angle_acc += abs(current_angle - self._last_angle)
            if self.stage == "lunging" and (
                self._rep_peak_angle is None or current_angle < self._rep_peak_angle
            ):
                self._rep_peak_angle = current_angle
                self._rep_peak_side = bent_side

        if response["rep_completed"]:
            side_label = response["rep_side"] or "that side"
            response["feedback"] = (
                f"Rep {self.rep_count} counted ({side_label} completed the pair) — nice work."
            )
        elif response["lunge_completed"]:
            side_label = response["rep_side"] or "that side"
            other = "left" if side_label == "right" else "right"
            if response.get("same_side_repeat"):
                response["feedback"] = (
                    f"{side_label.capitalize()} lunge logged, but that's two {side_label}s in a row — "
                    f"do a {other} lunge to complete the rep."
                )
            else:
                response["feedback"] = (
                    f"{side_label.capitalize()} lunge logged — do a {other} lunge to complete the rep."
                )
        elif position_message:
            response["feedback"] = position_message
        elif not self._seen_start:
            response["feedback"] = (
                "Setup confirmed — stand tall with feet together, then step out into a lunge."
            )
        elif self.stage == "standing":
            response["feedback"] = (
                "Step out to the side and bend that knee into the lunge."
            )
        elif self.stage == "lunging":
            response["feedback"] = (
                "Good depth — push off that leg and bring your feet back together."
            )
        elif self._complete():
            response["feedback"] = (
                f"Target reached — {self.target_reps} lateral lunges completed."
            )
        else:
            response["feedback"] = (
                "Keep your chest up and knee tracking over your toes."
            )

        response.update(
            {
                "stage": self.stage,
                "rep_count": self.rep_count,
                "left_reps": self.left_reps,
                "right_reps": self.right_reps,
                "pending_side": self._pending_side,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._complete(),
            }
        )
        self._last_angle = current_angle
        self._last_timestamp_s = timestamp_s
        return response


class LateralLungeSession:
    """Standalone detector session using one shared PoseEngine."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = LateralLungeAnalyzer(target_reps)
        self.target_sets = max(1, target_sets)
        self.set_number = max(1, min(set_number, self.target_sets))
        print(
            f"[LateralLunge] session start detector_version={DETECTOR_VERSION} "
            f"STANDING_KNEE_MIN_DEG={STANDING_KNEE_MIN_DEG} "
            f"LUNGE_BENT_KNEE_MAX_DEG={LUNGE_BENT_KNEE_MAX_DEG} "
            f"LUNGE_STRAIGHT_LEG_MIN_DEG={LUNGE_STRAIGHT_LEG_MIN_DEG} "
            f"LUNGE_STANCE_MIN_RATIO={LUNGE_STANCE_MIN_RATIO} "
            f"MIN_TRAVEL_DEG={MIN_TRAVEL_DEG}"
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
