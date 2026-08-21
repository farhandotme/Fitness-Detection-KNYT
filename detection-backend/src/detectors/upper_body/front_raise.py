"""
One- or two-arm dumbbell front-raise detector.

The left and right arms are tracked independently. A user may:

* raise both dumbbells together;
* use only the left or right hand; or
* alternate hands one at a time.

The total ``rep_count`` is the number of completed rounds across the arms:
``max(left_rep_count, right_rep_count)``. Therefore right=1 and left=1 is
total=1, while a single right-hand rep is also total=1.

MediaPipe pose landmarks cannot identify a dumbbell itself. The detector
validates the arm movement and reports the expected equipment/form cues while
the existing PoseEngine remains responsible for pose inference.
"""

import math
from dataclasses import dataclass, field
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_SHOULDER,
    LEFT_WRIST,
    PoseEngine,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)

MIN_LANDMARK_VISIBILITY = 0.45
PERSON_VISIBILITY = 0.60

CORE_LANDMARKS = (
    LEFT_SHOULDER,
    RIGHT_SHOULDER,
    LEFT_HIP,
    RIGHT_HIP,
)

# Shoulder-flexion angle: 0° is the arm alongside the torso and 90° is
# approximately shoulder height. Hysteresis prevents threshold chatter.
DOWN_ENTER_DEG = 34.0
TOP_ENTER_DEG = 68.0
MIN_REP_TRAVEL_DEG = 34.0
# A proper front raise stops at shoulder height (~90°) and goes no higher.
# This gives ~15° of tolerance for tracking noise and individual anatomy, but
# anything past it is drifting toward an overhead press, not a front raise.
MAX_TOP_DEG = 105.0
MIN_ELBOW_ANGLE_DEG = 145.0

ANGLE_SMOOTH_ALPHA = 0.52
POSITION_STABLE_FRAMES = 4
POSITION_GRACE_FRAMES = 8
MIN_REP_DURATION = 0.30
MAX_REP_DURATION = 8.0

FRAME_EDGE_MARGIN = 0.035
BBOX_TOO_CLOSE = 0.96
BBOX_TOO_FAR = 0.08


class _Point:
    __slots__ = ("x", "y", "z")

    def __init__(self, x: float, y: float, z: float = 0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)


@dataclass
class _ArmState:
    name: str
    rep_count: int = 0
    good_reps: int = 0
    flawed_reps: int = 0
    stage: str = "down"
    ready: bool = False
    seen_down: bool = False
    smoothed_angle: Optional[float] = None
    smoothed_elbow_angle: Optional[float] = None
    last_angle: Optional[float] = None
    last_timestamp_s: Optional[float] = None
    rep_start_time: Optional[float] = None
    rep_max_angle: Optional[float] = None
    rep_min_elbow_angle: Optional[float] = None
    rep_angle_acc: float = 0.0
    rep_issues: set[str] = field(default_factory=set)
    position_good_streak: int = 0
    position_bad_streak: int = 0

    def reset_rep(self) -> None:
        self.rep_start_time = None
        self.rep_max_angle = None
        self.rep_min_elbow_angle = None
        self.rep_angle_acc = 0.0
        self.rep_issues = set()


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
    return (
        float(getattr(point, "x", 0.0)),
        float(getattr(point, "y", 0.0)),
        float(getattr(point, "z", 0.0) or 0.0),
    )


def _distance(a: Any, b: Any) -> float:
    ax, ay, az = _xyz(a)
    bx, by, bz = _xyz(b)
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2)


def _angle_between(a: Any, b: Any, c: Any) -> Optional[float]:
    """Angle between b->a and b->c in 3D, normalized to [0, 180]."""
    ax, ay, az = _xyz(a)
    bx, by, bz = _xyz(b)
    cx, cy, cz = _xyz(c)
    first = (ax - bx, ay - by, az - bz)
    second = (cx - bx, cy - by, cz - bz)
    first_length = math.sqrt(sum(value * value for value in first))
    second_length = math.sqrt(sum(value * value for value in second))
    if first_length < 1e-8 or second_length < 1e-8:
        return None
    dot = sum(first[index] * second[index] for index in range(3))
    cosine = max(-1.0, min(1.0, dot / (first_length * second_length)))
    return math.degrees(math.acos(cosine))


def _midpoint(a: Any, b: Any) -> _Point:
    ax, ay, az = _xyz(a)
    bx, by, bz = _xyz(b)
    return _Point((ax + bx) / 2.0, (ay + by) / 2.0, (az + bz) / 2.0)


def _framing_feedback(points: list[Any]) -> Optional[str]:
    valid = [point for point in points if point is not None]
    for point in valid:
        if (
            point.x < FRAME_EDGE_MARGIN
            or point.x > 1.0 - FRAME_EDGE_MARGIN
            or point.y < FRAME_EDGE_MARGIN
            or point.y > 1.0 - FRAME_EDGE_MARGIN
        ):
            return "Keep your visible shoulder, hip, elbow, and wrist fully inside the frame."

    if len(valid) < 4:
        return None
    xs = [point.x for point in valid]
    ys = [point.y for point in valid]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "You're too close to the camera — step back so the raise fits."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for clearer tracking."
    return None


class FrontRaiseAnalyzer:
    """Stateful one- or two-arm dumbbell front-raise rep counter."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps
        self.left = _ArmState("left")
        self.right = _ArmState("right")
        # Kept as public compatibility fields for existing integrations.
        self.stage = "down"
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.left_angle: Optional[float] = None
        self.right_angle: Optional[float] = None
        self.smoothed_angle: Optional[float] = None
        self.last_angle: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None
        self.session_start_time: Optional[float] = None
        self._smoothed_torso_lean: Optional[float] = None

    def _complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    @staticmethod
    def _tempo(duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration < 0.30:
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
            "view_mode": None,
            "position_ok": False,
            "position_message": None,
            "ready": self.left.ready or self.right.ready,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "left_rep_count": self.left.rep_count,
            "right_rep_count": self.right.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "left_good_reps": self.left.good_reps,
            "right_good_reps": self.right.good_reps,
            "left_flawed_reps": self.left.flawed_reps,
            "right_flawed_reps": self.right.flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": self._complete(),
            "rep_completed": False,
            "rep_arms": [],
            "rep_duration": None,
            "rep_avg_speed": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "angle": None,
            "smoothed_angle": None,
            "left_shoulder_angle": None,
            "right_shoulder_angle": None,
            "left_elbow_angle": None,
            "right_elbow_angle": None,
            "angle_velocity": None,
            "top_reached": False,
            "down_reached": False,
            "left_top_reached": False,
            "right_top_reached": False,
            "left_down_reached": False,
            "right_down_reached": False,
            "alignment_ok": True,
            "alignment_issue": None,
            "framing_ok": True,
            "framing_message": None,
            "both_arms_visible": False,
            "left_arm_visible": False,
            "right_arm_visible": False,
            "dumbbells_visible": False,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

    def _finish_arm_rep(
        self,
        arm: _ArmState,
        timestamp_s: float,
        torso_ok: bool,
    ) -> Optional[dict[str, Any]]:
        if arm.rep_start_time is None or arm.rep_max_angle is None:
            arm.reset_rep()
            return None

        duration = max(0.0, timestamp_s - arm.rep_start_time)
        travel = arm.rep_max_angle - DOWN_ENTER_DEG
        if travel < MIN_REP_TRAVEL_DEG:
            arm.reset_rep()
            return None

        arm.rep_count += 1
        if duration < MIN_REP_DURATION:
            arm.rep_issues.add("rushed_rep")
        if duration > MAX_REP_DURATION:
            arm.rep_issues.add("too_slow")
        if arm.rep_max_angle < TOP_ENTER_DEG:
            arm.rep_issues.add("insufficient_height")
        # This was previously only a real-time text hint and never actually
        # checked at rep completion, so raising well past shoulder height
        # (toward an overhead press) still counted as a clean rep. Now it's
        # judged against the peak height actually reached during the rep.
        if arm.rep_max_angle > MAX_TOP_DEG:
            arm.rep_issues.add("raised_too_high")
        if (
            arm.rep_min_elbow_angle is not None
            and arm.rep_min_elbow_angle < MIN_ELBOW_ANGLE_DEG
        ):
            arm.rep_issues.add("bent_elbows")
        if not torso_ok:
            arm.rep_issues.add("torso_lean")

        quality = "good" if not arm.rep_issues else "needs_improvement"
        if quality == "good":
            arm.good_reps += 1
        else:
            arm.flawed_reps += 1
        result = {
            "arm": arm.name,
            "duration": duration,
            "avg_speed": arm.rep_angle_acc / duration if duration > 0 else None,
            "classification": self._tempo(duration),
            "quality": quality,
            "issues": sorted(arm.rep_issues),
        }
        arm.reset_rep()
        return result

    def _process_arm(
        self,
        arm: _ArmState,
        angle: float,
        elbow_angle: float,
        timestamp_s: float,
        position_ok: bool,
        torso_ok: bool,
    ) -> Optional[dict[str, Any]]:
        arm.smoothed_angle = (
            angle
            if arm.smoothed_angle is None
            else ANGLE_SMOOTH_ALPHA * angle
            + (1.0 - ANGLE_SMOOTH_ALPHA) * arm.smoothed_angle
        )
        # Elbow/wrist landmarks are noisy frame to frame. Smooth before judging
        # "bent elbows", or a single jittery frame anywhere in the rep — even one
        # performed with perfect form — can trip the flaw.
        arm.smoothed_elbow_angle = (
            elbow_angle
            if arm.smoothed_elbow_angle is None
            else ANGLE_SMOOTH_ALPHA * elbow_angle
            + (1.0 - ANGLE_SMOOTH_ALPHA) * arm.smoothed_elbow_angle
        )
        current_angle = arm.smoothed_angle
        down = current_angle <= DOWN_ENTER_DEG
        top = TOP_ENTER_DEG <= current_angle <= MAX_TOP_DEG

        if down and position_ok:
            arm.seen_down = True
        completed = None

        if top and position_ok and arm.seen_down:
            if arm.stage == "down":
                arm.stage = "raised"
                arm.rep_start_time = timestamp_s
                arm.rep_max_angle = current_angle
                arm.rep_min_elbow_angle = arm.smoothed_elbow_angle
                arm.rep_angle_acc = 0.0
                arm.rep_issues = set()
            elif arm.rep_max_angle is None or current_angle > arm.rep_max_angle:
                arm.rep_max_angle = current_angle
        elif down and position_ok and arm.stage == "raised":
            arm.stage = "down"
            completed = self._finish_arm_rep(arm, timestamp_s, torso_ok=torso_ok)

        if arm.stage == "raised":
            if arm.rep_max_angle is None or current_angle > arm.rep_max_angle:
                arm.rep_max_angle = current_angle
            if arm.last_angle is not None:
                arm.rep_angle_acc += abs(current_angle - arm.last_angle)
            if (
                arm.rep_min_elbow_angle is None
                or arm.smoothed_elbow_angle < arm.rep_min_elbow_angle
            ):
                arm.rep_min_elbow_angle = arm.smoothed_elbow_angle

        arm.last_angle = current_angle
        arm.last_timestamp_s = timestamp_s
        return completed

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
                "No person detected — stand in front of the camera with a dumbbell "
                "in either hand."
            )
            return response

        left_shoulder = landmarks[LEFT_SHOULDER]
        right_shoulder = landmarks[RIGHT_SHOULDER]
        left_hip = landmarks[LEFT_HIP]
        right_hip = landmarks[RIGHT_HIP]
        left_elbow = landmarks[LEFT_ELBOW]
        right_elbow = landmarks[RIGHT_ELBOW]
        left_wrist = landmarks[LEFT_WRIST]
        right_wrist = landmarks[RIGHT_WRIST]
        response["pose_detected"] = True

        shoulder_width = max(_distance(left_shoulder, right_shoulder), 1e-8)
        torso_length = max(
            _distance(
                _midpoint(left_shoulder, right_shoulder),
                _midpoint(left_hip, right_hip),
            ),
            1e-8,
        )
        view_ratio = shoulder_width / torso_length
        response["view_mode"] = (
            "front"
            if view_ratio >= 0.80
            else "angled" if view_ratio >= 0.48 else "side"
        )

        left_visible = _visible((left_shoulder, left_hip, left_elbow, left_wrist))
        right_visible = _visible((right_shoulder, right_hip, right_elbow, right_wrist))
        any_visible = left_visible or right_visible
        response["left_arm_visible"] = left_visible
        response["right_arm_visible"] = right_visible
        response["both_arms_visible"] = left_visible and right_visible
        response["low_visibility"] = not any_visible

        if not any_visible:
            response["feedback"] = (
                "I can't see either arm clearly — keep a shoulder, elbow, and wrist "
                "inside the frame."
            )
            return response

        framing_points = [
            left_shoulder,
            right_shoulder,
            left_hip,
            right_hip,
        ]
        if left_visible:
            framing_points.extend((left_elbow, left_wrist))
        if right_visible:
            framing_points.extend((right_elbow, right_wrist))
        framing_message = _framing_feedback(framing_points)
        framing_ok = framing_message is None

        mid_shoulder = _midpoint(left_shoulder, right_shoulder)
        mid_hip = _midpoint(left_hip, right_hip)
        torso_dx = abs(mid_hip.x - mid_shoulder.x)
        torso_dy = abs(mid_hip.y - mid_shoulder.y)
        torso_lean_deg = math.degrees(math.atan2(torso_dx, max(torso_dy, 1e-8)))
        # Smooth before thresholding — hip/shoulder landmarks jitter a little every
        # frame, and unsmoothed that jitter alone can flip torso_ok frame to frame.
        self._smoothed_torso_lean = (
            torso_lean_deg
            if self._smoothed_torso_lean is None
            else ANGLE_SMOOTH_ALPHA * torso_lean_deg
            + (1.0 - ANGLE_SMOOTH_ALPHA) * self._smoothed_torso_lean
        )
        torso_ok = self._smoothed_torso_lean <= 18.0

        arm_data: dict[str, dict[str, Any]] = {}
        if left_visible:
            left_angle = _angle_between(left_hip, left_shoulder, left_wrist)
            left_elbow_angle = _angle_between(left_shoulder, left_elbow, left_wrist)
            if left_angle is not None and left_elbow_angle is not None:
                left_corridor = (
                    abs(left_wrist.x - left_shoulder.x) <= shoulder_width * 0.82
                )
                arm_data["left"] = {
                    "state": self.left,
                    "angle": left_angle,
                    "elbow_angle": left_elbow_angle,
                    "position_ok": framing_ok and torso_ok and left_corridor,
                    "position_message": (
                        "Keep the dumbbell in front of your left shoulder, not out to the side."
                        if not left_corridor
                        else None
                    ),
                }
        if right_visible:
            right_angle = _angle_between(right_hip, right_shoulder, right_wrist)
            right_elbow_angle = _angle_between(right_shoulder, right_elbow, right_wrist)
            if right_angle is not None and right_elbow_angle is not None:
                right_corridor = (
                    abs(right_wrist.x - right_shoulder.x) <= shoulder_width * 0.82
                )
                arm_data["right"] = {
                    "state": self.right,
                    "angle": right_angle,
                    "elbow_angle": right_elbow_angle,
                    "position_ok": framing_ok and torso_ok and right_corridor,
                    "position_message": (
                        "Keep the dumbbell in front of your right shoulder, not out to the side."
                        if not right_corridor
                        else None
                    ),
                }

        if not arm_data:
            response["feedback"] = (
                "Move the visible arm away from your body so its joints are clear."
            )
            response["low_visibility"] = True
            return response

        completed: list[dict[str, Any]] = []
        for name, data in arm_data.items():
            arm: _ArmState = data["state"]
            position_now_ok = bool(data["position_ok"])
            if position_now_ok:
                arm.position_good_streak += 1
                arm.position_bad_streak = 0
            else:
                arm.position_good_streak = 0
                arm.position_bad_streak += 1
            if arm.position_good_streak >= POSITION_STABLE_FRAMES:
                arm.ready = True
            elif arm.position_bad_streak >= POSITION_GRACE_FRAMES:
                arm.ready = False
            position_ok = arm.ready and position_now_ok
            data["position_ok"] = position_ok
            if position_ok:
                event = self._process_arm(
                    arm,
                    data["angle"],
                    data["elbow_angle"],
                    timestamp_s,
                    position_ok=True,
                    torso_ok=torso_ok,
                )
                if event:
                    completed.append(event)

        self.rep_count = max(self.left.rep_count, self.right.rep_count)
        self.good_reps = max(self.left.good_reps, self.right.good_reps)
        self.flawed_reps = max(self.left.flawed_reps, self.right.flawed_reps)
        self.stage = (
            "alternating" if self.left.stage != self.right.stage else self.left.stage
        )

        angles = [data["angle"] for data in arm_data.values()]
        smoothed = [
            data["state"].smoothed_angle
            for data in arm_data.values()
            if data["state"].smoothed_angle is not None
        ]
        # During the first few position-stabilization frames an arm may be
        # visible but not yet ready for state-machine updates. Use its raw
        # angle for telemetry instead of emitting an empty aggregate.
        telemetry_smoothed = smoothed or angles
        velocities = []
        for data in arm_data.values():
            arm = data["state"]
            if arm.last_angle is not None and arm.last_timestamp_s is not None:
                # The current update has already stored last_angle, so use the
                # response only as a current telemetry aggregate.
                velocities.append(0.0)

        top_by_arm = {
            name: (
                TOP_ENTER_DEG <= data["state"].smoothed_angle <= MAX_TOP_DEG
                if data["state"].smoothed_angle is not None
                else False
            )
            for name, data in arm_data.items()
        }
        down_by_arm = {
            name: (
                data["state"].smoothed_angle <= DOWN_ENTER_DEG
                if data["state"].smoothed_angle is not None
                else False
            )
            for name, data in arm_data.items()
        }
        position_ok = any(data["position_ok"] for data in arm_data.values())
        position_message = next(
            (
                data["position_message"]
                for data in arm_data.values()
                if not data["position_ok"] and data["position_message"]
            ),
            None,
        )
        if not torso_ok:
            position_message = "Stand tall and keep your ribs stacked over your hips."
        elif not framing_ok:
            position_message = framing_message
        elif position_message is None and not position_ok:
            position_message = "Hold the visible dumbbell down beside your thigh first."

        if completed:
            first = completed[0]
            rep_arms = [item["arm"] for item in completed]
            quality = (
                "good"
                if all(item["quality"] == "good" for item in completed)
                else "needs_improvement"
            )
            response.update(
                {
                    "rep_completed": True,
                    "rep_arms": rep_arms,
                    "rep_duration": round(first["duration"], 3),
                    "rep_avg_speed": (
                        round(first["avg_speed"], 2)
                        if first["avg_speed"] is not None
                        else None
                    ),
                    "rep_classification": first["classification"],
                    "rep_form_quality": quality,
                }
            )
            issue_messages = {
                "rushed_rep": "that one was rushed",
                "too_slow": "that one dragged on too long",
                "insufficient_height": "didn't quite reach shoulder height",
                "raised_too_high": "went above shoulder height — stop there, don't press overhead",
                "bent_elbows": "elbows bent too much — keep them softly extended",
                "torso_lean": "leaned the torso instead of keeping it upright",
            }
            all_issues = sorted(
                {issue for item in completed for issue in item["issues"]}
            )
            if all_issues:
                notes = "; ".join(issue_messages.get(i, i) for i in all_issues)
                feedback = (
                    f"{', '.join(rep_arms).capitalize()} rep counted, but watch form: "
                    f"{notes}."
                )
            else:
                feedback = (
                    f"Clean {', '.join(rep_arms)} rep — total {self.rep_count}. "
                    "You can continue with either hand."
                )
        elif not position_ok:
            feedback = position_message
        elif any(
            data["state"].stage == "raised"
            and data["state"].smoothed_angle is not None
            and data["state"].smoothed_angle > MAX_TOP_DEG
            for data in arm_data.values()
        ):
            feedback = "Stop around shoulder height — don't shrug or press overhead."
        elif any(
            data["state"].stage == "raised"
            and data["state"].smoothed_elbow_angle is not None
            and data["state"].smoothed_elbow_angle < MIN_ELBOW_ANGLE_DEG
            for data in arm_data.values()
        ):
            feedback = "Keep the visible elbow softly extended and lower with control."
        elif any(data["state"].stage == "raised" for data in arm_data.values()):
            feedback = "Good height — lower the raised dumbbell slowly."
        elif self._complete():
            feedback = (
                f"Target reached — {self.target_reps} front-raise rounds completed."
            )
        elif len(arm_data) == 1:
            side = next(iter(arm_data))
            feedback = f"Ready — raise the {side} dumbbell to shoulder height."
        else:
            feedback = "Ready — raise either dumbbell to shoulder height."

        response.update(
            {
                "position_ok": position_ok,
                "position_message": position_message,
                "ready": self.left.ready or self.right.ready,
                "angle": round(sum(angles) / len(angles), 1),
                "smoothed_angle": round(
                    sum(telemetry_smoothed) / len(telemetry_smoothed), 1
                ),
                "left_shoulder_angle": (
                    round(arm_data["left"]["angle"], 1) if "left" in arm_data else None
                ),
                "right_shoulder_angle": (
                    round(arm_data["right"]["angle"], 1)
                    if "right" in arm_data
                    else None
                ),
                "left_elbow_angle": (
                    round(arm_data["left"]["elbow_angle"], 1)
                    if "left" in arm_data
                    else None
                ),
                "right_elbow_angle": (
                    round(arm_data["right"]["elbow_angle"], 1)
                    if "right" in arm_data
                    else None
                ),
                "angle_velocity": (
                    round(sum(velocities) / len(velocities), 2) if velocities else None
                ),
                "top_reached": any(top_by_arm.values()),
                "down_reached": any(down_by_arm.values()),
                "left_top_reached": top_by_arm.get("left", False),
                "right_top_reached": top_by_arm.get("right", False),
                "left_down_reached": down_by_arm.get("left", False),
                "right_down_reached": down_by_arm.get("right", False),
                "framing_ok": framing_ok,
                "framing_message": framing_message,
                "alignment_ok": torso_ok
                and all(
                    bool(data["position_ok"]) or not bool(data["state"].ready)
                    for data in arm_data.values()
                ),
                "alignment_issue": (
                    "Keep your torso upright and raise the dumbbell in front of the shoulder."
                    if not torso_ok or not position_ok
                    else None
                ),
                "stage": self.stage,
                "rep_count": self.rep_count,
                "left_rep_count": self.left.rep_count,
                "right_rep_count": self.right.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "left_good_reps": self.left.good_reps,
                "right_good_reps": self.right.good_reps,
                "left_flawed_reps": self.left.flawed_reps,
                "right_flawed_reps": self.right.flawed_reps,
                "session_complete": self._complete(),
                "feedback": feedback,
            }
        )
        return response


class FrontRaiseSession:
    """Full Front Raise session using one shared PoseEngine and analyzer."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = FrontRaiseAnalyzer(target_reps)
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
