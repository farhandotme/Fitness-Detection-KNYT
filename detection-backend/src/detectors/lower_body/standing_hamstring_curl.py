"""
Standing Hamstring Curl rep counting + posture correction.

The movement
------------
Standing upright on one leg (the other planted for balance, or lightly
touching down), the working leg's heel curls up and back toward the
glute — knee flexion only. The thigh stays roughly vertical and the hip
stays extended throughout; nothing about the hip joint changes, only the
knee. That's what separates this from a superficially similar movement
like a high-knee or knee raise, where the *thigh* swings forward (hip
flexion) — here the thigh doesn't move, only the shin folds back.
Rep-based; alternates legs, and — same as Standing Side Leg Raise —
each leg's curl-and-extend cycle counts toward the total independently.

Primary signal: knee angle, not a distance ratio
------------------------------------------------------
Every exercise before this one that tracked a limb used a
distance-based ratio (wrist-to-shoulder, ankle-to-hip, etc.) normalized
by shoulder width, because the defining motion was mostly lateral or
mostly vertical translation. A hamstring curl is different: the single
most direct, unambiguous signal for "how much has this knee bent" is
the knee angle itself (hip-knee-ankle), which needs no normalization by
body scale at all — it's a pure angle, immune to the camera-distance
sensitivity that a ratio-based signal has. Standing (rest) reads close
to a straight leg (near 180°); a full curl drops it sharply. This also
means camera framing is more forgiving here than in the ratio-based
exercises — the signal works about as well from a front-facing or a
3/4 angle, since it doesn't depend on how a distance projects onto the
image plane.

Why hip flexion is graded, not gated
------------------------------------------
The thigh swinging forward (turning this into a knee raise instead of a
curl) is a real form fault worth catching — `hip_angle` (shoulder-hip-
knee) is tracked for exactly that. But making it a hard, continuous gate
risks the same failure this codebase has hit more than once already
(Skier Jumping Jacks, and the intermittent-counting bug just fixed in
Standing Side Leg Raise): some natural forward lean is unavoidable for
balance, varies by person and camera angle, and a strict continuous
check can silently zero out counting on genuinely correct reps. So
`hip_angle` — along with the standing leg staying stable and the knee
not drifting out to the side — is folded into `rep_form_quality`
instead of blocking the count.

Fixed: framing size check was measuring the wrong thing
----------------------------------------------------------------
An earlier version checked "too close/too far" using only the two hip
points as the reference span. Hip-to-hip distance is always small —
it's not a meaningful stand-in for how much of the frame the person
actually occupies — so that check was flagging correctly-framed reps as
"too far" essentially all the time, which silently blocked every rep
before knee-angle tracking ever ran. The size check now uses whichever
of the shoulder/hip points are currently visible (a real torso-sized
span), while the edge-margin check and all counting logic still
deliberately exclude the knee/ankle, which are supposed to move.

Landmarks required vs. landmarks only used for grading
-------------------------------------------------------------
Learned directly from fixing the Standing Side Leg Raise analyzer:
core counting only needs the hip, knee, and ankle of each leg (the three
points the knee angle is built from). The shoulder landmarks are only
needed for the hip-flexion quality check and the framing box — so a
momentary shoulder-visibility dip degrades quality grading for that
frame, not counting itself. Framing is checked against the stable hip/
shoulder landmarks only, not the moving ankle, for the same reason
documented in the Side Leg Raise fix: the ankle is *supposed* to move
during this exercise, and rejecting a frame because the working ankle
is mid-curl would freeze tracking at exactly the moment it matters most.
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

MIN_LANDMARK_VISIBILITY = 0.25

# ---- knee angle (hip-knee-ankle), degrees — the core counting signal ----
KNEE_STRAIGHT_ABOVE = 155.0  # standing/rest position
KNEE_CURLED_BELOW = 100.0  # a clear, deliberate curl
KNEE_CURLED_IDEAL_BELOW = 65.0  # heel genuinely close to the glute — "good" tier
KNEE_STRAIGHT_IDEAL_ABOVE = 165.0  # fully, controlled extension between reps

# ---- hip flexion (shoulder-hip-knee), degrees — graded, not gated ----
# Thigh should stay close to vertical/in line with the torso; a real curl
# doesn't swing the hip forward. Only flagged well past normal balance lean.
HIP_FLEXING_BELOW = 150.0

# ---- standing (support) leg stability, degrees — graded, not gated ----
STANDING_KNEE_TOO_BENT_BELOW = 155.0

MISTAKE_PENALTY = {
    "shallow_curl": 10,
    "hip_flexing": 10,
    "standing_leg_unstable": 8,
    "incomplete_extension": 6,
}

SCORE_HISTORY = 30

# ---- framing (front-facing or 3/4 angle, standing) ----
FRAME_EDGE_MARGIN = 0.02
BBOX_TOO_CLOSE = 0.97
BBOX_TOO_FAR = 0.10


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
                "You're partly out of frame — step back so your whole body "
                "fits in the shot."
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


class _CurlTracker:
    """One straight/curled hysteresis state machine for one leg's knee
    angle. Tracks the extreme value reached in each phase for depth/
    quality grading, and counts its own completed cycles independently —
    each leg contributes to the combined total without needing the other
    leg to agree, since this exercise is single-limb by design."""

    def __init__(self):
        self.stage: str = "straight"  # "straight" | "curled"
        self.reps = 0
        self.straight_extreme = (
            0.0  # max angle seen since entering "straight" (higher = better)
        )
        self.curled_extreme = (
            180.0  # min angle seen since entering "curled" (lower = better)
        )
        self.just_completed = False  # edge-triggered, true for one update() call
        self.last_rep_quality: Optional[str] = None
        self._curl_had_hip_flex = False
        self._curl_had_unstable_standing = False

    def update(
        self,
        knee_angle: float,
        hip_flexing: bool,
        standing_leg_unstable: bool,
    ) -> None:
        self.just_completed = False

        if self.stage == "straight":
            self.straight_extreme = max(self.straight_extreme, knee_angle)
            if knee_angle < KNEE_CURLED_BELOW:
                self.stage = "curled"
                self.curled_extreme = knee_angle
                self._curl_had_hip_flex = hip_flexing
                self._curl_had_unstable_standing = standing_leg_unstable
        else:  # "curled"
            self.curled_extreme = min(self.curled_extreme, knee_angle)
            self._curl_had_hip_flex = self._curl_had_hip_flex or hip_flexing
            self._curl_had_unstable_standing = (
                self._curl_had_unstable_standing or standing_leg_unstable
            )

            if knee_angle > KNEE_STRAIGHT_ABOVE:
                self.stage = "straight"
                self.straight_extreme = knee_angle

                shallow = self.curled_extreme > KNEE_CURLED_IDEAL_BELOW
                incomplete_extension = knee_angle < KNEE_STRAIGHT_IDEAL_ABOVE
                flawed = (
                    shallow
                    or incomplete_extension
                    or self._curl_had_hip_flex
                    or self._curl_had_unstable_standing
                )

                self.reps += 1
                self.just_completed = True
                self.last_rep_quality = "needs_improvement" if flawed else "good"


class StandingHamstringCurlAnalyzer:
    """Stateful Standing Hamstring Curl rep counter — left and right legs
    tracked fully independently via direct knee-angle measurement, each
    contributing to the combined total."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.left_leg = _CurlTracker()
        self.right_leg = _CurlTracker()

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
            "left_knee_angle": None,
            "right_knee_angle": None,
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

        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]
        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]

        # Core counting only needs hip/knee/ankle per leg — see module
        # docstring for why shoulders are handled separately, as
        # grading-only landmarks.
        required_ok = _visible((l_hip, r_hip, l_knee, r_knee, l_ankle, r_ankle))
        if not required_ok:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your legs clearly — make sure both hips, knees "
                "and ankles are visible, facing the camera."
            )
            return response

        response["pose_detected"] = True

        # Framing checked against hips only (the most stable, always-
        # present reference points) — never the knees/ankles, which are
        # supposed to move during this exercise.
        # The framing SIZE check (too close/too far) needs points that
        # actually span the person's presence in frame — using only the
        # two hip points (as an earlier version did) measures nothing
        # more than hip width, which is small regardless of how far the
        # person actually is from the camera, and was flagging correctly
        # -framed reps as "too far" every time. Shoulders + hips give a
        # real torso-sized span. Ankles/knees are still deliberately
        # excluded — they're supposed to move during this exercise, and
        # rejecting a frame because the working ankle is mid-curl would
        # freeze tracking right when it matters most.
        framing_points = [
            p for p in (l_shoulder, r_shoulder, l_hip, r_hip) if _visible((p,))
        ]
        if len(framing_points) < 3:
            # Not enough visible reference points to judge size reliably
            # this frame — don't block on a call we can't make with
            # confidence; just skip the size check for this frame.
            framing_message = None
        else:
            framing_message = _framing_feedback(framing_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        if framing_message is not None:
            response["feedback"] = framing_message
            return response

        left_knee_angle = _angle_deg(l_hip, l_knee, l_ankle)
        right_knee_angle = _angle_deg(r_hip, r_knee, r_ankle)
        response["left_knee_angle"] = round(left_knee_angle, 1)
        response["right_knee_angle"] = round(right_knee_angle, 1)

        # Hip-flexion grading needs the shoulders — optional, degrades
        # gracefully rather than blocking anything if they're briefly
        # not visible.
        shoulders_visible = _visible((l_shoulder, r_shoulder))
        left_hip_angle = (
            _angle_deg(l_shoulder, l_hip, l_knee) if shoulders_visible else None
        )
        right_hip_angle = (
            _angle_deg(r_shoulder, r_hip, r_knee) if shoulders_visible else None
        )

        left_hip_flexing = (
            left_hip_angle is not None and left_hip_angle < HIP_FLEXING_BELOW
        )
        right_hip_flexing = (
            right_hip_angle is not None and right_hip_angle < HIP_FLEXING_BELOW
        )
        left_standing_unstable = right_knee_angle < STANDING_KNEE_TOO_BENT_BELOW
        right_standing_unstable = left_knee_angle < STANDING_KNEE_TOO_BENT_BELOW

        # Which leg is currently curling is whichever has the smaller
        # knee angle this frame — used only to decide which side's hip
        # flexion is graded as "the curling leg's fault" this frame.
        left_is_curling_side = left_knee_angle <= right_knee_angle

        self.left_leg.update(
            left_knee_angle,
            hip_flexing=left_hip_flexing if left_is_curling_side else False,
            standing_leg_unstable=(
                left_standing_unstable if left_is_curling_side else False
            ),
        )
        self.right_leg.update(
            right_knee_angle,
            hip_flexing=right_hip_flexing if not left_is_curling_side else False,
            standing_leg_unstable=(
                right_standing_unstable if not left_is_curling_side else False
            ),
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
                feedback = (
                    f"Left leg rep {self.left_leg.reps} counted — curl higher, "
                    "keep your hips still."
                )

        if self.right_leg.just_completed:
            rep_completed = True
            right_quality = self.right_leg.last_rep_quality
            if right_quality == "good":
                self.good_reps += 1
            else:
                self.flawed_reps += 1
            if feedback is None:
                quality = right_quality
                if right_quality == "good":
                    feedback = f"Right leg rep {self.right_leg.reps} counted!"
                else:
                    feedback = (
                        f"Right leg rep {self.right_leg.reps} counted — curl higher, "
                        "keep your hips still."
                    )
            elif right_quality == "needs_improvement":
                quality = "needs_improvement"

        if feedback is None:
            if self.left_leg.stage == "curled":
                feedback = "Left leg curled — lower back down with control."
            elif self.right_leg.stage == "curled":
                feedback = "Right leg curled — lower back down with control."
            else:
                feedback = "Ready — curl a heel up toward your glute."

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


class StandingHamstringCurlSession:
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
        self.analyzer = StandingHamstringCurlAnalyzer(target_reps)
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
