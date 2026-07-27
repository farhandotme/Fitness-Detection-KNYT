"""
Half Moon Pose (Ardha Chandrasana) hold timing + posture correction.

Design
------
Same family as `PlankHoldAnalyzer` / `SidePlankAnalyzer` / `WallSitAnalyzer`
— Half Moon has no reps, it's a single continuous balance hold, so this
does **not** run a rep state machine. It runs the identical **hold timer
that only advances while the person is verified, frame by frame, to
actually be in a valid Half Moon shape**:

    * The instant the pose breaks (both feet down, the lifted leg drops,
      the torso folds all the way down, or the camera loses the person)
      the timer **pauses**. It never silently resets to zero, so
      accumulated `hold_seconds` is monotonic for the lifetime of a set.
      `current_streak_seconds` (time since the last break) is what
      resets, giving live feedback on the *current* attempt without
      punishing total progress.
    * The instant a valid shape returns, the timer picks back up from
      exactly where it left off.

Balance wobble is expected and is explicitly NOT treated the same as a
hard break: small shifts show up as `balance_confidence` dipping (a
rolling measure of how consistently the last couple of seconds held
pose), not as the timer stopping — only a genuine loss of the shape
(foot down, leg dropped, torso collapsed, framing gone) pauses it.

Which leg is standing vs. lifted
---------------------------------
Unlike the other hold exercises, Half Moon is asymmetric — the two legs
have different jobs — so the very first thing each frame does is work
out `standing_side`: whichever ankle sits clearly lower in the frame
(closer to the floor) is standing; the other is lifted. Once a side is
established, it's kept "sticky" across frames (like `active_side` in the
side plank) so a single noisy frame doesn't spin the pose around.

Form signal
-----------
Core gating (hard-break) signals, evaluated using the standing leg's own
proportions as the reference scale (so it doesn't matter how close/far
the person is from the camera):

  * `leg_height_ratio` = how far above the standing foot the lifted ankle
    sits, normalized by standing-leg length. Near 0 = both feet basically
    level (not lifted at all); this is the main "is a leg actually up"
    gate.
  * `lifted_knee_angle` = angle(hip, knee, ankle) on the lifted leg.
    Needs to read as reasonably straight — a tightly bent/tucked knee
    looks like tree pose, not an extended Half Moon leg.
  * `standing_knee_angle` = angle(hip, knee, ankle) on the standing leg.
    A slight bend is fine (explicitly allowed for balance), but it can't
    collapse into a deep bend or this becomes a lunge/squat.
  * `standing_hip_angle` = angle(shoulder, hip, knee) on the standing
    side. Guards against a full forward fold — Half Moon opens the torso
    sideways, it doesn't hinge the torso all the way down over the leg.

Softer, secondary signals (grade quality, never pause the timer):

  * `rotation_signal` = |shoulder_L.z - shoulder_R.z| (relative depth
    between the shoulders). Near 0 means the chest is still square to the
    camera; a real Half Moon rotates the chest open, which shows up as
    the shoulders separating in depth. Low value → "hips_not_open".
  * `standing_side_lean_angle` = tilt of the standing-side shoulder->hip
    line from vertical. Some lean is normal (the torso reaches out over
    the standing leg), but a lot of it reads as leaning on the standing
    side rather than lengthening open.
  * `top_arm_reach` = how far the top wrist (assumed to be on the same
    side as the lifted leg, per the classic shape) sits above its
    shoulder, normalized by torso length.

Support modifier
----------------
There's no object-detection model in this codebase to see a literal wall
or block — `PoseEngine` only returns body landmarks — so support is
handled the same way `target_seconds` is: the frontend tells the backend
what's being used (`support_mode` = "free" | "wall" | "block", a session
query param, same convention as the target/set params), and the analyzer
uses it purely as a **threshold modifier**: a wall relaxes the lean
check (leaning briefly into a wall is expected), a block relaxes the
lift-height check slightly (the "floor" is effectively raised). This
matches "use it as a support modifier, not a disqualifier" without
pretending to detect an object that isn't there.
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

MIN_LANDMARK_VISIBILITY = 0.4

LEG_LANDMARKS = {
    "left": (LEFT_SHOULDER, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE),
    "right": (RIGHT_SHOULDER, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE),
}
WRIST_LANDMARKS = {"left": LEFT_WRIST, "right": RIGHT_WRIST}
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)

SUPPORT_MODES = ("free", "wall", "block")

# ---- which leg is standing vs lifted ----
# Ankle-height difference (normalized to frame height) needed before one
# side is confidently called "standing" and the other "lifted". Below
# this, both feet read as roughly level (i.e. not a Half Moon stance yet).
STANCE_MARGIN = 0.10

# ---- lifted-leg height (normalized by standing leg length) ----
LIFT_BREAK = 0.28
LIFT_RESUME = 0.36
LIFT_IDEAL = 0.55

# ---- lifted knee angle (hip-knee-ankle), degrees — must read "extended" ----
EXTENSION_BREAK = 118.0
EXTENSION_RESUME = 130.0

# ---- standing knee angle (hip-knee-ankle), degrees ----
# A slight bend is explicitly allowed for balance — only a deep bend
# (turning this into a lunge/squat) is a hard break.
STANDING_KNEE_BREAK = 120.0
STANDING_KNEE_RESUME = 132.0
STANDING_KNEE_LOCKED_ABOVE = 174.0  # soft note: almost hyperextended

# ---- standing-side hip angle (shoulder-hip-knee), degrees ----
# Guards against a full forward fold — the torso opens sideways in Half
# Moon, it doesn't hinge all the way down over the standing leg.
FOLD_BREAK = 55.0
FOLD_RESUME = 68.0

# ---- torso rotation ("chest openness"), relative shoulder depth ----
ROTATION_IDEAL = 0.09

# ---- standing-side lean angle (shoulder->hip vs vertical), degrees ----
LEAN_SOFT_MAX = 40.0

# ---- top-arm reach, (shoulder.y - wrist.y) / torso length ----
REACH_IDEAL = 0.35

# Per-issue form_score penalty (applied per frame while holding).
MISTAKE_PENALTY = {
    "standing_knee_locked": 8,
    "lifted_leg_low": 14,
    "hips_not_open": 16,
    "top_arm_not_reaching": 10,
    "leaning_into_standing_side": 12,
}

SCORE_HISTORY = 30
SCORE_SAMPLE_INTERVAL = 1.0  # seconds

# Rolling "is this frame currently holding" window used for
# `balance_confidence` — reflects wobble over roughly the last 1.5s,
# independent of (and faster-updating than) `avg_form_score`.
BALANCE_WINDOW = 45

# -------------------------------------------------------------------------
# Camera framing thresholds (front / slight front-side oblique view — the
# whole spread-out shape needs to be in frame, not just a tight upright
# crop like the wall sit).
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
    return visible_core >= 2  # an oblique/side-leaning view may not show all 4 cleanly


def _leg_visibility(landmarks, side: str) -> float:
    scores = []
    for idx in LEG_LANDMARKS[side]:
        v = landmarks[idx].visibility
        scores.append(v if v is not None else 0.0)
    return min(scores) if scores else 0.0


# Threshold used specifically to decide standing-vs-lifted role. Deciding
# a role only needs the hip and ankle (see `_stance_visibility` below) —
# requiring the full leg tuple (which also includes the knee and
# shoulder) here was too strict: an actively-extended lifted leg is
# routinely scored lower confidence by the pose model than a normally
# planted one even when it's clearly visible on camera, which was
# rejecting genuinely correct Half Moon attempts as "can't see your legs."
STANCE_VISIBILITY_MIN = 0.3


def _stance_visibility(landmarks, side: str) -> float:
    """Lowest visibility between just the hip and ankle on `side` — the
    only two landmarks `_pick_standing_side` actually reads. Deliberately
    lighter than `_leg_visibility` (which also checks the knee and
    shoulder) so a well-tracked-but-lower-confidence extended leg still
    gets picked up."""
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
    """Coaches the user into a good spot for the camera to judge a Half
    Moon from — checked every frame, independent of exercise form.

    Half Moon's silhouette is wide and spread out (lifted leg extended
    to one side, top arm reaching up), so this only checks edge-clipping
    and overall distance — it does NOT require an upright body shape
    the way the wall sit's framing check does.
    """
    for p in all_points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — step back so your whole "
                "shape, extended leg and reaching arm included, fits in "
                "the shot."
            )

    xs = [p.x for p in all_points]
    ys = [p.y for p in all_points]
    span = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    if span > BODY_SPAN_TOO_CLOSE:
        return "You're too close to the camera — step back until your whole body fits in frame."
    if span < BODY_SPAN_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class HalfMoonAnalyzer:
    """Stateful Half Moon hold timer + posture checker.

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

        self._was_complete = False  # for edge-triggering `target_reached`

        self.form_scores: deque[int] = deque(maxlen=SCORE_HISTORY)
        self._last_score_sample_time: Optional[float] = None

        # Rolling holding/not-holding window for balance_confidence.
        self._balance_window: deque[bool] = deque(maxlen=BALANCE_WINDOW)

    # ---------------------------------------------------------------
    def _is_complete(self) -> bool:
        return (
            self.target_seconds is not None and self.hold_seconds >= self.target_seconds
        )

    def _pick_standing_side(self, landmarks) -> Optional[str]:
        """Decide standing vs lifted leg from relative ankle height, with
        stickiness so a single noisy frame can't flip which leg is which
        mid-hold.

        `diff` is left-ankle-y minus right-ankle-y: positive means the
        left ankle sits lower in the frame (closer to the floor, i.e.
        left is standing); negative means right is standing.
        """
        vis = {side: _leg_visibility(landmarks, side) for side in ("left", "right")}
        if (
            vis["left"] < MIN_LANDMARK_VISIBILITY
            or vis["right"] < MIN_LANDMARK_VISIBILITY
        ):
            return None

        l_ankle = landmarks[LEFT_ANKLE]
        r_ankle = landmarks[RIGHT_ANKLE]
        diff = l_ankle.y - r_ankle.y

        if self.standing_side == "left":
            # Only hand off to "right" if right has become clearly (not
            # marginally) the more-grounded foot.
            return "right" if diff < -STANCE_MARGIN else "left"
        if self.standing_side == "right":
            return "left" if diff > STANCE_MARGIN else "right"

        # No prior assignment yet — require a clear, unambiguous margin
        # before committing to a side at all.
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
            "rotation_signal": None,
            "standing_side_lean_angle": None,
            "top_arm_reach": None,
            "hip_opening_ok": True,
            "top_arm_reach_ok": True,
            "balance_confidence": None,
            "support_mode": self.support_mode,
            "wall_supported": self.support_mode == "wall",
            "block_supported": self.support_mode == "block",
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
            dt = max(0.0, min(t - self.last_timestamp_s, 0.5))  # clamp huge gaps
        self.last_timestamp_s = t

        if landmarks is None or not _looks_like_a_person(landmarks):
            self._register_broken_frame()
            response["feedback"] = (
                "No person detected — step into frame, facing the camera, "
                "with room to extend a leg out to the side."
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

        lifted_shoulder = landmarks[l_sh_i]
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

        rotation_signal = abs(
            (
                landmarks[LEFT_SHOULDER].z
                if landmarks[LEFT_SHOULDER].z is not None
                else 0.0
            )
            - (
                landmarks[RIGHT_SHOULDER].z
                if landmarks[RIGHT_SHOULDER].z is not None
                else 0.0
            )
        )
        standing_side_lean_angle = _vertical_deviation_deg(
            standing_shoulder, standing_hip
        )

        torso_len = max(_dist(standing_shoulder, standing_hip), 1e-6)
        top_wrist = landmarks[WRIST_LANDMARKS[lifted_side]]
        top_arm_visible = (
            top_wrist.visibility is not None
            and top_wrist.visibility >= MIN_LANDMARK_VISIBILITY
        )
        top_arm_reach = (
            (lifted_shoulder.y - top_wrist.y) / torso_len if top_arm_visible else None
        )

        # ---- support-mode threshold modifiers ----
        # A wall makes some lean into it expected; a block effectively
        # raises the floor a little, so the lift-height bar can be a touch
        # lower without it being a worse pose. Neither relaxes the core
        # "is this actually Half Moon" gates (extension, standing knee,
        # fold) — support only changes how forgiving the softer checks are.
        lean_soft_max = LEAN_SOFT_MAX * (1.4 if self.support_mode == "wall" else 1.0)
        lift_break = LIFT_BREAK * (0.85 if self.support_mode == "block" else 1.0)
        lift_resume = LIFT_RESUME * (0.85 if self.support_mode == "block" else 1.0)
        lift_ideal = LIFT_IDEAL * (0.9 if self.support_mode == "block" else 1.0)

        # ---- resolve hold-validity this frame (with hysteresis) ----
        if self.hold_active:
            leg_too_low = leg_height_ratio < lift_break
            knee_not_extended = lifted_knee_angle < EXTENSION_BREAK
            standing_too_bent = standing_knee_angle < STANDING_KNEE_BREAK
            torso_folded = standing_hip_angle < FOLD_BREAK
        else:
            leg_too_low = leg_height_ratio < lift_resume
            knee_not_extended = lifted_knee_angle < EXTENSION_RESUME
            standing_too_bent = standing_knee_angle < STANDING_KNEE_RESUME
            torso_folded = standing_hip_angle < FOLD_RESUME

        hard_break = (
            leg_too_low or knee_not_extended or standing_too_bent or torso_folded
        )
        holding_now = framing_message is None and not hard_break

        # ---- form tiering (only meaningful while holding) ----
        issues: list[str] = []
        messages: list[str] = []
        hip_opening_ok = True
        top_arm_reach_ok = True

        if holding_now:
            if standing_knee_angle > STANDING_KNEE_LOCKED_ABOVE:
                issues.append("standing_knee_locked")
                messages.append("Soften the standing knee slightly for balance.")

            if leg_height_ratio < lift_ideal:
                issues.append("lifted_leg_low")
                messages.append("Lift the back leg a little higher.")

            if rotation_signal < ROTATION_IDEAL:
                hip_opening_ok = False
                issues.append("hips_not_open")
                messages.append("Open the hips more — keep the chest turning open.")

            if top_arm_visible:
                if top_arm_reach is not None and top_arm_reach < REACH_IDEAL:
                    top_arm_reach_ok = False
                    issues.append("top_arm_not_reaching")
                    messages.append("Reach the top arm up.")
            else:
                top_arm_reach_ok = False

            if standing_side_lean_angle > lean_soft_max:
                issues.append("leaning_into_standing_side")
                messages.append(
                    "Lengthen up and out through both sides, rather than "
                    "leaning into your standing leg."
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
            feedback = "Lift the other leg out and up — extend it away from your body."
        if feedback is None and knee_not_extended:
            feedback = (
                "Straighten the lifted leg — extend it out rather than tucking it."
            )
        if feedback is None and standing_too_bent:
            feedback = (
                "Press into the standing leg and straighten it a bit more for balance."
            )
        if feedback is None and torso_folded:
            feedback = (
                "Open your chest upward instead of folding down over your standing leg."
            )
        if feedback is None and messages:
            feedback = messages[0]
        if feedback is None and not self.started and holding_now:
            feedback = "Nice — you're balanced in Half Moon, stay steady!"
        if feedback is None and target_reached:
            feedback = (
                f"Target reached — {self.target_seconds}s held, beautiful balance!"
            )
        if feedback is None and holding_now:
            feedback = "Press into the standing leg — reach the top arm up!"
        if feedback is None and self.hold_active is False and self.started:
            # A wobble that hasn't fully broken form yet — reassurance,
            # not a hard error, per the beginner-friendly requirement.
            feedback = "A little wobble is fine — find your gaze point and reset."
        if feedback is None:
            feedback = (
                "Stand on one leg, lift the other out, and open your chest to begin."
            )

        response.update(
            {
                "pose_detected": True,
                "standing_side": self.standing_side,
                "leg_height_ratio": round(leg_height_ratio, 2),
                "lifted_leg_height": round(leg_height_ratio, 2),
                "lifted_knee_angle": round(lifted_knee_angle, 1),
                "standing_knee_angle": round(standing_knee_angle, 1),
                "standing_hip_angle": round(standing_hip_angle, 1),
                "rotation_signal": round(rotation_signal, 3),
                "standing_side_lean_angle": round(standing_side_lean_angle, 1),
                "top_arm_reach": (
                    round(top_arm_reach, 2) if top_arm_reach is not None else None
                ),
                "hip_opening_ok": hip_opening_ok,
                "top_arm_reach_ok": top_arm_reach_ok,
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


class HalfMoonSession:
    """Full Half Moon session: one shared pose model + one analyzer.

    `target_seconds` / `target_sets` / `set_number` / `support_mode` are
    the coach-assigned plan for this user, supplied by the caller (the
    websocket route, from query params) — same convention as the other
    hold sessions. The frontend does not decide on its own whether a
    set/exercise is done; `session_complete` and `exercise_complete` are
    both computed here.
    """

    def __init__(
        self,
        target_seconds: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
        support_mode: str = "free",
    ):
        self.engine = PoseEngine()
        self.analyzer = HalfMoonAnalyzer(target_seconds, support_mode=support_mode)
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
