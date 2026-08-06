"""
Cable Upright Row detector.

Movement contract
-----------------
The user stands with both feet planted and both hands low on the cable:

    low/start -> pull elbows high and out -> lower hands and elbows

Both arms must be visible and rise together. Both ankles are required and are
calibrated at the start of the set; a meaningful foot/ankle shift pauses the
counter so leg movement cannot create a false upper-body repetition.
"""

import math
from dataclasses import dataclass
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_SHOULDER,
    LEFT_WRIST,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)

MIN_LANDMARK_VISIBILITY = 0.38
# Ankles are often partly occluded by shoes, equipment, or the frame edge.
# Keep the gate conservative enough to reject noise, but do not discard a
# clearly tracked ankle solely because one side has a lower confidence score.
ANKLE_VISIBILITY = 0.20
ARM_VISIBILITY = 0.34
PERSON_VISIBILITY = 0.58

CORE_LANDMARKS = (
    LEFT_SHOULDER,
    RIGHT_SHOULDER,
    LEFT_HIP,
    RIGHT_HIP,
)
TRACKED_LANDMARKS = CORE_LANDMARKS + (
    LEFT_ELBOW,
    RIGHT_ELBOW,
    LEFT_WRIST,
    RIGHT_WRIST,
    LEFT_ANKLE,
    RIGHT_ANKLE,
)

# Elbow lift is normalized to torso height. Image y increases downward.
LOW_ELBOW_LIFT = 0.08
HIGH_ELBOW_LIFT = 0.22
MIN_ELBOW_TRAVEL = 0.18
WRIST_BELOW_ELBOW_TOLERANCE = 0.10
ELBOW_OUTWARD_RATIO = 0.18

LIFT_SMOOTH_ALPHA = 0.68
STANCE_CONFIRM_FRAMES = 5
STANCE_GRACE_FRAMES = 2
LOW_CONFIRM_FRAMES = 2
HIGH_CONFIRM_FRAMES = 3
MIN_REP_DURATION = 0.25
MAX_REP_DURATION = 8.0

# Ankle y values can drift substantially in MediaPipe VIDEO mode as the model
# refines the body scale. Track feet relative to the pelvis and weight
# horizontal movement more heavily, because an actual step changes the
# horizontal stance while model scale drift mostly changes y.
MAX_ANKLE_SHIFT_RATIO = 0.28
MAX_ANKLE_WIDTH_CHANGE_RATIO = 0.20
ANKLE_VERTICAL_DRIFT_WEIGHT = 0.25
STANCE_BASELINE_ALPHA = 0.08

FRAME_EDGE_MARGIN = 0.025


@dataclass
class _Stance:
    baseline_left: Optional[tuple[float, float]] = None
    baseline_right: Optional[tuple[float, float]] = None
    baseline_width: Optional[float] = None
    stable_frames: int = 0
    bad_frames: int = 0
    ready: bool = False
    shift: float = 0.0
    width_change: float = 0.0
    dropout_frames: int = 0


@dataclass
class _State:
    stage: str = "low"
    low_streak: int = 0
    high_streak: int = 0
    seen_low: bool = False
    smoothed_lift: Optional[float] = None
    last_lift: Optional[float] = None
    rep_start_time: Optional[float] = None
    peak_lift: Optional[float] = None
    angle_acc: float = 0.0

    def reset_rep(self) -> None:
        self.rep_start_time = None
        self.peak_lift = None
        self.angle_acc = 0.0
        self.high_streak = 0


def _visible(
    points: tuple[Any, ...],
    threshold: float = MIN_LANDMARK_VISIBILITY,
) -> bool:
    return all(
        point is not None
        and (
            getattr(point, "visibility", None) is None
            or getattr(point, "visibility", 0.0) >= threshold
        )
        for point in points
    )


def _looks_like_a_person(landmarks: list[Any]) -> bool:
    if len(landmarks) < 33:
        return False
    visible_core = sum(
        1
        for index in CORE_LANDMARKS
        if getattr(landmarks[index], "visibility", None) is not None
        and landmarks[index].visibility >= PERSON_VISIBILITY
    )
    return visible_core >= 3


def _xyz(point: Any) -> tuple[float, float, float]:
    if isinstance(point, (tuple, list)) and len(point) >= 3:
        return float(point[0]), float(point[1]), float(point[2])
    return (
        float(getattr(point, "x", 0.0)),
        float(getattr(point, "y", 0.0)),
        float(getattr(point, "z", 0.0) or 0.0),
    )


def _distance(a: Any, b: Any) -> float:
    ax, ay, az = _xyz(a)
    bx, by, bz = _xyz(b)
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2)


def _angle_at(a: Any, b: Any, c: Any) -> Optional[float]:
    ax, ay, az = _xyz(a)
    bx, by, bz = _xyz(b)
    cx, cy, cz = _xyz(c)
    first = (ax - bx, ay - by, az - bz)
    second = (cx - bx, cy - by, cz - bz)
    first_len = math.sqrt(sum(value * value for value in first))
    second_len = math.sqrt(sum(value * value for value in second))
    if first_len < 1e-8 or second_len < 1e-8:
        return None
    cosine = sum(first[i] * second[i] for i in range(3)) / (first_len * second_len)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _framing_feedback(points: list[Any]) -> Optional[str]:
    for point in points:
        if (
            point.x < FRAME_EDGE_MARGIN
            or point.x > 1.0 - FRAME_EDGE_MARGIN
            or point.y < FRAME_EDGE_MARGIN
            or point.y > 1.0 - FRAME_EDGE_MARGIN
        ):
            return "Keep your shoulders, elbows, wrists, and ankles inside the frame."
    return None


class CableUprightRowAnalyzer:
    """Stateful bilateral cable upright-row counter with ankle tracking."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps
        self.state = _State()
        self.stance = _Stance()
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.last_timestamp_s: Optional[float] = None
        self.session_start_time: Optional[float] = None

    def _complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    @staticmethod
    def _tempo(duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration < 0.25:
            return "too_fast"
        if duration < 0.70:
            return "fast"
        if duration < 1.80:
            return "good"
        if duration < 3.50:
            return "slow"
        return "too_slow"

    def _base_response(self, elapsed: float) -> dict[str, Any]:
        return {
            "pose_detected": False,
            "view_mode": "front",
            "position_ok": False,
            "position_message": None,
            "ready": self.stance.ready,
            "stage": self.state.stage,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": self._complete(),
            "rep_completed": False,
            "rep_duration": None,
            "rep_avg_speed": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "left_elbow_lift": None,
            "right_elbow_lift": None,
            "smoothed_elbow_lift": None,
            "left_elbow_angle": None,
            "right_elbow_angle": None,
            "elbows_high": False,
            "wrists_below_elbows": False,
            "low_position": False,
            "left_ankle_visible": False,
            "right_ankle_visible": False,
            "ankles_tracked": False,
            "ankle_gate": "waiting_for_ankles",
            "ankle_shift": 0.0,
            "ankle_width": None,
            "ankle_width_change": 0.0,
            "stance_stable": False,
            "left_arm_visible": False,
            "right_arm_visible": False,
            "wrists_optional": True,
            "framing_ok": True,
            "framing_message": None,
            "alignment_ok": True,
            "alignment_issue": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

    def _update_stance(
        self,
        left_ankle: Any,
        right_ankle: Any,
        hip_center: tuple[float, float],
        torso_height: float,
        allow_calibration: bool,
    ) -> bool:
        lx, ly, _ = _xyz(left_ankle)
        rx, ry, _ = _xyz(right_ankle)
        hx, hy = hip_center
        current_left = (
            (lx - hx) / max(torso_height, 1e-8),
            (ly - hy) / max(torso_height, 1e-8),
        )
        current_right = (
            (rx - hx) / max(torso_height, 1e-8),
            (ry - hy) / max(torso_height, 1e-8),
        )
        width = abs(current_right[0] - current_left[0])

        if self.stance.baseline_left is None and allow_calibration:
            self.stance.baseline_left = current_left
            self.stance.baseline_right = current_right
            self.stance.baseline_width = width
            self.stance.stable_frames = 1
            self.stance.ready = False
            # Calibration itself is not a valid stance gate. This prevents a
            # top-position frame from entering "raising" before the ankle
            # baseline has been confirmed.
            return False

        if self.stance.baseline_left is None or self.stance.baseline_right is None:
            return False

        left_shift = math.hypot(
            current_left[0] - self.stance.baseline_left[0],
            ANKLE_VERTICAL_DRIFT_WEIGHT
            * (current_left[1] - self.stance.baseline_left[1]),
        )
        right_shift = math.hypot(
            current_right[0] - self.stance.baseline_right[0],
            ANKLE_VERTICAL_DRIFT_WEIGHT
            * (current_right[1] - self.stance.baseline_right[1]),
        )
        baseline_width = self.stance.baseline_width or width
        width_change = abs(width - baseline_width)
        self.stance.shift = max(left_shift, right_shift)
        self.stance.width_change = width_change

        stable = (
            self.stance.shift <= MAX_ANKLE_SHIFT_RATIO
            and self.stance.width_change <= MAX_ANKLE_WIDTH_CHANGE_RATIO
        )
        if stable:
            self.stance.stable_frames += 1
            self.stance.bad_frames = 0
        else:
            self.stance.bad_frames += 1
            self.stance.stable_frames = 0

        if self.stance.stable_frames >= STANCE_CONFIRM_FRAMES:
            self.stance.ready = True
        elif self.stance.bad_frames >= STANCE_GRACE_FRAMES:
            self.stance.ready = False

        # Slowly follow camera/model drift while stable. A real step still
        # remains outside the threshold for several frames and is rejected.
        if not self.stance.ready or stable:
            alpha = STANCE_BASELINE_ALPHA if self.stance.ready else 0.30
            self.stance.baseline_left = tuple(
                (1.0 - alpha) * old + alpha * new
                for old, new in zip(self.stance.baseline_left, current_left)
            )
            self.stance.baseline_right = tuple(
                (1.0 - alpha) * old + alpha * new
                for old, new in zip(self.stance.baseline_right, current_right)
            )
            self.stance.baseline_width = (1.0 - alpha) * baseline_width + alpha * width
        return stable and self.stance.ready

    def _finish_rep(
        self,
        timestamp_s: float,
        left_elbow_angle: Optional[float],
        right_elbow_angle: Optional[float],
    ) -> dict[str, Any]:
        duration = (
            max(0.0, timestamp_s - self.state.rep_start_time)
            if self.state.rep_start_time is not None
            else 0.0
        )
        issues: set[str] = set()
        if duration < MIN_REP_DURATION:
            issues.add("rushed_rep")
        if duration > MAX_REP_DURATION:
            issues.add("too_slow")
        if (
            left_elbow_angle is not None
            and right_elbow_angle is not None
            and abs(left_elbow_angle - right_elbow_angle) > 28.0
        ):
            issues.add("uneven_elbows")

        quality = "good" if not issues else "needs_improvement"
        self.rep_count += 1
        if quality == "good":
            self.good_reps += 1
        else:
            self.flawed_reps += 1

        event = {
            "duration": duration,
            "avg_speed": (self.state.angle_acc / duration if duration > 0 else None),
            "classification": self._tempo(duration),
            "quality": quality,
        }
        self.state.stage = "raised"
        self.state.rep_start_time = None
        self.state.peak_lift = None
        self.state.angle_acc = 0.0
        self.state.high_streak = 0
        return event

    def update(
        self, landmarks: Optional[list[Any]], timestamp_ms: int
    ) -> dict[str, Any]:
        timestamp_s = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = timestamp_s
        elapsed = max(0.0, timestamp_s - self.session_start_time)
        response = self._base_response(elapsed)

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = (
                "No person detected — stand with both feet visible and hold the cable low."
            )
            return response
        response["pose_detected"] = True

        left_shoulder = landmarks[LEFT_SHOULDER]
        right_shoulder = landmarks[RIGHT_SHOULDER]
        left_hip = landmarks[LEFT_HIP]
        right_hip = landmarks[RIGHT_HIP]
        left_elbow = landmarks[LEFT_ELBOW]
        right_elbow = landmarks[RIGHT_ELBOW]
        left_wrist = landmarks[LEFT_WRIST]
        right_wrist = landmarks[RIGHT_WRIST]
        left_ankle = landmarks[LEFT_ANKLE]
        right_ankle = landmarks[RIGHT_ANKLE]

        torso_points = (
            left_shoulder,
            right_shoulder,
            left_hip,
            right_hip,
        )
        ankle_points = (left_ankle, right_ankle)
        left_arm_points = (left_shoulder, left_elbow)
        right_arm_points = (right_shoulder, right_elbow)
        left_wrist_visible = _visible((left_wrist,))
        right_wrist_visible = _visible((right_wrist,))
        torso_visible = _visible(torso_points)
        ankles_visible = _visible(ankle_points, ANKLE_VISIBILITY)
        left_arm_visible = _visible(left_arm_points, ARM_VISIBILITY)
        right_arm_visible = _visible(right_arm_points, ARM_VISIBILITY)

        # Wrists are deliberately not part of the hard gate. In a cable row
        # they are commonly occluded by the handle/cable or by the forearms,
        # while the shoulders and elbows still describe the movement reliably.
        required = torso_points + ankle_points + left_arm_points + right_arm_points
        response["left_arm_visible"] = left_arm_visible
        response["right_arm_visible"] = right_arm_visible
        response["left_ankle_visible"] = _visible((left_ankle,), ANKLE_VISIBILITY)
        response["right_ankle_visible"] = _visible((right_ankle,), ANKLE_VISIBILITY)
        response["low_visibility"] = not (
            torso_visible and ankles_visible and left_arm_visible and right_arm_visible
        )
        if not torso_visible:
            response["feedback"] = (
                "Keep both shoulders and hips visible so I can measure your torso."
            )
            response["ankle_gate"] = "torso_not_visible"
            return response
        if not ankles_visible and self.stance.baseline_left is None:
            response["feedback"] = (
                "Keep both ankles visible — I use them to check that your feet stay planted."
            )
            response["ankle_gate"] = "ankles_not_visible"
            return response
        if not left_arm_visible or not right_arm_visible:
            response["feedback"] = (
                "Keep both elbows visible. Lead the row with both elbows, not your hands."
            )
            response["ankle_gate"] = "waiting_for_arms"
            return response

        # A low-confidence wrist can still have a useful position, but it
        # cannot be allowed to suppress a valid elbow-led rep.
        wrist_visibility = {
            "left": left_wrist_visible,
            "right": right_wrist_visible,
        }
        framing_message = _framing_feedback(list(required))
        framing_ok = framing_message is None
        torso_height = max(
            _distance(left_shoulder, left_hip),
            _distance(right_shoulder, right_hip),
            1e-8,
        )
        hip_center = (
            (left_hip.x + right_hip.x) / 2.0,
            (left_hip.y + right_hip.y) / 2.0,
        )
        ankle_tracking_grace = False
        if ankles_visible:
            self.stance.dropout_frames = 0
            stance_ok = self._update_stance(
                left_ankle,
                right_ankle,
                hip_center,
                torso_height,
                allow_calibration=framing_ok,
            )
        else:
            # MediaPipe can report a visible ankle coordinate with a
            # temporarily low confidence while the leg is still stationary.
            # Do not throw away an otherwise valid elbow movement during that
            # short dropout; keep the last verified stance and fail only after
            # a sustained loss.
            self.stance.dropout_frames += 1
            ankle_tracking_grace = self.stance.dropout_frames <= 10
            stance_ok = self.stance.ready and ankle_tracking_grace
            if ankle_tracking_grace:
                response["low_visibility"] = False
                response["left_ankle_visible"] = True
                response["right_ankle_visible"] = True
                response["ankle_gate"] = "tracking_grace"
            else:
                response["ankle_gate"] = "ankles_not_visible"

        left_elbow_lift = (left_shoulder.y - left_elbow.y) / torso_height
        right_elbow_lift = (right_shoulder.y - right_elbow.y) / torso_height
        raw_lift = (left_elbow_lift + right_elbow_lift) / 2.0
        self.state.smoothed_lift = (
            raw_lift
            if self.state.smoothed_lift is None
            else LIFT_SMOOTH_ALPHA * raw_lift
            + (1.0 - LIFT_SMOOTH_ALPHA) * self.state.smoothed_lift
        )
        current_lift = self.state.smoothed_lift

        left_elbow_angle = _angle_at(left_shoulder, left_elbow, left_wrist)
        right_elbow_angle = _angle_at(right_shoulder, right_elbow, right_wrist)
        elbows_high = (
            current_lift >= HIGH_ELBOW_LIFT
            and left_elbow.y <= left_shoulder.y + torso_height * 0.12
            and right_elbow.y <= right_shoulder.y + torso_height * 0.12
        )
        wrists_below_elbows = (
            not left_wrist_visible
            or left_wrist.y >= left_elbow.y - torso_height * WRIST_BELOW_ELBOW_TOLERANCE
        ) and (
            not right_wrist_visible
            or right_wrist.y
            >= right_elbow.y - torso_height * WRIST_BELOW_ELBOW_TOLERANCE
        )
        elbows_out = (
            abs(left_elbow.x - left_shoulder.x) >= torso_height * ELBOW_OUTWARD_RATIO
            and abs(right_elbow.x - right_shoulder.x)
            >= torso_height * ELBOW_OUTWARD_RATIO
        )
        # In a real cable upright row the hands can finish level with or
        # slightly above the elbows, and a front-facing user may show only a
        # small horizontal elbow spread. The elbow lift is the reliable
        # movement signal, so wrist order and elbow width are coaching signals,
        # not hard count gates.
        high_position = elbows_high
        low_position = (
            current_lift <= LOW_ELBOW_LIFT
            and (
                not left_wrist_visible
                or left_wrist.y >= left_shoulder.y - torso_height * 0.02
            )
            and (
                not right_wrist_visible
                or right_wrist.y >= right_shoulder.y - torso_height * 0.02
            )
        )

        if low_position and stance_ok:
            self.state.seen_low = True
            self.state.low_streak += 1
            self.state.high_streak = 0
        else:
            self.state.low_streak = 0
        # A session can begin while the user is already at the top of the
        # row (for example, the camera connects after the lift). Once the
        # ankle stance is calibrated, allow that first high position to
        # initialize the rep instead of waiting forever for a low frame that
        # already happened off-camera. After this initial rep, the normal
        # high -> low reset remains mandatory.
        high_can_start = self.state.seen_low or (
            not self.state.seen_low and self.rep_count == 0 and self.stance.ready
        )
        if high_position and stance_ok and high_can_start:
            self.state.high_streak += 1
        else:
            self.state.high_streak = 0

        completed = None
        # Start timing as soon as the user leaves the low position. Starting
        # the timer only after the high confirmation made every fast, valid
        # rep look like a zero-duration rep.
        if (
            self.state.stage == "low"
            and stance_ok
            and not low_position
            and current_lift > LOW_ELBOW_LIFT
            and (self.state.seen_low or self.rep_count == 0)
        ):
            self.state.stage = "raising"
            self.state.rep_start_time = timestamp_s
            self.state.peak_lift = current_lift
            self.state.angle_acc = 0.0
        if self.state.stage in ("raising", "raised"):
            if self.state.peak_lift is None or current_lift > self.state.peak_lift:
                self.state.peak_lift = current_lift
            if self.state.last_lift is not None:
                self.state.angle_acc += abs(current_lift - self.state.last_lift)
        if (
            self.state.stage == "raising"
            and self.state.high_streak >= HIGH_CONFIRM_FRAMES
        ):
            completed = self._finish_rep(
                timestamp_s,
                left_elbow_angle,
                right_elbow_angle,
            )
        if self.state.stage == "raised" and low_position and stance_ok:
            self.state.low_streak += 1
            if self.state.low_streak >= LOW_CONFIRM_FRAMES:
                self.state.stage = "low"
                self.state.seen_low = True
                self.state.reset_rep()

        if completed:
            feedback = f"Rep {self.rep_count} counted — lower the cable with control."
            response.update(
                {
                    "rep_completed": True,
                    "rep_duration": round(completed["duration"], 3),
                    "rep_avg_speed": (
                        round(completed["avg_speed"], 2)
                        if completed["avg_speed"] is not None
                        else None
                    ),
                    "rep_classification": completed["classification"],
                    "rep_form_quality": completed["quality"],
                }
            )
        elif not stance_ok and not ankle_tracking_grace:
            feedback = (
                "Keep both feet planted — your ankle position moved. "
                "Reset your stance before pulling."
            )
        elif ankle_tracking_grace:
            feedback = "Ankle tracking is stabilizing — keep both feet planted."
        elif not framing_ok:
            feedback = framing_message
        elif not self.stance.ready:
            feedback = "Hold both ankles still for a moment to set your stance."
        elif not self.state.seen_low and self.rep_count == 0 and not high_position:
            feedback = "Start with both hands low in front of your thighs."
        elif self.state.stage in ("raising", "raised"):
            feedback = "Pull your elbows up and out, then lower the cable slowly."
        elif not elbows_out and current_lift > LOW_ELBOW_LIFT:
            feedback = "Keep lifting with your elbows; a wider elbow path is preferred."
        elif self._complete():
            feedback = (
                f"Target reached — {self.target_reps} cable upright rows completed."
            )
        else:
            feedback = "Ready — pull both elbows up and out, then return to low."

        ankle_width = _distance(left_ankle, right_ankle)
        response.update(
            {
                "position_ok": stance_ok,
                "position_message": (
                    None if stance_ok else "Keep both ankles planted and visible."
                ),
                "ready": self.stance.ready,
                "stage": self.state.stage,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._complete(),
                "left_elbow_lift": round(left_elbow_lift, 3),
                "right_elbow_lift": round(right_elbow_lift, 3),
                "smoothed_elbow_lift": round(current_lift, 3),
                "left_elbow_angle": (
                    round(left_elbow_angle, 1) if left_elbow_angle is not None else None
                ),
                "right_elbow_angle": (
                    round(right_elbow_angle, 1)
                    if right_elbow_angle is not None
                    else None
                ),
                "elbows_high": elbows_high,
                "wrists_below_elbows": wrists_below_elbows,
                "low_position": low_position,
                "ankles_tracked": ankles_visible or ankle_tracking_grace,
                "ankle_gate": "stable" if stance_ok else "ankles_moved",
                "ankle_shift": round(self.stance.shift, 3),
                "ankle_width": round(ankle_width, 3),
                "ankle_width_change": round(self.stance.width_change, 3),
                "stance_stable": stance_ok,
                "framing_ok": framing_ok,
                "framing_message": framing_message,
                "alignment_ok": elbows_out if current_lift > LOW_ELBOW_LIFT else True,
                "alignment_issue": (
                    "Keep lifting with your elbows and avoid shrugging."
                    if current_lift > LOW_ELBOW_LIFT and not elbows_out
                    else None
                ),
                "feedback": feedback,
            }
        )
        self.state.last_lift = current_lift
        self.last_timestamp_s = timestamp_s
        return response


class CableUprightRowSession:
    """Cable Upright Row session using one shared PoseEngine."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = CableUprightRowAnalyzer(target_reps)
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
