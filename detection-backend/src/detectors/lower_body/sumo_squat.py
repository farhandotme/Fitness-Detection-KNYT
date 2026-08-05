"""
Sumo squat rep counter + strict stance/depth/form gate.

Design (mirrors `pushup.py`'s philosophy exactly)
--------------------------------------------------
A sumo squat is judged on FOUR camera-agnostic, joint-angle-only signals —
no object detection, so the dumbbell/kettlebell itself is never tracked,
only what the body does:

  1. **Stance width** — feet must be planted meaningfully wider than the
     shoulders. This is the one thing that makes a squat a *sumo* squat
     instead of a regular squat, so it's the hard gate: nothing counts as
     a sumo rep until a sufficiently wide stance is confirmed, the same
     way `pushup.py` refuses to count anything until a real floor plank is
     confirmed.
  2. **Depth** — knees must bend past a real threshold (not a half-hearted
     dip). Same idea as push-up's `MIN_ANGLE_DELTA` — insufficient travel
     means the rep is simply not counted, full stop.
  3. **Knee tracking** — knees must track out over the toes, not cave
     inward ("knee valgus"). This does NOT block the rep from counting
     (a person doing a real sumo squat with wobbly knees is still doing a
     sumo squat) but it does mark the rep `flawed` — identical to how
     `pushup.py` still counts a rep with hip sag, just tags it.
  4. **Torso posture** — sumo squats stay fairly upright (unlike a
     deadlift-style forward hinge). Excess forward lean is likewise a
     `flawed` tag, not a hard block.

Rep state machine
------------------
`stage` is "up" (standing, knees extended) at rest, and flips to "down"
once the knee angle drops below `SQUAT_ANGLE` **while the stance gate is
satisfied**. The rep completes (and only then is it evaluated / counted)
when the knee angle rises back above `STAND_ANGLE`. This is the same
down/up edge-triggered pattern as `PushupAnalyzer`, just re-anchored to
knee angle instead of elbow angle and to "up" (not "down") as the resting
stage, because a squat's neutral/rest position is standing tall.

Nothing here ever counts a rep purely from a single good-looking frame —
exactly like the push-up detector, correctness is judged across the whole
down->up cycle (stance held, real depth reached, tempo sane), and a
result that fails those checks is explicitly reported as "not counted"
rather than silently incrementing anything.
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_FOOT_INDEX,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_FOOT_INDEX,
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


# Knee angle (hip-knee-ankle) thresholds driving the rep state machine.
# Standing tall = large angle (leg straight); bottom of the squat = small
# angle (knee sharply bent).
STAND_ANGLE = 160.0  # legs considered fully extended (top / rest position)
SQUAT_ANGLE = 120.0  # bent enough to count as "in the squat"
MIN_ANGLE_DELTA = 35.0  # total angle travel required for a rep to "count"
MIN_REP_DURATION = 0.4  # seconds — faster than this = uncontrolled/bouncing
MAX_REP_DURATION = 8.0  # seconds — slower than this = probably a pause, not a rep

# -------------------------------------------------------------------------
# Sumo-stance gate (the thing that makes this a SUMO squat, not a squat)
# -------------------------------------------------------------------------
# ankle-to-ankle distance / shoulder-to-shoulder distance. A regular squat
# stance sits close to ~1.0; sumo squats plant the feet noticeably wider.
STANCE_RATIO_MIN = 1.35
STANCE_RATIO_GOOD = 1.55  # comfortably wide — used only for feedback tone

STABLE_STANCE_FRAMES = 5  # consecutive good frames before counting turns on
GRACE_FRAMES = 8  # consecutive bad frames tolerated before counting turns off

# View-mode classification (shoulder width / hip width) — sumo squat form
# can only be judged facing the camera (or close to it); a hard side-on
# view hides both the stance width and the knee-tracking check.
SIDE_VIEW_SHOULDER_HIP_MAX = 0.55
FRONT_VIEW_SHOULDER_HIP_MIN = 0.8

# Knee tracking (valgus / knees caving in), normalized against stance width.
# knee-to-knee distance / ankle-to-ankle distance. In a good wide sumo
# squat the knees push out roughly as wide as the feet; if this ratio
# collapses, the knees are caving inward.
KNEE_TRACK_GOOD_MIN = 0.75
KNEE_TRACK_FLAW_MAX = 0.6  # below this is flagged as a real valgus flaw

# Torso posture — sumo squats stay upright. Angle measured from horizontal
# (same convention as pushup.py's torso incline helper): ~90 deg = fully
# vertical torso, smaller = leaning forward.
TORSO_UPRIGHT_MIN_DEG = 55.0

# Camera framing
FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.97
BBOX_TOO_FAR = 0.12


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


def _torso_incline_deg(mid_shoulder, mid_hip) -> Optional[float]:
    dx = mid_hip.x - mid_shoulder.x
    dy = mid_hip.y - mid_shoulder.y
    if dx == 0 and dy == 0:
        return None
    return math.degrees(math.atan2(abs(dy), max(abs(dx), 1e-9)))


def _bbox_aspect_points(points: list[_Point]) -> Optional[tuple[float, float]]:
    if len(points) < 4:
        return None
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    return (max(xs) - min(xs), max(ys) - min(ys))


def _framing_feedback(points: list[_Point]) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — reposition so your whole body is visible."
            )

    box = _bbox_aspect_points(points)
    if box is None:
        return None
    width, height = box

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return (
            "You're too close to the camera — back up so your whole body fits in frame."
        )
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


def _view_mode(shoulder_width: float, hip_width: float) -> str:
    ratio = shoulder_width / max(hip_width, 1e-6)
    if ratio <= SIDE_VIEW_SHOULDER_HIP_MAX:
        return "side"
    if ratio >= FRONT_VIEW_SHOULDER_HIP_MIN:
        return "front"
    return "angled"


class SumoSquatAnalyzer:
    """Stateful sumo-squat rep counter + strict wide-stance gate."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        # Rep state machine
        self.stage = "up"  # "up" = standing (rest), "down" = squat bottom
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        self.smoothed_angle: Optional[float] = None
        self.last_angle: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None
        self.rep_start_time: Optional[float] = None
        self._rep_angle_acc = 0.0
        self.angle_smooth_alpha = 0.6

        self.session_start_time: Optional[float] = None

        # Stance gating (see module docstring) — same streak/hysteresis
        # pattern as PushupAnalyzer's floor-position gate.
        self._stance_streak = 0
        self._bad_streak = 0
        self.ready = False

        self._current_rep_issues: set[str] = set()
        # tracks the deepest knee angle reached during the current
        # down-phase so a shallow "bounce" doesn't get credited as depth.
        self._attempt_min_angle: Optional[float] = None

    # ---------------------------------------------------------------
    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 3.5:
            return "too_slow"
        if duration >= 2.0:
            return "slow"
        if duration >= 0.8:
            return "good"
        if duration >= 0.4:
            return "fast"
        return "too_fast"

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
            "view_mode": None,
            "position_ok": False,
            "position_message": None,
            "ready": self.ready,
            "angle": None,
            "smoothed_angle": None,
            "left_knee_angle": None,
            "right_knee_angle": None,
            "stance_ratio": None,
            "stance_ok": False,
            "knee_track_ratio": None,
            "knee_tracking_ok": True,
            "torso_angle": None,
            "torso_upright_ok": True,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_duration": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = "No person detected — step into frame."
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]
        l_foot, r_foot = landmarks[LEFT_FOOT_INDEX], landmarks[RIGHT_FOOT_INDEX]

        legs_visible = _visible((l_hip, l_knee, l_ankle)) and _visible(
            (r_hip, r_knee, r_ankle)
        )
        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))

        if not legs_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your legs clearly — step back so your hips, "
                "knees, and ankles are all in frame."
            )
            return response

        if not torso_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your torso — make sure your shoulders and hips "
                "are both in frame."
            )
            return response

        response["pose_detected"] = True

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        shoulder_width = _dist(l_shoulder, r_shoulder)
        hip_width = max(_dist(l_hip, r_hip), 1e-6)
        ankle_width = _dist(l_ankle, r_ankle)
        knee_width = _dist(l_knee, r_knee)

        view_mode = _view_mode(shoulder_width, hip_width)
        response["view_mode"] = view_mode

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

        # ---- camera framing (independent of squat form) ----
        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        # ---- stance width — the sumo-specific hard gate ----
        stance_ratio = ankle_width / max(shoulder_width, 1e-6)
        response["stance_ratio"] = stance_ratio
        stance_wide_enough = stance_ratio >= STANCE_RATIO_MIN
        facing_camera = view_mode in ("front", "angled")
        stance_ok = stance_wide_enough and facing_camera and framing_message is None
        response["stance_ok"] = stance_ok

        if stance_ok:
            self._stance_streak += 1
            self._bad_streak = 0
        else:
            self._stance_streak = 0
            self._bad_streak += 1

        if self._stance_streak >= STABLE_STANCE_FRAMES:
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES:
            self.ready = False
        # else: keep previous `ready` state — short grace period for tracking noise

        position_ok = self.ready
        response["position_ok"] = position_ok
        response["ready"] = self.ready

        if not facing_camera:
            position_message = (
                "Turn to face the camera — sumo squat stance needs to be "
                "seen from the front to track correctly."
            )
        elif not stance_wide_enough:
            position_message = (
                f"Widen your stance — feet need to be noticeably wider "
                f"than shoulder-width for a sumo squat "
                f"(currently {stance_ratio:.2f}x shoulder width, need "
                f"{STANCE_RATIO_MIN:.2f}x+)."
            )
        elif not position_ok:
            position_message = (
                "Set up in a wide sumo stance, toes turned out, facing "
                "the camera, before starting your reps."
            )
        else:
            position_message = None
        response["position_message"] = position_message

        # ---- knee angles (drive rep counting) ----
        left_angle = _angle_deg(l_hip, l_knee, l_ankle)
        right_angle = _angle_deg(r_hip, r_knee, r_ankle)
        raw_angle = (left_angle + right_angle) / 2.0
        response["left_knee_angle"] = left_angle
        response["right_knee_angle"] = right_angle

        if self.smoothed_angle is None:
            self.smoothed_angle = raw_angle
        else:
            self.smoothed_angle = (
                self.angle_smooth_alpha * raw_angle
                + (1 - self.angle_smooth_alpha) * self.smoothed_angle
            )

        # ---- knee tracking (valgus) — informational flaw, not a hard gate ----
        knee_track_ratio = knee_width / max(ankle_width, 1e-6)
        response["knee_track_ratio"] = knee_track_ratio
        knee_tracking_ok = knee_track_ratio >= KNEE_TRACK_FLAW_MAX
        response["knee_tracking_ok"] = knee_tracking_ok

        # ---- torso posture — informational flaw, not a hard gate ----
        torso_angle = _torso_incline_deg(mid_shoulder, mid_hip)
        response["torso_angle"] = torso_angle
        torso_upright_ok = torso_angle is None or torso_angle >= TORSO_UPRIGHT_MIN_DEG
        response["torso_upright_ok"] = torso_upright_ok

        feedback = framing_message

        # ---- rep state machine — only ever progresses in a valid stance ----
        rep_completed = False
        rep_duration = rep_class = rep_form_quality = None

        if not position_ok:
            if self.rep_start_time is not None:
                # Mid-rep and the stance broke — the attempt doesn't count.
                self.rep_start_time = None
                self._rep_angle_acc = 0.0
                self._attempt_min_angle = None
                self._current_rep_issues = set()
                if feedback is None:
                    feedback = (
                        "Lost sumo stance mid-rep — not counted. Reset to "
                        "standing and try again."
                    )
            if feedback is None:
                feedback = position_message
        else:
            # Only in the "down" phase do we track how deep they went and
            # whether knee-tracking / posture issues occurred.
            if self.stage == "down":
                if (
                    self._attempt_min_angle is None
                    or self.smoothed_angle < self._attempt_min_angle
                ):
                    self._attempt_min_angle = self.smoothed_angle
                if not knee_tracking_ok:
                    self._current_rep_issues.add("knee_valgus")
                if not torso_upright_ok:
                    self._current_rep_issues.add("forward_lean")

            if self.stage == "up" and self.smoothed_angle < SQUAT_ANGLE:
                self.stage = "down"
                self.rep_start_time = t
                self._rep_angle_acc = 0.0
                self._attempt_min_angle = self.smoothed_angle
                self._current_rep_issues = set()
                if not knee_tracking_ok:
                    self._current_rep_issues.add("knee_valgus")
                if not torso_upright_ok:
                    self._current_rep_issues.add("forward_lean")
            elif self.stage == "down" and self.smoothed_angle > STAND_ANGLE:
                self.stage = "up"
                rep_completed = True

            if self.last_angle is not None and self.rep_start_time is not None:
                self._rep_angle_acc += abs(self.smoothed_angle - self.last_angle)

            if feedback is None and self.stage == "down":
                if not stance_wide_enough:
                    feedback = "Keep your stance wide through the whole rep."
                elif not knee_tracking_ok:
                    feedback = "Push your knees out over your toes — don't let them cave in."
                elif not torso_upright_ok:
                    feedback = "Keep your chest up — don't lean forward."

            if rep_completed:
                rep_duration = (
                    (t - self.rep_start_time)
                    if self.rep_start_time is not None
                    else None
                )

                depth_reached = (
                    self._attempt_min_angle is not None
                    and (STAND_ANGLE - self._attempt_min_angle) >= MIN_ANGLE_DELTA
                )
                valid = (
                    rep_duration is not None
                    and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                    and depth_reached
                    and stance_wide_enough
                )

                if valid:
                    self.rep_count += 1
                    rep_class = self._classify_tempo(rep_duration)

                    if self._current_rep_issues:
                        rep_form_quality = "needs_improvement"
                        self.flawed_reps += 1
                        issue_text = ", ".join(
                            i.replace("_", " ")
                            for i in sorted(self._current_rep_issues)
                        )
                        feedback = (
                            f"Rep {self.rep_count} counted, but watch your "
                            f"form ({issue_text})."
                        )
                    else:
                        rep_form_quality = "good"
                        self.good_reps += 1
                        if rep_class in ("good", "fast"):
                            feedback = (
                                f"Clean sumo squat — {rep_class} tempo "
                                f"({rep_duration:.2f}s)."
                            )
                        elif rep_class in ("slow", "too_slow"):
                            feedback = (
                                f"Good depth, nice and controlled "
                                f"({rep_duration:.2f}s)."
                            )
                        else:
                            feedback = (
                                f"Clean rep, but control the tempo "
                                f"({rep_duration:.2f}s)."
                            )
                else:
                    rep_completed = False
                    if rep_duration is not None and rep_duration < MIN_REP_DURATION:
                        feedback = (
                            "Too fast — that one wasn't counted, control the movement."
                        )
                    elif rep_duration is not None and rep_duration > MAX_REP_DURATION:
                        feedback = "That rep took too long — not counted. Keep moving."
                    elif not stance_wide_enough:
                        feedback = (
                            "Stance narrowed during the rep — not counted as "
                            "a sumo squat."
                        )
                    else:
                        feedback = (
                            "Not enough depth — sit lower into the squat. Not counted."
                        )

                self.rep_start_time = None
                self._rep_angle_acc = 0.0
                self._attempt_min_angle = None
                self._current_rep_issues = set()

        self.last_angle = self.smoothed_angle
        self.last_timestamp_s = t

        if feedback is None and not self.ready:
            feedback = (
                "Set up in a wide sumo stance, facing the camera, to start "
                "counting reps."
            )
        if feedback is None:
            feedback = "Good form — keep going."

        response.update(
            {
                "angle": raw_angle,
                "smoothed_angle": self.smoothed_angle,
                "stage": self.stage,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_duration": rep_duration,
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "feedback": feedback,
            }
        )
        return response


class SumoSquatSession:
    """Full sumo-squat session: one shared pose model + one analyzer.

    `target_reps` / `target_sets` / `set_number` are the coach-assigned
    plan for this user, supplied by the caller (the websocket route, from
    query params) — same convention as `PushupSession`. The frontend does
    not decide on its own whether a set/exercise is done; `session_complete`
    (this set's reps are done) and `exercise_complete` (the whole assigned
    plan — all sets — is done) are computed here.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = SumoSquatAnalyzer(target_reps)
        self.target_sets = max(1, target_sets)
        self.set_number = max(1, min(set_number, self.target_sets))

    def detect(self, frame, timestamp_ms: int) -> dict[str, Any]:
        landmarks = self.engine.detect(frame, timestamp_ms)
        result = self.analyzer.update(landmarks, timestamp_ms)
        result["landmarks"] = (
            PoseEngine.landmarks_to_json(landmarks) if landmarks else []
        )

        # Backend-validated plan progress — frontend just reads these, it
        # never computes them itself.
        result["set_number"] = self.set_number
        result["target_sets"] = self.target_sets
        result["exercise_complete"] = bool(
            result["session_complete"] and self.set_number >= self.target_sets
        )
        return result

    def close(self):
        self.engine.close()
