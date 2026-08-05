"""
Tree Pose hold timing + posture correction.

Design
------
Like `PlankHoldAnalyzer` / `SidePlankAnalyzer`, tree pose has no reps —
it's a timed balance hold, so this runs the same **hold timer that only
advances while the person is verified, frame by frame, to actually be in
a correct tree pose**. Unlike the other two holds, tree pose is done on
*each leg*, so this tracks `left_seconds` / `right_seconds` completely
independently, and the exercise isn't "complete" until both legs have
individually reached `target_seconds`.

The single most important property of this module (explicitly requested):
**a frame where the person is genuinely in correct form must count.** A
false "you're not holding it" on a technically-correct frame is treated as
a worse failure mode than being a little lenient. Two things do the work:

    * Hysteresis bands on every gate — the threshold to *keep* a hold
      going is looser than the threshold needed to *start* one, so a
      borderline angle doesn't flicker holding/broken every other frame.
    * A short **grace period** (`GRACE_SECONDS`) — once a hold is
      running, a single bad/noisy frame (a MediaPipe jitter, a missed
      landmark) does not immediately pause the timer. Only bad form that
      *persists* past the grace window actually pauses it.

As with plank/side-plank, the timer only ever **pauses** on a break —
`hold_seconds` (per leg) is monotonic for the life of a set. It never
silently resets to zero.

Camera framing
---------------
Tree pose is judged from a **front-facing, full-body, standing view** —
the opposite orientation from plank/side-plank. The framing check here
expects a body that reads as mostly vertical (shoulders above hips above
ankles), not horizontal.

Form signal
-----------
All computed from the standard 33-point body model (no hand/finger
landmarks needed — this never tries to judge the exact hand position,
only the standing leg and torso, which is what actually determines
balance and safety):

  * **Standing-leg straightness** — `angle(hip, knee, ankle)` on
    whichever leg is on the ground. A bent standing knee means the pose
    has collapsed into a squat, not a balanced tree.
  * **Lifted-foot height** — the raised ankle must sit above the
    standing knee's height (in image-y terms), normalized by hip width.
    This is what actually distinguishes "foot resting against the
    thigh/calf" from "foot barely off the floor".
  * **Lifted-foot placement** — the raised ankle's horizontal offset from
    the standing leg's line must stay small, i.e. the foot is tucked in
    against the standing leg, not sticking out to the side or forward.
  * **Torso uprightness** — the angle of the shoulder-midpoint ->
    hip-midpoint line from true vertical. Leaning to compensate for
    balance is exactly the failure mode this catches.

Hip levelness (whether both hips stay square) is graded as a **soft
form note only** — it never pauses the timer — since a small amount of
hip drop/hike is a normal, safe part of balancing on one leg.
"""

import math
from collections import deque
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
LEG_LANDMARKS = (LEFT_HIP, LEFT_KNEE, LEFT_ANKLE, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE)

# ---- which leg is lifted, normalized ankle-height difference / hip width ----
# Hysteresis: looser (BROKEN) threshold keeps an already-running hold alive
# through minor tracking noise; the tighter (RESUME) threshold is required
# to newly establish which leg is standing.
LIFT_DETECT_BROKEN = 0.28
LIFT_DETECT_RESUME = 0.45

# ---- standing-leg straightness, angle(hip, knee, ankle) in degrees ----
STANDING_KNEE_ANGLE_BROKEN = 155.0
STANDING_KNEE_ANGLE_RESUME = 163.0
STANDING_KNEE_ANGLE_IDEAL = 172.0  # scoring only, no gate at this level

# ---- lifted-foot height above standing knee, / hip width ----
FOOT_HEIGHT_GAP_BROKEN = 0.12
FOOT_HEIGHT_GAP_RESUME = 0.28

# ---- lifted-foot horizontal offset from standing leg line, / hip width ----
FOOT_PLACEMENT_BROKEN = 1.3
FOOT_PLACEMENT_RESUME = 1.0

# ---- torso tilt from vertical, degrees ----
TORSO_TILT_BROKEN = 24.0
TORSO_TILT_RESUME = 17.0
TORSO_TILT_IDEAL = 8.0  # scoring only

# ---- hip levelness, soft note only, / hip width ----
HIP_LEVEL_SOFT = 0.10

# Once a hold is running, bad form has to persist longer than this before
# the timer actually pauses — absorbs single-frame tracking jitter so a
# genuinely-correct pose never gets falsely marked as "not holding".
GRACE_SECONDS = 0.4

MISTAKE_PENALTY = {
    "standing_knee_bent": 30,
    "foot_too_low": 25,
    "foot_not_tucked": 20,
    "torso_lean": 25,
    "hips_uneven": 10,
}

SCORE_HISTORY = 30
SCORE_SAMPLE_INTERVAL = 1.0  # seconds

# -------------------------------------------------------------------------
# Camera framing (front-facing, standing view — body should read as
# mostly vertical, not horizontal).
# -------------------------------------------------------------------------
FRAME_EDGE_MARGIN = 0.02
BODY_SPAN_TOO_CLOSE = 0.95  # shoulder-to-ankle span as a fraction of frame height
BODY_SPAN_TOO_FAR = 0.30
MAX_LYING_RATIO = 0.75  # |dx|/|dy| of shoulder->ankle above this = too horizontal


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 3


def _visible(points) -> bool:
    for p in points:
        if p is None:
            return False
        v = getattr(p, "visibility", None)
        if v is not None and v < MIN_LANDMARK_VISIBILITY:
            return False
    return True


def _legs_visible(landmarks) -> bool:
    return _visible([landmarks[i] for i in LEG_LANDMARKS])


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


def _midpoint(a, b):
    class _P:
        __slots__ = ("x", "y")

    p = _P()
    p.x = (a.x + b.x) / 2
    p.y = (a.y + b.y) / 2
    return p


def _framing_feedback(shoulder_mid, hip_mid, ankle_mid) -> Optional[str]:
    """Coaches the user into a spot the camera can judge tree pose from —
    checked every frame, independent of exercise form.

    Checks, in order of how badly they break tracking:
      1. Part of the body clipped at a frame edge.
      2. Lying/leaning too horizontal instead of standing upright — most
         likely the camera isn't front-on, or the person isn't standing.
      3. Too close / too far from the camera.
    """
    for p in (shoulder_mid, hip_mid, ankle_mid):
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — step back so your whole body, "
                "head to feet, fits in the shot."
            )

    dx = abs(ankle_mid.x - shoulder_mid.x)
    dy = abs(ankle_mid.y - shoulder_mid.y)
    if dy < 1e-6 or (dx / dy) > MAX_LYING_RATIO:
        return (
            "Stand facing the camera, upright, with your whole body in "
            "frame — I need a front-on standing view to check your balance."
        )

    body_span = math.hypot(dx, dy)
    if body_span > BODY_SPAN_TOO_CLOSE:
        return "You're too close to the camera — step back until your whole body fits in frame."
    if body_span < BODY_SPAN_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class TreePoseAnalyzer:
    """Stateful tree-pose-hold timer + posture checker.

    Tracks `left_seconds` (time spent balanced on the left leg) and
    `right_seconds` (right leg) completely independently. `target_seconds`
    is the per-leg target — `session_complete` is only True once **both**
    legs have individually reached it, mirroring real tree-pose practice
    (alternate sides).
    """

    def __init__(self, target_seconds: Optional[int] = None):
        self.target_seconds = target_seconds

        # `active_leg` = which leg is currently the STANDING (support) leg.
        self.active_leg: Optional[str] = None

        self.hold_active = False  # is the timer running THIS frame
        self.started = False  # has the timer ever run at all

        self.left_seconds = 0.0
        self.right_seconds = 0.0
        self.good_seconds = 0.0
        self.flawed_seconds = 0.0
        self.current_streak_seconds = 0.0
        self.best_streak_seconds = 0.0
        self.break_count = 0

        self._bad_streak_seconds = 0.0  # grace-period accumulator

        self.last_timestamp_s: Optional[float] = None
        self.session_start_time: Optional[float] = None

        self._left_was_complete = False
        self._right_was_complete = False

        self.form_scores: deque[int] = deque(maxlen=SCORE_HISTORY)
        self._last_score_sample_time: Optional[float] = None

    # ---------------------------------------------------------------
    @property
    def hold_seconds(self) -> float:
        """Combined hold time across both legs — kept for parity with the
        other hold-based detectors' response shape."""
        return self.left_seconds + self.right_seconds

    def _left_complete(self) -> bool:
        return self.target_seconds is not None and self.left_seconds >= self.target_seconds

    def _right_complete(self) -> bool:
        return self.target_seconds is not None and self.right_seconds >= self.target_seconds

    def _is_complete(self) -> bool:
        if self.target_seconds is None:
            return False
        return self._left_complete() and self._right_complete()

    def _pick_standing_leg(self, landmarks) -> Optional[str]:
        la, ra = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]
        lh, rh = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        hip_width = max(_dist(lh, rh), 1e-6)

        # Image y grows DOWNWARD (0 = top, 1 = bottom), so a grounded ankle
        # has a LARGER y than a lifted one.
        #   normalized very negative => right ankle's y is much smaller
        #     than left ankle's y => right ankle is the one lifted => the
        #     LEFT leg is standing (grounded).
        #   normalized very positive => the opposite => RIGHT leg is
        #     standing.
        normalized = (ra.y - la.y) / hip_width

        threshold = LIFT_DETECT_BROKEN if self.active_leg is not None else LIFT_DETECT_RESUME
        if normalized <= -threshold:
            return "left"
        if normalized >= threshold:
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
            "active_leg": self.active_leg,
            "standing_knee_angle": None,
            "foot_height_gap": None,
            "foot_placement_offset": None,
            "torso_tilt_angle": None,
            "hip_level_diff": None,
            "hold_state": (
                "holding"
                if self.started and self.hold_active
                else ("broken" if self.started else "not_started")
            ),
            "is_holding": False,
            "hold_seconds": round(self.hold_seconds, 2),
            "left_seconds": round(self.left_seconds, 2),
            "right_seconds": round(self.right_seconds, 2),
            "good_seconds": round(self.good_seconds, 2),
            "flawed_seconds": round(self.flawed_seconds, 2),
            "current_streak_seconds": round(self.current_streak_seconds, 2),
            "best_streak_seconds": round(self.best_streak_seconds, 2),
            "break_count": self.break_count,
            "target_seconds": self.target_seconds,
            "left_complete": self._left_complete(),
            "right_complete": self._right_complete(),
            "session_complete": self._is_complete(),
            "leg_target_reached": None,
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
                "No person detected — stand facing the camera with your whole body in frame."
            )
            response.update(self._progress_fields())
            return response

        if not _legs_visible(landmarks):
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._register_broken_frame()
            response["feedback"] = (
                "Can't see your legs clearly — step back and make sure your "
                "hips, knees and ankles are all in frame."
            )
            response.update(self._progress_fields())
            return response

        left_shoulder, right_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        left_hip, right_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        left_ankle, right_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        shoulder_mid = _midpoint(left_shoulder, right_shoulder)
        hip_mid = _midpoint(left_hip, right_hip)
        ankle_mid = _midpoint(left_ankle, right_ankle)

        framing_message = _framing_feedback(shoulder_mid, hip_mid, ankle_mid)

        standing_leg = self._pick_standing_leg(landmarks)

        hip_width = max(_dist(left_hip, right_hip), 1e-6)
        torso_tilt = math.degrees(
            math.atan2(abs(shoulder_mid.x - hip_mid.x), max(abs(shoulder_mid.y - hip_mid.y), 1e-6))
        )
        hip_level_diff = abs(left_hip.y - right_hip.y) / hip_width

        standing_knee_angle = None
        foot_height_gap = None
        foot_placement_offset = None
        gates_ok = False

        if standing_leg is not None:
            if standing_leg == "left":
                s_hip, s_knee, s_ankle = left_hip, landmarks[LEFT_KNEE], left_ankle
                lifted_ankle = right_ankle
            else:
                s_hip, s_knee, s_ankle = right_hip, landmarks[RIGHT_KNEE], right_ankle
                lifted_ankle = left_ankle

            standing_knee_angle = _angle_deg(s_hip, s_knee, s_ankle)
            foot_height_gap = (s_knee.y - lifted_ankle.y) / hip_width
            foot_placement_offset = abs(lifted_ankle.x - s_knee.x) / hip_width

            if self.hold_active:
                knee_bad = standing_knee_angle < STANDING_KNEE_ANGLE_BROKEN
                height_bad = foot_height_gap < FOOT_HEIGHT_GAP_BROKEN
                placement_bad = foot_placement_offset > FOOT_PLACEMENT_BROKEN
                tilt_bad = torso_tilt > TORSO_TILT_BROKEN
            else:
                knee_bad = standing_knee_angle < STANDING_KNEE_ANGLE_RESUME
                height_bad = foot_height_gap < FOOT_HEIGHT_GAP_RESUME
                placement_bad = foot_placement_offset > FOOT_PLACEMENT_RESUME
                tilt_bad = torso_tilt > TORSO_TILT_RESUME

            gates_ok = not (knee_bad or height_bad or placement_bad or tilt_bad)
        else:
            knee_bad = height_bad = placement_bad = tilt_bad = False

        holding_now_raw = framing_message is None and standing_leg is not None and gates_ok

        # ---- grace period: absorb transient bad frames while already holding ----
        if holding_now_raw:
            self._bad_streak_seconds = 0.0
            holding_now = True
        elif self.hold_active:
            self._bad_streak_seconds += dt
            holding_now = self._bad_streak_seconds < GRACE_SECONDS
        else:
            holding_now = False

        # ---- leg switch handling: a genuine change of standing leg always ----
        # starts a fresh streak, even if it happens without an intervening
        # "broken" frame.
        if standing_leg is not None and standing_leg != self.active_leg:
            self.current_streak_seconds = 0.0
            self.active_leg = standing_leg

        # ---- form tiering (only meaningful while holding) ----
        issues: list[str] = []
        messages: list[str] = []
        if holding_now and standing_leg is not None:
            if knee_bad or (standing_knee_angle is not None and standing_knee_angle < STANDING_KNEE_ANGLE_IDEAL):
                issues.append("standing_knee_bent")
                messages.append("Straighten your standing leg — keep that knee from bending.")
            if height_bad:
                issues.append("foot_too_low")
                messages.append("Lift your foot higher — press it against your calf or thigh, above knee height.")
            if placement_bad:
                issues.append("foot_not_tucked")
                messages.append("Tuck your foot in against your standing leg instead of letting it drift out.")
            if tilt_bad or torso_tilt > TORSO_TILT_IDEAL:
                issues.append("torso_lean")
                messages.append("Stand tall — you're leaning, engage your core to stay upright.")
            if hip_level_diff > HIP_LEVEL_SOFT:
                issues.append("hips_uneven")
                messages.append("Keep your hips level and square to the camera.")

        # ---- advance / pause the timer ----
        form_score = None
        hold_quality = None
        leg_target_reached = None
        if holding_now:
            if not self.hold_active:
                self.current_streak_seconds = 0.0
            self.hold_active = True
            self.started = True

            if self.active_leg == "left":
                self.left_seconds += dt
            elif self.active_leg == "right":
                self.right_seconds += dt

            self.current_streak_seconds += dt
            if self.current_streak_seconds > self.best_streak_seconds:
                self.best_streak_seconds = self.current_streak_seconds

            # Only the four hard-gate issues count against "good vs flawed"
            # hold time; hips_uneven is a soft note and doesn't demote it.
            hard_issues = [i for i in issues if i != "hips_uneven"]
            if hard_issues:
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

        left_complete_now = self._left_complete()
        right_complete_now = self._right_complete()
        if left_complete_now and not self._left_was_complete:
            leg_target_reached = "left"
        elif right_complete_now and not self._right_was_complete:
            leg_target_reached = "right"
        self._left_was_complete = left_complete_now
        self._right_was_complete = right_complete_now

        is_complete = self._is_complete()

        # ---- feedback priority: framing > no-lift > hard break > form flaws > praise ----
        feedback = framing_message
        if feedback is None and standing_leg is None:
            feedback = "Lift one foot and press it against your standing leg to start the hold."
        if feedback is None and not holding_now and standing_leg is not None:
            feedback = (
                "That's not quite tree pose yet — straighten your standing leg, "
                "lift your other foot above knee height, and stand tall."
            )
        if feedback is None and messages:
            feedback = messages[0]
        if feedback is None and leg_target_reached:
            feedback = f"{leg_target_reached.capitalize()} leg target reached — {self.target_seconds}s held, nice balance!"
        if feedback is None and is_complete:
            feedback = "Both legs complete — great tree pose session!"
        if feedback is None and holding_now:
            feedback = "Great tree pose — keep holding!"
        if feedback is None:
            feedback = "Get back into tree pose to resume the timer."

        response.update(
            {
                "pose_detected": True,
                "active_leg": self.active_leg,
                "standing_knee_angle": round(standing_knee_angle, 1) if standing_knee_angle is not None else None,
                "foot_height_gap": round(foot_height_gap, 3) if foot_height_gap is not None else None,
                "foot_placement_offset": round(foot_placement_offset, 3) if foot_placement_offset is not None else None,
                "torso_tilt_angle": round(torso_tilt, 1),
                "hip_level_diff": round(hip_level_diff, 3),
                "hold_state": "holding" if holding_now else "broken",
                "is_holding": holding_now,
                "leg_target_reached": leg_target_reached,
                "hold_quality": hold_quality,
                "posture_ok": len([i for i in issues if i != "hips_uneven"]) == 0,
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
        self._bad_streak_seconds = 0.0

    def _progress_fields(self) -> dict[str, Any]:
        return {
            "hold_seconds": round(self.hold_seconds, 2),
            "left_seconds": round(self.left_seconds, 2),
            "right_seconds": round(self.right_seconds, 2),
            "good_seconds": round(self.good_seconds, 2),
            "flawed_seconds": round(self.flawed_seconds, 2),
            "current_streak_seconds": round(self.current_streak_seconds, 2),
            "best_streak_seconds": round(self.best_streak_seconds, 2),
            "break_count": self.break_count,
            "left_complete": self._left_complete(),
            "right_complete": self._right_complete(),
            "session_complete": self._is_complete(),
        }

    @staticmethod
    def _avg(values: "deque[int]") -> Optional[int]:
        if not values:
            return None
        return round(sum(values) / len(values))


class TreePoseSession:
    """Full tree-pose session: one shared pose model + one analyzer.

    `target_seconds` is the coach-assigned **per-leg** hold target;
    `target_sets` / `set_number` follow the same convention as
    `PlankHoldSession` / `SidePlankSession` — the frontend does not decide
    on its own whether a set/exercise is done; `session_complete` and
    `exercise_complete` are both computed here.
    """

    def __init__(
        self,
        target_seconds: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = TreePoseAnalyzer(target_seconds)
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
