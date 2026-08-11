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

MIN_LANDMARK_VISIBILITY = 0.25

# ---- per-leg reach (ankle-to-own-hip horizontal distance / shoulder width) ----
LEG_DOWN_BELOW = 0.22
LEG_UP_ABOVE = 0.5
LEG_DOWN_IDEAL_BELOW = 0.12  # standing leg genuinely settled, controlled
LEG_UP_IDEAL_ABOVE = 0.75  # a clear, deliberate raise, not a small twitch

# ---- raised-leg straightness (hip-knee-ankle), degrees — graded, not gated ----
KNEE_TOO_BENT_BELOW = 150.0

# ---- standing (support) leg stability, degrees — graded, not gated ----
STANDING_KNEE_TOO_BENT_BELOW = 155.0

# ---- torso lean (shoulder midpoint x vs hip midpoint x) / shoulder width ----
# Some lean is normal for balance; flagged only past a clearly excessive amount.
MAX_TORSO_LEAN_RATIO = 0.35

MISTAKE_PENALTY = {
    "shallow_raise": 10,
    "bent_knee": 10,
    "standing_leg_unstable": 10,
    "leaning": 8,
}

SCORE_HISTORY = 30

# ---- framing (front-facing, standing) ----
FRAME_EDGE_MARGIN = 0.02
BBOX_TOO_CLOSE = 0.97
BBOX_TOO_FAR = 0.12


def _looks_like_a_person(landmarks) -> bool:
    core = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)
    visible = sum(
        1
        for i in core
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible >= 3


def _visible(points) -> bool:
    for p in points:
        if p is None:
            return False
        v = getattr(p, "visibility", None)
        if v is not None and v < MIN_LANDMARK_VISIBILITY:
            return False
    return True


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _angle_deg(a, b, c) -> float:
    ang = math.degrees(
        math.atan2(c.y - b.y, c.x - b.x) - math.atan2(a.y - b.y, a.x - b.x)
    )
    ang = abs(ang)
    if ang > 180:
        ang = 360 - ang
    return ang


def _framing_feedback(points) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — step back so your whole body, "
                "both legs included, fits in the shot."
            )

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "You're too close to the camera — step back so your whole body fits in frame."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class _LegRaiseTracker:
    """One down/up hysteresis state machine for one leg's outward reach.
    Tracks the extreme value reached in each phase for depth/quality
    grading, and counts its own completed cycles independently — see
    module docstring for why no cross-leg synchronization is needed."""

    def __init__(self, label: str):
        self.label = label
        self.stage: str = "down"  # "down" | "up"
        self.reps = 0
        self.down_extreme = 1.0  # min ratio seen since entering "down" (lower = better)
        self.up_extreme = 0.0  # max ratio seen since entering "up" (higher = better)
        self.just_completed = False  # edge-triggered, true for one update() call
        self.last_rep_quality: Optional[str] = None
        self._up_had_bent_knee = False
        self._up_had_unstable_standing = False
        self._up_had_lean = False

    def update(
        self,
        ratio: float,
        knee_bent: bool,
        standing_leg_unstable: bool,
        leaning: bool,
    ) -> None:
        self.just_completed = False

        if self.stage == "down":
            self.down_extreme = min(self.down_extreme, ratio)
            if ratio > LEG_UP_ABOVE:
                self.stage = "up"
                self.up_extreme = ratio
                self._up_had_bent_knee = knee_bent
                self._up_had_unstable_standing = standing_leg_unstable
                self._up_had_lean = leaning
        else:  # "up"
            self.up_extreme = max(self.up_extreme, ratio)
            self._up_had_bent_knee = self._up_had_bent_knee or knee_bent
            self._up_had_unstable_standing = (
                self._up_had_unstable_standing or standing_leg_unstable
            )
            self._up_had_lean = self._up_had_lean or leaning

            if ratio < LEG_DOWN_BELOW:
                self.stage = "down"
                self.down_extreme = ratio

                shallow = self.up_extreme < LEG_UP_IDEAL_ABOVE
                flawed = (
                    shallow
                    or self._up_had_bent_knee
                    or self._up_had_unstable_standing
                    or self._up_had_lean
                )

                self.reps += 1
                self.just_completed = True
                self.last_rep_quality = "needs_improvement" if flawed else "good"


class StandingSideLegRaiseAnalyzer:
    """Stateful Standing Side Leg Raise rep counter — left and right legs
    tracked fully independently, each contributing to the combined total."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.left_leg = _LegRaiseTracker("left")
        self.right_leg = _LegRaiseTracker("right")

        self.good_reps = 0
        self.flawed_reps = 0

        self.session_start_time: Optional[float] = None

    # ---------------------------------------------------------------
    @property
    def rep_count(self) -> int:
        return self.left_leg.reps + self.right_leg.reps

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
            "framing_ok": True,
            "framing_message": None,
            "left_reach_ratio": None,
            "right_reach_ratio": None,
            "left_leg_stage": self.left_leg.stage,
            "right_leg_stage": self.right_leg.stage,
            "left_leg_reps": self.left_leg.reps,
            "right_leg_reps": self.right_leg.reps,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_form_quality": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = (
                "No person detected — step into frame, facing the camera."
            )
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        # Only shoulders/hips/ankles are "required" — they're what the core
        # counting signal (reach_ratio) and the framing check depend on.
        # Knees are used only for quality grading (bent-knee, standing-leg
        # stability), so a momentary knee-visibility dip — common at the
        # top of a raise, when the moving leg's knee is more foreshortened
        # or partially self-occluded by the torso — must not freeze
        # counting. This was the main cause of inconsistent counting: a
        # single low-confidence knee landmark on an otherwise perfectly
        # tracked frame was silently discarding that whole frame.
        required_ok = _visible((l_shoulder, r_shoulder, l_hip, r_hip, l_ankle, r_ankle))
        if not required_ok:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your full body clearly — make sure both legs and "
                "hips are visible, facing the camera."
            )
            return response

        response["pose_detected"] = True

        shoulder_width = max(_dist(l_shoulder, r_shoulder), 1e-6)

        # Framing is checked against the stable landmarks only (shoulders,
        # hips) — the ankles are deliberately excluded here. A real side
        # leg raise swings the ankle outward, toward the frame's edge, on
        # purpose; rejecting the frame right as the ankle approaches the
        # edge was freezing tracking at exactly the moment — the peak of
        # the raise — that most needed to be captured, which was the other
        # main cause of inconsistent counting.
        framing_message = _framing_feedback((l_shoulder, r_shoulder, l_hip, r_hip))
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        if framing_message is not None:
            response["feedback"] = framing_message
            return response

        left_reach_ratio = abs(l_ankle.x - l_hip.x) / shoulder_width
        right_reach_ratio = abs(r_ankle.x - r_hip.x) / shoulder_width
        response["left_reach_ratio"] = round(left_reach_ratio, 2)
        response["right_reach_ratio"] = round(right_reach_ratio, 2)

        # Knee angles are graded only when visible this frame; if a knee is
        # briefly occluded, quality grading just falls back to "unknown"
        # for that landmark rather than blocking anything.
        knees_visible = _visible((l_knee, r_knee))
        left_knee_angle = _angle_deg(l_hip, l_knee, l_ankle) if knees_visible else None
        right_knee_angle = _angle_deg(r_hip, r_knee, r_ankle) if knees_visible else None

        mid_shoulder_x = (l_shoulder.x + r_shoulder.x) / 2.0
        mid_hip_x = (l_hip.x + r_hip.x) / 2.0
        torso_lean_ratio = abs(mid_shoulder_x - mid_hip_x) / shoulder_width
        leaning = torso_lean_ratio > MAX_TORSO_LEAN_RATIO

        # Which leg is currently the "raised" one is whichever has the
        # larger reach ratio this frame — used only to decide which knee
        # angle is "the raised leg's" vs "the standing leg's" for grading.
        left_is_raised_side = left_reach_ratio >= right_reach_ratio

        left_knee_bent = (
            left_knee_angle is not None and left_knee_angle < KNEE_TOO_BENT_BELOW
        )
        right_knee_bent = (
            right_knee_angle is not None and right_knee_angle < KNEE_TOO_BENT_BELOW
        )
        left_standing_unstable = (
            left_knee_angle is not None
            and left_knee_angle < STANDING_KNEE_TOO_BENT_BELOW
        )
        right_standing_unstable = (
            right_knee_angle is not None
            and right_knee_angle < STANDING_KNEE_TOO_BENT_BELOW
        )

        # For whichever leg is actually raising, grade its OWN knee
        # straightness as "bent_knee", and the OTHER leg's knee stability
        # as "standing_leg_unstable" — swapped depending on which side is
        # currently active.
        self.left_leg.update(
            left_reach_ratio,
            knee_bent=left_knee_bent,
            standing_leg_unstable=(
                right_standing_unstable if left_is_raised_side else False
            ),
            leaning=leaning,
        )
        self.right_leg.update(
            right_reach_ratio,
            knee_bent=right_knee_bent,
            standing_leg_unstable=(
                left_standing_unstable if not left_is_raised_side else False
            ),
            leaning=leaning,
        )

        response["left_leg_stage"] = self.left_leg.stage
        response["right_leg_stage"] = self.right_leg.stage

        rep_completed = False
        quality: Optional[str] = None
        feedback: Optional[str] = None

        if self.left_leg.just_completed:
            rep_completed = True
            quality = self.left_leg.last_rep_quality
            if quality == "good":
                self.good_reps += 1
                feedback = f"Left leg rep {self.left_leg.reps} counted!"
            else:
                self.flawed_reps += 1
                feedback = f"Left leg rep {self.left_leg.reps} counted — raise higher, keep it controlled."

        if self.right_leg.just_completed:
            rep_completed = True
            right_quality = self.right_leg.last_rep_quality
            if right_quality == "good":
                self.good_reps += 1
            else:
                self.flawed_reps += 1
            # In the (rare) case both legs complete on the same processed
            # frame, prefer reporting whichever is worse so the coaching
            # message doesn't hide a flaw, and don't overwrite a message
            # that's already set for the left leg with a duplicate one.
            if feedback is None:
                quality = right_quality
                if right_quality == "good":
                    feedback = f"Right leg rep {self.right_leg.reps} counted!"
                else:
                    feedback = f"Right leg rep {self.right_leg.reps} counted — raise higher, keep it controlled."
            elif right_quality == "needs_improvement":
                quality = "needs_improvement"

        if feedback is None:
            if self.left_leg.stage == "up":
                feedback = "Left leg raised — lower back down with control."
            elif self.right_leg.stage == "up":
                feedback = "Right leg raised — lower back down with control."
            else:
                feedback = "Ready — raise a leg out to the side."

        response.update(
            {
                "left_leg_reps": self.left_leg.reps,
                "right_leg_reps": self.right_leg.reps,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_form_quality": quality,
                "feedback": feedback,
            }
        )
        return response


class StandingSideLegRaiseSession:
    """Full session: one shared pose model + one analyzer.

    `target_reps` / `target_sets` / `set_number` are the coach-assigned
    plan for this user, supplied by the caller (the websocket route, from
    query params) — same convention as the other rep-based sessions in
    this codebase. The frontend does not decide on its own whether a
    set/exercise is done; `session_complete` and `exercise_complete` are
    both computed here.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = StandingSideLegRaiseAnalyzer(target_reps)
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
