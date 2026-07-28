"""
Dancer Pose (Natarajasana) hold timing + posture correction.

Design
------
Same family as `WallSitAnalyzer` / `HalfMoonAnalyzer` — Dancer Pose has
no reps, it's a single continuous standing balance hold, so this does
**not** run a rep state machine. It runs the identical **hold timer that
only advances while the person is verified, frame by frame, to actually
be in a valid Dancer shape**:

    * The instant the shape breaks (the kicked-back leg straightens out
      or drops, the standing leg buckles, the torso folds all the way
      forward, or the camera loses the person) the timer **pauses**. It
      never silently resets to zero, so accumulated `hold_seconds` is
      monotonic for the lifetime of a set. `current_streak_seconds`
      (time since the last break) is what resets, giving live feedback
      on the *current* attempt without punishing total progress.
    * The instant a valid shape returns, the timer picks back up from
      exactly where it left off.

Balance wobble is expected and is explicitly not the same as a hard
break — small shifts show up in `balance_confidence` (a rolling measure
of how consistently the last ~1.5s held the pose), not as the timer
stopping.

Standing vs. kicked-back leg
------------------------------
Like Half Moon, Dancer Pose is asymmetric, so each frame first works out
`standing_side` from relative ankle height — whichever ankle sits
clearly lower in the frame is standing, the other is the kicked-back
leg. The assignment is kept "sticky" across frames (same convention used
in `HalfMoonAnalyzer._pick_standing_side`) so one noisy frame can't spin
the pose around. Role decisions only look at the hip and ankle for this
(not the knee or shoulder) since the kicked-back leg is often folded
partly behind the torso and gets a lower confidence score from the pose
model even when it's genuinely visible — requiring the full leg tuple
here caused exactly this kind of correct-but-rejected attempt on the
Half Moon detector, so this one is written the same forgiving way from
the start.

Form signal
-----------
Dancer Pose is the mirror image of Half Moon's "extend the leg out"
requirement — here the back leg has to be BENT, not straight, with the
same-side hand catching the foot and kicking it up and back while the
front arm reaches forward and the torso opens/tilts forward as a
counterbalance:

  * `lifted_knee_angle` = angle(hip, knee, ankle) on the kicked-back leg.
    Needs to read as clearly bent (low angle) — a straight leg just
    lifted behind the body is not Natarajasana, it's closer to a warrior
    3 kick.
  * `standing_knee_angle` = angle(hip, knee, ankle) on the standing leg.
    A slight bend is fine for balance; a deep bend turns this into a
    lunge/squat.
  * `leg_height_ratio` = how far above the standing foot the kicked-back
    ankle sits, normalized by standing-leg length — confirms the leg is
    actually lifted, not just bent while resting near the ground.
  * `standing_hip_angle` = angle(shoulder, hip, knee) on the standing
    side, guarding against folding all the way forward into something
    closer to a standing forward bend than an open, chest-lifted Dancer
    shape. Some forward lean is normal and expected here (more than
    Half Moon), so this threshold is deliberately looser than the
    equivalent Half Moon check.

Softer, secondary signals (grade quality, never pause the timer):

  * `front_arm_reach` = how far the front wrist extends forward from its
    shoulder, normalized by torso length — the counterbalancing arm.
  * `hand_foot_gap` = distance between the back wrist and the kicked-back
    ankle, normalized by standing-leg length — confirms the classic
    "kick the foot into the hand" grip, when the pose isn't strap-assisted.
  * `standing_side_lean_angle` / knee-lock, same idea as the other hold
    analyzers.

Support modifier
----------------
Same approach as Half Moon's `support_mode`: there's no object detection
in this codebase, so the frontend tells the backend what's being used —
`"free"`, `"wall"` (for balance), or `"strap"` (a yoga strap bridging
hand to foot when flexibility doesn't allow a direct grip yet) — as a
session query param, and it's used purely as a threshold modifier: a
wall relaxes the standing-side lean check, a strap relaxes the
hand-to-foot distance check. Neither relaxes the core "is this actually
Dancer Pose" gates (leg bend, lift height, standing knee, fold).
"""

import math
from collections import deque
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    LEFT_WRIST,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)

# -------------------------------------------------------------------------
# Tunable constants
# -------------------------------------------------------------------------

LEG_LANDMARKS = {
    "left": (LEFT_SHOULDER, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE),
    "right": (RIGHT_SHOULDER, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE),
}
WRIST_LANDMARKS = {"left": LEFT_WRIST, "right": RIGHT_WRIST}
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)

SUPPORT_MODES = ("free", "wall", "strap")

MIN_LANDMARK_VISIBILITY = 0.4

# Threshold used specifically to decide standing-vs-kicked-back role.
# Deliberately lighter than a full-leg-tuple check (see module docstring)
# — only the hip and ankle are read to make this call, so a genuinely
# visible but lower-confidence kicked-back leg still gets picked up.
STANCE_VISIBILITY_MIN = 0.3

# ---- which leg is standing vs kicked back ----
STANCE_MARGIN = 0.08

# ---- lifted-leg height (normalized by standing leg length) ----
# Only a leg that's essentially back down is a hard break — a leg that's
# up but short of a deep kick is a soft "lift it higher" note.
LIFT_BREAK = 0.10
LIFT_RESUME = 0.15
LIFT_IDEAL = 0.35

# ---- kicked-back knee angle (hip-knee-ankle), degrees ----
# LOW angle = bent (correct). A leg that's basically straight behind the
# body isn't Dancer Pose. Hysteresis runs opposite to the other
# analyzers' extension checks since here we want the SMALL-angle side.
BEND_BREAK = 155.0  # while holding, straightening past this breaks it
BEND_RESUME = 140.0  # to resume, must bend back below this
BEND_IDEAL_MAX = 105.0  # at/below this, knee-bend tier reads as "good"

# ---- standing knee angle (hip-knee-ankle), degrees ----
STANDING_KNEE_BREAK = 120.0
STANDING_KNEE_RESUME = 132.0

# ---- standing-side hip angle (shoulder-hip-knee), degrees ----
# Looser than Half Moon's equivalent check — Dancer Pose is expected to
# lean/open forward more than Half Moon's sideways-open shape.
FOLD_BREAK = 38.0
FOLD_RESUME = 48.0

# ---- front-arm reach: (front_wrist.x - front_shoulder.x) forward distance ----
# normalized by torso length; direction-agnostic (absolute value), since
# "forward" could be either side of the frame depending on which way the
# person is facing.
REACH_IDEAL = 0.30

# ---- hand-to-foot connection gap, normalized by standing leg length ----
HAND_FOOT_IDEAL = 0.22

# ---- standing-side lean angle (shoulder->hip vs vertical), degrees ----
LEAN_SOFT_MAX = 45.0

MISTAKE_PENALTY = {
    "leg_lift_low": 12,
    "knee_not_bent_enough": 10,
    "front_arm_not_reaching": 10,
    "hand_foot_not_connected": 10,
    "leaning_into_standing_side": 10,
}

SCORE_HISTORY = 30
SCORE_SAMPLE_INTERVAL = 1.0  # seconds
BALANCE_WINDOW = 45  # rolling holding/not-holding window (~1.5s)

# -------------------------------------------------------------------------
# Camera framing thresholds (front / slight front-side oblique view).
# -------------------------------------------------------------------------
FRAME_EDGE_MARGIN = 0.03
BODY_SPAN_TOO_CLOSE = 0.95
BODY_SPAN_TOO_FAR = 0.22


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 2


def _stance_visibility(landmarks, side: str) -> float:
    """Lowest visibility between just the hip and ankle on `side` — the
    only two landmarks role-assignment actually reads."""
    _, hip_i, _, ankle_i = LEG_LANDMARKS[side]
    hip_v = landmarks[hip_i].visibility
    ankle_v = landmarks[ankle_i].visibility
    return min(
        hip_v if hip_v is not None else 0.0,
        ankle_v if ankle_v is not None else 0.0,
    )


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


def _vertical_deviation_deg(top, bottom) -> float:
    """Angle of the vector top->bottom from straight-down vertical, in
    degrees. 0deg = perfectly plumb."""
    dx = bottom.x - top.x
    dy = bottom.y - top.y
    if dx == 0 and dy == 0:
        return 0.0
    return math.degrees(math.atan2(abs(dx), abs(dy))) if dy != 0 else 90.0


def _framing_feedback(all_points) -> Optional[str]:
    """Coaches the user into a good spot for the camera — checked every
    frame, independent of exercise form. Dancer Pose's silhouette is
    tall and can lean forward quite a bit, so this only checks
    edge-clipping and overall distance, not an upright shape."""
    for p in all_points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — step back so your whole "
                "shape, kicked-back leg and reaching arm included, fits "
                "in the shot."
            )

    xs = [p.x for p in all_points]
    ys = [p.y for p in all_points]
    span = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    if span > BODY_SPAN_TOO_CLOSE:
        return "You're too close to the camera — step back until your whole body fits in frame."
    if span < BODY_SPAN_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class DancerPoseAnalyzer:
    """Stateful Dancer Pose hold timer + posture checker.

    No `target_reps` here — the coach-assigned target is a duration,
    `target_seconds`. `session_complete` is `hold_seconds >= target_seconds`,
    exactly mirroring the other hold analyzers.
    """

    def __init__(
        self,
        target_seconds: Optional[int] = None,
        support_mode: str = "free",
    ):
        self.target_seconds = target_seconds
        self.support_mode = support_mode if support_mode in SUPPORT_MODES else "free"

        self.standing_side: Optional[str] = None

        self.hold_active = False
        self.started = False
        self.hold_seconds = 0.0
        self.good_seconds = 0.0
        self.flawed_seconds = 0.0
        self.current_streak_seconds = 0.0
        self.best_streak_seconds = 0.0
        self.break_count = 0

        self.last_timestamp_s: Optional[float] = None
        self.session_start_time: Optional[float] = None

        self._was_complete = False

        self.form_scores: deque[int] = deque(maxlen=SCORE_HISTORY)
        self._last_score_sample_time: Optional[float] = None
        self._balance_window: deque[bool] = deque(maxlen=BALANCE_WINDOW)

    # ---------------------------------------------------------------
    def _is_complete(self) -> bool:
        return (
            self.target_seconds is not None and self.hold_seconds >= self.target_seconds
        )

    def _pick_standing_side(self, landmarks) -> Optional[str]:
        """Decide standing vs kicked-back leg from relative ankle height,
        sticky across frames — same convention as
        `HalfMoonAnalyzer._pick_standing_side`."""
        vis = {side: _stance_visibility(landmarks, side) for side in ("left", "right")}
        if vis["left"] < STANCE_VISIBILITY_MIN or vis["right"] < STANCE_VISIBILITY_MIN:
            return None

        l_ankle = landmarks[LEFT_ANKLE]
        r_ankle = landmarks[RIGHT_ANKLE]
        diff = l_ankle.y - r_ankle.y  # positive => left ankle lower (standing)

        if self.standing_side == "left":
            return "right" if diff < -STANCE_MARGIN else "left"
        if self.standing_side == "right":
            return "left" if diff > STANCE_MARGIN else "right"

        if diff > STANCE_MARGIN:
            return "left"
        if diff < -STANCE_MARGIN:
            return "right"
        return None

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "standing_side": self.standing_side,
            "leg_height_ratio": None,
            "lifted_leg_height": None,
            "lifted_knee_angle": None,
            "standing_knee_angle": None,
            "standing_hip_angle": None,
            "standing_side_lean_angle": None,
            "front_arm_reach": None,
            "hand_foot_gap": None,
            "front_arm_reach_ok": True,
            "hand_foot_connected": True,
            "balance_confidence": None,
            "support_mode": self.support_mode,
            "wall_supported": self.support_mode == "wall",
            "strap_supported": self.support_mode == "strap",
            "hold_state": (
                "holding"
                if self.started and self.hold_active
                else ("broken" if self.started else "not_started")
            ),
            "is_holding": False,
            "hold_seconds": round(self.hold_seconds, 2),
            "good_seconds": round(self.good_seconds, 2),
            "flawed_seconds": round(self.flawed_seconds, 2),
            "current_streak_seconds": round(self.current_streak_seconds, 2),
            "best_streak_seconds": round(self.best_streak_seconds, 2),
            "break_count": self.break_count,
            "target_seconds": self.target_seconds,
            "session_complete": self._is_complete(),
            "target_reached": False,
            "hold_quality": None,
            "posture_ok": True,
            "posture_issues": [],
            "posture_messages": [],
            "framing_ok": True,
            "framing_message": None,
            "form_score": None,
            "avg_form_score": self._avg(self.form_scores),
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        dt = 0.0
        if self.last_timestamp_s is not None:
            dt = max(0.0, min(t - self.last_timestamp_s, 0.5))
        self.last_timestamp_s = t

        if landmarks is None or not _looks_like_a_person(landmarks):
            self._register_broken_frame()
            response["feedback"] = (
                "No person detected — step into frame, facing the camera, "
                "with room to kick a leg back."
            )
            response.update(self._progress_fields())
            return response

        self.standing_side = self._pick_standing_side(landmarks)
        if self.standing_side is None:
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._register_broken_frame()
            response["feedback"] = (
                "Can't see both legs clearly — step back so your whole "
                "body is visible to the camera."
            )
            response.update(self._progress_fields())
            return response

        lifted_side = "right" if self.standing_side == "left" else "left"
        s_sh_i, s_hip_i, s_knee_i, s_ank_i = LEG_LANDMARKS[self.standing_side]
        l_sh_i, l_hip_i, l_knee_i, l_ank_i = LEG_LANDMARKS[lifted_side]

        standing_shoulder = landmarks[s_sh_i]
        standing_hip = landmarks[s_hip_i]
        standing_knee = landmarks[s_knee_i]
        standing_ankle = landmarks[s_ank_i]

        lifted_hip = landmarks[l_hip_i]
        lifted_knee = landmarks[l_knee_i]
        lifted_ankle = landmarks[l_ank_i]

        framing_message = _framing_feedback(
            [
                standing_shoulder,
                standing_hip,
                standing_ankle,
                lifted_hip,
                lifted_ankle,
            ]
        )

        standing_leg_len = max(_dist(standing_hip, standing_ankle), 1e-6)
        leg_height_ratio = (standing_ankle.y - lifted_ankle.y) / standing_leg_len

        lifted_knee_angle = _angle_deg(lifted_hip, lifted_knee, lifted_ankle)
        standing_knee_angle = _angle_deg(standing_hip, standing_knee, standing_ankle)
        standing_hip_angle = _angle_deg(standing_shoulder, standing_hip, standing_knee)
        standing_side_lean_angle = _vertical_deviation_deg(
            standing_shoulder, standing_hip
        )

        torso_len = max(_dist(standing_shoulder, standing_hip), 1e-6)

        # Front arm = same side as the standing leg (counterbalances
        # forward); back arm = same side as the kicked-back leg (reaches
        # back to catch the foot).
        front_wrist = landmarks[WRIST_LANDMARKS[self.standing_side]]
        back_wrist = landmarks[WRIST_LANDMARKS[lifted_side]]
        front_shoulder = standing_shoulder

        front_arm_visible = (
            front_wrist.visibility is not None
            and front_wrist.visibility >= MIN_LANDMARK_VISIBILITY
        )
        front_arm_reach = (
            abs(front_wrist.x - front_shoulder.x) / torso_len
            if front_arm_visible
            else None
        )

        back_wrist_visible = (
            back_wrist.visibility is not None
            and back_wrist.visibility >= MIN_LANDMARK_VISIBILITY
        )
        hand_foot_gap = (
            _dist(back_wrist, lifted_ankle) / standing_leg_len
            if back_wrist_visible
            else None
        )

        # ---- support-mode threshold modifiers ----
        # A wall makes some lean into it expected; a strap bridges hand
        # to foot, so it shouldn't be graded as if the hand fell short.
        # Neither relaxes the core "is this actually Dancer Pose" gates.
        lean_soft_max = LEAN_SOFT_MAX * (1.4 if self.support_mode == "wall" else 1.0)
        hand_foot_ideal = HAND_FOOT_IDEAL * (
            2.2 if self.support_mode == "strap" else 1.0
        )

        # ---- resolve hold-validity this frame (with hysteresis) ----
        if self.hold_active:
            leg_too_low = leg_height_ratio < LIFT_BREAK
            knee_too_straight = lifted_knee_angle > BEND_BREAK
            standing_too_bent = standing_knee_angle < STANDING_KNEE_BREAK
            torso_folded = standing_hip_angle < FOLD_BREAK
        else:
            leg_too_low = leg_height_ratio < LIFT_RESUME
            knee_too_straight = lifted_knee_angle > BEND_RESUME
            standing_too_bent = standing_knee_angle < STANDING_KNEE_RESUME
            torso_folded = standing_hip_angle < FOLD_RESUME

        hard_break = (
            leg_too_low or knee_too_straight or standing_too_bent or torso_folded
        )
        holding_now = framing_message is None and not hard_break

        # ---- form tiering (only meaningful while holding) ----
        issues: list[str] = []
        messages: list[str] = []
        front_arm_reach_ok = True
        hand_foot_connected = True

        if holding_now:
            if leg_height_ratio < LIFT_IDEAL:
                issues.append("leg_lift_low")
                messages.append("Kick the back leg up a little higher.")

            # Knee bend and kick height are correlated, not independent —
            # a very high kick (leg_height_ratio already at/above ideal)
            # can be achieved through more hip/back extension with a
            # slightly more open knee, and that's not a flaw. Only nudge
            # on knee bend when the kick ISN'T already reading as
            # excellent, so an outstanding pose doesn't get nitpicked on
            # a secondary, correlated measurement.
            if leg_height_ratio < LIFT_IDEAL and lifted_knee_angle > BEND_IDEAL_MAX:
                issues.append("knee_not_bent_enough")
                messages.append("Bend the back knee more and kick into your hand.")

            if front_arm_visible:
                if front_arm_reach is not None and front_arm_reach < REACH_IDEAL:
                    front_arm_reach_ok = False
                    issues.append("front_arm_not_reaching")
                    messages.append("Reach the front arm forward for balance.")
            else:
                front_arm_reach_ok = False

            if self.support_mode != "strap":
                if back_wrist_visible:
                    if hand_foot_gap is not None and hand_foot_gap > hand_foot_ideal:
                        hand_foot_connected = False
                        issues.append("hand_foot_not_connected")
                        messages.append(
                            "Reach back and connect your hand to your ankle or foot."
                        )
                else:
                    hand_foot_connected = False

            if standing_side_lean_angle > lean_soft_max:
                issues.append("leaning_into_standing_side")
                messages.append(
                    "Lift through your chest rather than leaning on your standing side."
                )

        # ---- advance / pause the timer ----
        form_score = None
        hold_quality = None
        if holding_now:
            if not self.hold_active:
                self.current_streak_seconds = 0.0
            self.hold_active = True
            self.started = True

            self.hold_seconds += dt
            self.current_streak_seconds += dt
            if self.current_streak_seconds > self.best_streak_seconds:
                self.best_streak_seconds = self.current_streak_seconds

            if issues:
                self.flawed_seconds += dt
                hold_quality = "needs_improvement"
            else:
                self.good_seconds += dt
                hold_quality = "good"

            form_score = 100
            for issue in issues:
                form_score -= MISTAKE_PENALTY.get(issue, 10)
            form_score = max(0, form_score)

            if (
                self._last_score_sample_time is None
                or t - self._last_score_sample_time >= SCORE_SAMPLE_INTERVAL
            ):
                self.form_scores.append(form_score)
                self._last_score_sample_time = t
        else:
            self._register_broken_frame()

        self._balance_window.append(holding_now)
        balance_confidence = round(
            100 * sum(self._balance_window) / len(self._balance_window)
        )

        is_complete = self._is_complete()
        target_reached = is_complete and not self._was_complete
        self._was_complete = is_complete

        # ---- feedback priority: framing > hard break > form flaws > praise ----
        feedback = framing_message
        if feedback is None and leg_too_low:
            feedback = "Kick your back leg up and into your hand."
        if feedback is None and knee_too_straight:
            feedback = (
                "Bend the back knee — Dancer Pose kicks the heel up, not out straight."
            )
        if feedback is None and standing_too_bent:
            feedback = (
                "Press into the standing leg and straighten it a bit more for balance."
            )
        if feedback is None and torso_folded:
            feedback = (
                "Lift your chest instead of folding forward over your standing leg."
            )
        if feedback is None and messages:
            feedback = messages[0]
        if feedback is None and not self.started and holding_now:
            feedback = "Nice — you're balanced in Dancer Pose, stay steady!"
        if feedback is None and target_reached:
            feedback = f"Target reached — {self.target_seconds}s held, beautiful!"
        if feedback is None and holding_now:
            feedback = "Kick into your hand and reach the front arm forward!"
        if feedback is None and self.hold_active is False and self.started:
            feedback = "A little wobble is fine — find your gaze point and reset."
        if feedback is None:
            feedback = "Stand on one leg, bend the other knee, and reach back for your foot to begin."

        response.update(
            {
                "pose_detected": True,
                "standing_side": self.standing_side,
                "leg_height_ratio": round(leg_height_ratio, 2),
                "lifted_leg_height": round(leg_height_ratio, 2),
                "lifted_knee_angle": round(lifted_knee_angle, 1),
                "standing_knee_angle": round(standing_knee_angle, 1),
                "standing_hip_angle": round(standing_hip_angle, 1),
                "standing_side_lean_angle": round(standing_side_lean_angle, 1),
                "front_arm_reach": (
                    round(front_arm_reach, 2) if front_arm_reach is not None else None
                ),
                "hand_foot_gap": (
                    round(hand_foot_gap, 2) if hand_foot_gap is not None else None
                ),
                "front_arm_reach_ok": front_arm_reach_ok,
                "hand_foot_connected": hand_foot_connected,
                "balance_confidence": balance_confidence,
                "hold_state": "holding" if holding_now else "broken",
                "is_holding": holding_now,
                "target_reached": target_reached,
                "hold_quality": hold_quality,
                "posture_ok": len(issues) == 0,
                "posture_issues": issues,
                "posture_messages": messages,
                "framing_ok": framing_message is None,
                "framing_message": framing_message,
                "form_score": form_score,
                "avg_form_score": self._avg(self.form_scores),
                "feedback": feedback,
            }
        )
        response.update(self._progress_fields())
        return response

    # ---------------------------------------------------------------
    def _register_broken_frame(self):
        if self.hold_active:
            self.break_count += 1
        self.hold_active = False
        self.current_streak_seconds = 0.0

    def _progress_fields(self) -> dict[str, Any]:
        return {
            "hold_seconds": round(self.hold_seconds, 2),
            "good_seconds": round(self.good_seconds, 2),
            "flawed_seconds": round(self.flawed_seconds, 2),
            "current_streak_seconds": round(self.current_streak_seconds, 2),
            "best_streak_seconds": round(self.best_streak_seconds, 2),
            "break_count": self.break_count,
            "session_complete": self._is_complete(),
        }

    @staticmethod
    def _avg(values: "deque[int]") -> Optional[int]:
        if not values:
            return None
        return round(sum(values) / len(values))


class DancerPoseSession:
    """Full Dancer Pose session: one shared pose model + one analyzer.

    `target_seconds` / `target_sets` / `set_number` / `support_mode` are
    the coach-assigned plan for this user, supplied by the caller (the
    websocket route, from query params) — same convention as the other
    hold sessions.
    """

    def __init__(
        self,
        target_seconds: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
        support_mode: str = "free",
    ):
        self.engine = PoseEngine()
        self.analyzer = DancerPoseAnalyzer(target_seconds, support_mode=support_mode)
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
