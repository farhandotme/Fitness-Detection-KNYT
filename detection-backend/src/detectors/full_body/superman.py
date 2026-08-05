"""
Superman hold timer + posture correction.

THE MOVEMENT
------------
Lie face-down (prone) on the floor, arms extended overhead, and lift the
chest, arms and legs off the floor together — hips stay down and act as
the pivot — then hold that position. Unlike a push-up, this has no reps:
it's a single sustained position, held for time. So — same as
`PlankHoldAnalyzer` / `SidePlankAnalyzer` — this file does NOT run a rep
state machine. It runs a **hold timer that only advances while the
person is verified, frame by frame, to actually be in a correct Superman
hold**:

    * The instant the lift drops (or the person leaves frame, isn't
      lying down, or the camera framing goes bad), the timer **pauses**.
      It never silently resets to zero, so accumulated `hold_seconds` is
      monotonic for the lifetime of a set. `current_streak_seconds` (time
      since the last break) is what resets, giving live feedback on the
      *current* attempt without punishing total progress.
    * The instant a valid hold resumes, the timer picks back up from
      where it left off.

WHY THE SAME "HIP-LINE DEVIATION" TRICK FROM hindu_pushup.py APPLIES HERE
--------------------------------------------------------------------------
At rest, the shoulder, hip and ankle sit roughly level with the floor —
i.e. roughly collinear from the side. While holding Superman, the hip
stays anchored near the floor while the shoulder AND the ankle both rise
above it. That is geometrically identical to the Cobra half of a Hindu
push-up (two elevated endpoints, one anchored midpoint sagging "below"
the line joining them) — so the same signed hip-deviation formula,
applied here, is a natural, camera-robust primary signal for "how much
lift is currently being held": near 0 lying flat, strongly positive at
full Superman extension.

WHY IT ISN'T *JUST* THAT FORMULA, THOUGH
-----------------------------------------
The single combined deviation can be satisfied by lifting only the chest
or only the legs — a real, common Superman mistake (and arguably a
different exercise: a prone leg raise, or a cobra-style chest raise).
So chest-rise and leg-rise are also tracked as two independent
quantities (each relative to the hip's height) — a shortfall in either
doesn't break the hold (the person IS still doing something), but it
downgrades that portion of the hold to "needs_improvement" with a
specific, actionable message, exactly like `SidePlankAnalyzer`'s
hip_sag/knee_forward/head_position tiering.

WHY THIS IS SAFE FROM THE "CONTINUOUS NEAR-PEAK CHECK" BUG
-------------------------------------------------------------
An earlier rep-counting version of this file had a real bug: checking
"is the elbow straight" via a loose "near the peak" proximity test
misfired during the natural start of lowering back down, because the
arms/legs begin moving before the combined lift signal does. A hold
timer sidesteps that failure mode entirely — there is no "snapshot the
peak instant" logic here at all. Every quality check below is evaluated
fresh, every single frame, ONLY while genuinely holding (`holding_now`),
using the current frame's own values — so there's nothing to desync.
"""

import math
from collections import deque
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


# ---- lift thresholds (signed hip deviation from the shoulder->leg line,
# identical formula to hindu_pushup.py's hip-arc — near 0 lying flat,
# strongly positive at full Superman extension, since both ends rise
# while the hip stays anchored near the floor). ----
# Hysteresis band: once holding, only a drop below LIFT_BROKEN pauses the
# timer; once broken/not-started, lift has to climb back above
# LIFT_RESUME to start it again — stops a borderline value from
# flickering holding/broken every other frame.
LIFT_BROKEN = 0.10  # below this = not a Superman hold at all — timer pauses
LIFT_RESUME = 0.14  # must climb back above this from broken to resume
LIFT_IDEAL = 0.22  # at/above this, lift depth is "good" tier (no flaw)

# Independent chest-rise / leg-rise thresholds (each relative to hip
# height, normalized by the relevant body segment length) — the hold can
# clear LIFT_IDEAL on the *combined* signal while one side barely moved,
# so these are checked separately for the "both ends up together" form
# that actually defines Superman. Not a hard break — graded as a form
# note only, same tier as knee/head position in `side_plank.py`.
MIN_CHEST_RISE = 0.10
MIN_LEG_RISE = 0.10

# Arm-extension quality check (classic Superman holds the arms straight
# out overhead) — also a form note only, never a hard break.
PEAK_ARM_EXTENSION = 150.0

# Per-issue form_score penalty (applied per frame while holding).
MISTAKE_PENALTY = {
    "shallow_lift": 15,
    "chest_not_lifted": 20,
    "legs_not_lifted": 20,
    "arms_bent": 12,
}

# form_score is sampled into this rolling window roughly once a second
# (not every frame) so `avg_form_score` reflects the last ~SCORE_HISTORY
# seconds of holding rather than being dominated by frame rate.
SCORE_HISTORY = 30
SCORE_SAMPLE_INTERVAL = 1.0  # seconds

# -------------------------------------------------------------------------
# Camera framing / floor-stance thresholds. Folded into a single
# `_framing_feedback` channel (checked fresh every frame, no hysteresis),
# same convention as `side_plank.py` — standing-vs-lying and view-angle
# are both just further reasons the camera can't currently judge the
# exercise, same tier as being clipped at a frame edge.
# -------------------------------------------------------------------------
FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.95
BBOX_TOO_FAR = 0.15

# Superman's whole range of motion is small (a few cm of lift), so unlike
# hindu_pushup.py's Downward-Dog-vs-plank problem, a single wide-bbox gate
# stays valid across the ENTIRE hold — it never needs to tolerate a big
# shape change mid-hold.
FLOOR_BBOX_ASPECT_MIN = 1.3
STANDING_BBOX_ASPECT_MAX = 0.7

# View-mode classification — Superman's lift is a front-to-back-plane
# motion that a head-on camera would flatten to near-zero, same reasoning
# as hindu_pushup.py.
SIDE_VIEW_RATIO_MAX = 0.45
FRONT_VIEW_RATIO_MIN = 0.85


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


def _framing_feedback(
    points: list[_Point],
    bbox_aspect: Optional[float],
    view_mode: str,
) -> Optional[str]:
    """Coaches the user into a spot the camera can actually judge a
    Superman hold from — checked fresh every frame, independent of hold
    quality. Checks, in order of how badly they break tracking:

      1. Part of the body clipped at a frame edge.
      2. Standing too upright instead of lying flat — most likely they
         haven't gotten into position yet.
      3. Facing the camera instead of side-on — the lift is a
         front-to-back motion a head-on view can't read.
      4. Too close / too far from the camera.
    """
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — reposition so your whole body, "
                "head to feet, fits in the shot."
            )

    if bbox_aspect is not None and bbox_aspect <= STANDING_BBOX_ASPECT_MAX:
        return (
            "Lie face-down on the floor, arms extended overhead — I need "
            "you lying flat to start the timer."
        )

    if view_mode == "front":
        return (
            "Turn side-on to the camera — Superman needs a side view to "
            "track the lift accurately."
        )

    if len(points) < 4:
        return None

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


class SupermanAnalyzer:
    """Stateful Superman-hold timer + posture checker.

    No `target_reps` here — the coach-assigned target is a duration,
    `target_seconds`. `session_complete` is `hold_seconds >= target_seconds`,
    exactly mirroring `PlankHoldAnalyzer` / `SidePlankAnalyzer`.
    """

    def __init__(self, target_seconds: Optional[int] = None):
        self.target_seconds = target_seconds

        self.hold_active = False  # is the timer running THIS frame
        self.started = False  # has the timer ever run at all
        self.hold_seconds = 0.0
        self.good_seconds = 0.0
        self.flawed_seconds = 0.0
        self.current_streak_seconds = 0.0
        self.best_streak_seconds = 0.0
        self.break_count = 0

        self.smoothed_lift: Optional[float] = None
        self.lift_smooth_alpha = 0.5

        self.last_timestamp_s: Optional[float] = None
        self.session_start_time: Optional[float] = None

        self._was_complete = False  # for edge-triggering `target_reached`

        self.form_scores: deque[int] = deque(maxlen=SCORE_HISTORY)
        self._last_score_sample_time: Optional[float] = None

    # ---------------------------------------------------------------
    def _is_complete(self) -> bool:
        return (
            self.target_seconds is not None and self.hold_seconds >= self.target_seconds
        )

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "view_mode": None,
            "lift": None,
            "smoothed_lift": None,
            "chest_rise": None,
            "leg_rise": None,
            "left_elbow_angle": None,
            "right_elbow_angle": None,
            "elbow_angle": None,
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
                "No person detected — get into frame, lying face-down on the floor."
            )
            response.update(self._progress_fields())
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

        if not torso_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._register_broken_frame()
            response["feedback"] = (
                "Can't see your torso — make sure your shoulders and hips "
                "are both in frame."
            )
            response.update(self._progress_fields())
            return response

        response["pose_detected"] = True

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)
        shoulder_width = _dist(l_shoulder, r_shoulder)

        view_mode = _view_mode(shoulder_width, torso_length)
        response["view_mode"] = view_mode

        leg_far = _leg_far_point(l_ankle, r_ankle, l_knee, r_knee)
        if leg_far is None:
            response["low_visibility"] = True
            self._register_broken_frame()
            response["feedback"] = (
                "Can't see your legs clearly — make sure your knees or "
                "ankles are visible in frame."
            )
            response.update(self._progress_fields())
            return response

        leg_length = max(_dist(mid_hip, leg_far), 1e-6)

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

        framing_message = _framing_feedback(bbox_points, bbox_aspect, view_mode)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        # ---- elbow angles (arm-extension quality only) ----
        left_elbow_angle = (
            _angle_deg(l_shoulder, l_elbow, l_wrist) if left_arm_ok else None
        )
        right_elbow_angle = (
            _angle_deg(r_shoulder, r_elbow, r_wrist) if right_arm_ok else None
        )
        elbow_angles = [
            a for a in (left_elbow_angle, right_elbow_angle) if a is not None
        ]
        elbow_angle = sum(elbow_angles) / len(elbow_angles) if elbow_angles else None

        # ---- primary signal: signed hip deviation from the shoulder->leg
        # line (identical formula to hindu_pushup.py's hip_arc). Near 0
        # lying flat; strongly positive at full extension, since both the
        # shoulder and the leg rise while the hip stays anchored. ----
        raw_lift = None
        dx = leg_far.x - mid_shoulder.x
        if abs(dx) > 0.05:
            frac = (mid_hip.x - mid_shoulder.x) / dx
            expected_hip_y = mid_shoulder.y + frac * (leg_far.y - mid_shoulder.y)
            raw_lift = (mid_hip.y - expected_hip_y) / torso_length

        if raw_lift is None:
            response["low_visibility"] = True
            self._register_broken_frame()
            response["feedback"] = (
                "Can't get a clear side-on read of your position — adjust "
                "the camera angle."
            )
            response.update(self._progress_fields())
            return response

        if self.smoothed_lift is None:
            self.smoothed_lift = raw_lift
        else:
            self.smoothed_lift = (
                self.lift_smooth_alpha * raw_lift
                + (1 - self.lift_smooth_alpha) * self.smoothed_lift
            )

        # ---- independent chest-rise / leg-rise (each relative to hip
        # height) — the "both ends up together" signal ----
        chest_rise = (mid_hip.y - mid_shoulder.y) / torso_length
        leg_rise = (mid_hip.y - leg_far.y) / leg_length

        # ---- resolve hold-validity this frame (with hysteresis) ----
        if self.hold_active:
            lift_broken = self.smoothed_lift < LIFT_BROKEN
        else:
            lift_broken = self.smoothed_lift < LIFT_RESUME

        holding_now = framing_message is None and not lift_broken

        # ---- form tiering (only meaningful while holding). Never a hard
        # break — a shallow or one-sided hold still counts toward the
        # timer, just downgraded to "needs_improvement" with a specific,
        # actionable message. Evaluated fresh every frame, only while
        # holding_now, off the current frame's own values — no snapshot /
        # peak-instant logic here at all (see module docstring). ----
        issues: list[str] = []
        messages: list[str] = []
        if holding_now:
            if self.smoothed_lift < LIFT_IDEAL:
                issues.append("shallow_lift")
                messages.append(
                    "Lift higher — chest and legs should come further off the floor."
                )
            if chest_rise < MIN_CHEST_RISE:
                issues.append("chest_not_lifted")
                messages.append("Lift your chest and arms higher off the floor.")
            if leg_rise < MIN_LEG_RISE:
                issues.append("legs_not_lifted")
                messages.append("Lift your legs higher off the floor.")
            if elbow_angle is not None and elbow_angle < PEAK_ARM_EXTENSION:
                issues.append("arms_bent")
                messages.append("Reach your arms out straight overhead.")

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

        is_complete = self._is_complete()
        target_reached = is_complete and not self._was_complete
        self._was_complete = is_complete

        # ---- feedback priority: framing/position > hard break > form
        # flaws > praise ----
        feedback = framing_message
        if feedback is None and lift_broken:
            feedback = (
                "That's not a Superman hold yet — lift your chest and legs "
                "together off the floor, arms reaching overhead."
            )
        if feedback is None and messages:
            feedback = messages[0]
        if feedback is None and target_reached:
            feedback = f"Target reached — {self.target_seconds}s held, nice work!"
        if feedback is None and holding_now:
            feedback = "Great Superman hold — keep it up!"
        if feedback is None:
            feedback = "Get back into position to resume the timer."

        response.update(
            {
                "view_mode": view_mode,
                "lift": raw_lift,
                "smoothed_lift": self.smoothed_lift,
                "chest_rise": chest_rise,
                "leg_rise": leg_rise,
                "left_elbow_angle": left_elbow_angle,
                "right_elbow_angle": right_elbow_angle,
                "elbow_angle": elbow_angle,
                "hold_state": "holding" if holding_now else "broken",
                "is_holding": holding_now,
                "target_reached": target_reached,
                "hold_quality": hold_quality,
                "posture_ok": len(issues) == 0,
                "posture_issues": issues,
                "posture_messages": messages,
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


class SupermanSession:
    """Full Superman session: one shared pose model + one analyzer.

    `target_seconds` / `target_sets` / `set_number` are the coach-assigned
    plan for this user, supplied by the caller (the websocket route, from
    query params) — same convention as `PlankHoldSession` /
    `SidePlankSession`. The frontend does not decide on its own whether a
    set/exercise is done; `session_complete` and `exercise_complete` are
    both computed here.
    """

    def __init__(
        self,
        target_seconds: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = SupermanAnalyzer(target_seconds)
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
