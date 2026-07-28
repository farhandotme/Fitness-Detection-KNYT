"""
Arnold press — bilateral overhead-press rep counter.

Design
------
Same "angle at a joint drives a down/up hysteresis state machine" pattern
as `pushup.py` / `leg_raise.py` / `single_leg_squat.py`, applied to the
elbow:

    elbow_angle = angle(SHOULDER, ELBOW, WRIST)

Bottom (the "rack" position — dumbbells at shoulder height, palms facing
in) reads a bent elbow, roughly 70-110°; pressing overhead extends that
toward straight. Both arms move together (this is a bilateral press, not
an alternating one), so — same reasoning as `leg_raise.py` — the rep
clock runs off both arms' average angle, `arms_in_sync` is a soft note
rather than a blocker, and if one arm's wrist/elbow briefly drops out of
tracking the other carries the rep alone instead of stalling it.

What actually makes it an "Arnold" press vs. a plain overhead/shoulder
press is the palm-rotation through the movement — and that's not
something a 2D pose skeleton can see at all (no hand-orientation data,
just a wrist point). So this detector counts the press motion itself
(the part that's actually measurable) and leaves the rotation cue as
coaching copy rather than something it grades — same honesty tradeoff
`leg_raise.py` makes about not being able to see forearm rotation either.

Why no calibration step (unlike `single_leg_squat.py`)
--------------------------------------------------------
The single-leg-squat bug came from measuring a joint angle across a
plane that foreshortens badly from the front — a standing leg's true
extension reads far below 180° in 2D specifically because it extends
mostly along the camera's depth axis. An overhead press doesn't have
that problem from a front-facing camera: the arm's range of motion is
mostly vertical, in-plane, not depth-wise, so the projected elbow angle
tracks the real one reasonably well without per-session calibration.
Fixed, generous thresholds (same approach `leg_raise.py` uses
successfully) are appropriate here instead. What front-view *does*
distort is telling "pressed overhead" apart from "arms raised out to the
side" — both can read a similarly extended elbow angle — so `top_reached`
also requires the wrist to actually be above the shoulder line, not just
the elbow being straight.

Position gate
--------------
Arnold press is legitimately done standing or seated, so — unlike
`single_leg_squat.py` — this gate does not care about standing vs.
seated at all. It only disqualifies a frame on clear evidence the torso
is not upright (folded over / lying down), same permissive-by-default
"guilty until proven not-upright" approach as the other gates, so a
slouched-but-fine seated posture or a slightly rotated camera never
zeroes out `position_ok` mid-rep.

Framing
--------
The standard edge-of-frame framing check (borrowed from `leg_raise.py`)
deliberately excludes the wrists from the top-edge test: a wrist
approaching the top edge of frame during a real overhead press is
expected, not a framing problem, and penalizing it would flag "out of
frame" on every clean rep. The setup copy tells the user to leave
headroom above their head instead of the detector fighting a normal rep.
"""

import math
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

# -------------------------------------------------------------------------
# Tunable constants
# -------------------------------------------------------------------------

MIN_LANDMARK_VISIBILITY = 0.4
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)

# Elbow angle (shoulder-elbow-wrist). Deliberately generous — this is a
# rep-counting exercise, not a lockout grader, so a correctly performed
# rep must always count even without a picture-perfect 180° extension.
BOTTOM_ANGLE = 115.0  # rack position — elbows bent, weights near shoulder height
TOP_ANGLE = 150.0  # extended overhead — not requiring a strict lockout
MIN_ANGLE_DELTA = 30.0  # total angle travel required for a rep to "count"
MIN_REP_DURATION = 0.4
MAX_REP_DURATION = 10.0

# "Overhead" confirmation — an arm straight out to the side can read a
# similarly extended elbow angle to a real press, so top position also
# requires the wrist to sit above the shoulder line by this fraction of
# torso length.
WRIST_ABOVE_SHOULDER_MIN = 0.10

# "Rack" confirmation at the bottom — wrist roughly at shoulder height,
# not down at the hip (which would also read a bent elbow on some builds).
WRIST_NEAR_SHOULDER_MAX = 0.55

# Left/right symmetry — "one arm lagging" soft note vs. an unusable rep.
SYNC_SOFT_TOLERANCE_DEG = 20.0
SYNC_BLOCK_TOLERANCE_DEG = 50.0

# Torso stability (soft note) — excessive incline drift during a rep
# usually means leaning back/swinging to use momentum instead of
# pressing with the shoulders.
TORSO_DRIFT_TOLERANCE_DEG = 15.0

# Position gate — permissive by default, standing or seated both valid.
# See module docstring for why this doesn't check standing-vs-seated.
TORSO_INCLINE_NOT_UPRIGHT_MAX_DEG = 40.0
STABLE_FRAMES = 3
GRACE_FRAMES = 24  # ~0.8s at 30fps — absorbs real tracking noise/occlusion

# Camera framing
FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.95
BBOX_TOO_FAR = 0.15


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


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 3


def _torso_incline_deg(mid_shoulder, mid_hip) -> Optional[float]:
    """0deg = torso lying flat/horizontal, 90deg = torso perfectly vertical."""
    dx = mid_hip.x - mid_shoulder.x
    dy = mid_hip.y - mid_shoulder.y
    if dx == 0 and dy == 0:
        return None
    return math.degrees(math.atan2(abs(dy), max(abs(dx), 1e-9)))


def _assess_upright_position(torso_incline_deg: Optional[float]) -> tuple[bool, bool]:
    """(is_acceptable, is_clearly_not_upright).

    Only disqualifies a frame on clear evidence of NOT upright (folded
    over near-horizontal) — standing or seated both pass, since both are
    legitimate ways to do this exercise. Same asymmetric, permissive
    reasoning as the other exercises' gates.
    """
    not_upright = (
        torso_incline_deg is not None
        and torso_incline_deg <= TORSO_INCLINE_NOT_UPRIGHT_MAX_DEG
    )
    return (not not_upright), not_upright


def _framing_feedback(
    core_points: list[_Point], wrist_points: list[_Point]
) -> Optional[str]:
    """Same edge/too-close/too-far check as `leg_raise.py`, except the
    wrists are deliberately excluded from the top-edge test — a wrist
    near the top of frame mid-press is expected, not a framing problem."""
    for p in core_points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — step back so your whole body is visible."
            )

    for p in wrist_points:
        if p.x < FRAME_EDGE_MARGIN or p.x > 1 - FRAME_EDGE_MARGIN:
            return (
                "You're partly out of frame — step back so your whole body is visible."
            )

    all_points = core_points + wrist_points
    if len(all_points) < 4:
        return None

    xs = [p.x for p in all_points]
    ys = [p.y for p in all_points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "You're too close to the camera — step back so your whole body fits in frame."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class ArnoldPressAnalyzer:
    """Stateful bilateral Arnold-press rep counter."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.stage = "down"  # "down" = rack position, "up" = pressed overhead
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        self.smoothed_angle: Optional[float] = None
        self.smoothed_left: Optional[float] = None
        self.smoothed_right: Optional[float] = None
        self.last_angle: Optional[float] = None
        self.angle_smooth_alpha = 0.55

        self.rep_start_time: Optional[float] = None
        self._rep_angle_acc = 0.0
        self._current_rep_issues: set[str] = set()
        self._rep_start_torso_incline: Optional[float] = None

        self.session_start_time: Optional[float] = None

        self._floor_streak = 0
        self._bad_streak = 0
        self.ready = False

    # ---------------------------------------------------------------
    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 3.5:
            return "too_slow"
        if duration >= 2.0:
            return "slow"
        if duration >= 0.7:
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
            "ready": self.ready,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "left_elbow_angle": None,
            "right_elbow_angle": None,
            "arms_in_sync": True,
            "top_reached": False,
            "bottom_reached": False,
            "rep_completed": False,
            "rep_classification": None,
            "rep_form_quality": None,
            "position_ok": False,
            "position_message": None,
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
            # extra fields
            "wrist_overhead_ok": False,
            "torso_stable_ok": True,
            "rep_duration": None,
            "rep_avg_speed": None,
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = "No person detected — step into frame."
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]

        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
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
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)

        torso_incline = _torso_incline_deg(mid_shoulder, mid_hip)

        core_points = [
            _Point(p.x, p.y)
            for p in (l_shoulder, r_shoulder, l_hip, r_hip)
            if _visible((p,))
        ]
        wrist_points = [_Point(p.x, p.y) for p in (l_wrist, r_wrist) if _visible((p,))]

        framing_message = _framing_feedback(core_points, wrist_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        is_acceptable, not_upright = _assess_upright_position(torso_incline)

        if is_acceptable:
            self._floor_streak += 1
            self._bad_streak = 0
        else:
            self._floor_streak = 0
            self._bad_streak += 1

        if self._floor_streak >= STABLE_FRAMES:
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES:
            self.ready = False

        position_ok = self.ready
        response["position_ok"] = position_ok
        response["ready"] = self.ready

        if not_upright and not position_ok:
            position_message = (
                "Sit or stand upright, torso facing the camera, to begin — "
                "standing or seated both work."
            )
        elif not position_ok:
            position_message = (
                "Get into an upright standing or seated position to begin."
            )
        else:
            position_message = None
        response["position_message"] = position_message

        # ---- per-arm elbow angle (drives rep counting) ----
        left_ok = _visible((l_shoulder, l_elbow, l_wrist))
        right_ok = _visible((r_shoulder, r_elbow, r_wrist))

        left_angle = _angle_deg(l_shoulder, l_elbow, l_wrist) if left_ok else None
        right_angle = _angle_deg(r_shoulder, r_elbow, r_wrist) if right_ok else None

        if left_angle is None and right_angle is None:
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your arms clearly — adjust the camera so your "
                "shoulders, elbows, and wrists are all in frame."
            )
            return response

        # One arm briefly occluded — infer it from the other so the rep
        # clock never stalls waiting on a single dropped landmark.
        if left_angle is None:
            left_angle = right_angle
            response["low_visibility"] = True
        if right_angle is None:
            right_angle = left_angle
            response["low_visibility"] = True

        self.smoothed_left = (
            left_angle
            if self.smoothed_left is None
            else self.angle_smooth_alpha * left_angle
            + (1 - self.angle_smooth_alpha) * self.smoothed_left
        )
        self.smoothed_right = (
            right_angle
            if self.smoothed_right is None
            else self.angle_smooth_alpha * right_angle
            + (1 - self.angle_smooth_alpha) * self.smoothed_right
        )

        response["left_elbow_angle"] = round(self.smoothed_left, 1)
        response["right_elbow_angle"] = round(self.smoothed_right, 1)

        raw_angle = (left_angle + right_angle) / 2.0
        self.smoothed_angle = (
            raw_angle
            if self.smoothed_angle is None
            else self.angle_smooth_alpha * raw_angle
            + (1 - self.angle_smooth_alpha) * self.smoothed_angle
        )

        angle_diff = abs(self.smoothed_left - self.smoothed_right)
        arms_in_sync = angle_diff <= SYNC_SOFT_TOLERANCE_DEG
        response["arms_in_sync"] = arms_in_sync

        # ---- "actually overhead", not just "elbow is straight" ----
        wrist_overhead_ok = True
        gaps = []
        if _visible((l_wrist,)):
            gaps.append((mid_shoulder.y - l_wrist.y) / torso_length)
        if _visible((r_wrist,)):
            gaps.append((mid_shoulder.y - r_wrist.y) / torso_length)
        if gaps:
            wrist_overhead_ok = min(gaps) >= WRIST_ABOVE_SHOULDER_MIN
        response["wrist_overhead_ok"] = wrist_overhead_ok

        wrist_near_rack_ok = True
        rack_gaps = []
        if _visible((l_wrist,)):
            rack_gaps.append(abs(mid_shoulder.y - l_wrist.y) / torso_length)
        if _visible((r_wrist,)):
            rack_gaps.append(abs(mid_shoulder.y - r_wrist.y) / torso_length)
        if rack_gaps:
            wrist_near_rack_ok = min(rack_gaps) <= WRIST_NEAR_SHOULDER_MAX

        response["top_reached"] = self.smoothed_angle >= TOP_ANGLE and wrist_overhead_ok
        response["bottom_reached"] = self.smoothed_angle <= BOTTOM_ANGLE

        # ---- torso stability (soft note — leaning back/swinging) ----
        torso_stable_ok = True
        if self._rep_start_torso_incline is not None and torso_incline is not None:
            drift = abs(torso_incline - self._rep_start_torso_incline)
            if drift > TORSO_DRIFT_TOLERANCE_DEG:
                torso_stable_ok = False
        response["torso_stable_ok"] = torso_stable_ok

        feedback = framing_message

        # ---- rep state machine — only progresses while upright-gate is ok ----
        rep_completed = False
        rep_duration = rep_avg_speed = rep_class = rep_form_quality = None

        if not position_ok:
            if self.rep_start_time is not None:
                self.rep_start_time = None
                self._rep_angle_acc = 0.0
                self._current_rep_issues = set()
                self._rep_start_torso_incline = None
                if feedback is None:
                    feedback = (
                        "Lost upright position mid-rep — not counted. "
                        "Reset and try again."
                    )
            if feedback is None:
                feedback = position_message
        else:
            entering_press = (
                self.stage == "down"
                and self.smoothed_angle >= TOP_ANGLE
                and wrist_overhead_ok
            )
            if self.stage == "down" and self.rep_start_time is None:
                self._rep_start_torso_incline = torso_incline

            if self.last_angle is not None:
                self._rep_angle_acc += abs(self.smoothed_angle - self.last_angle)

            if (
                self.stage == "down"
                and self.smoothed_angle > BOTTOM_ANGLE + 5
                and self.rep_start_time is None
            ):
                # Started moving up out of the rack position — this is the
                # actual start of a rep attempt.
                self.rep_start_time = t
                self._rep_angle_acc = 0.0
                self._current_rep_issues = set()

            if self.rep_start_time is not None:
                if not arms_in_sync and angle_diff <= SYNC_BLOCK_TOLERANCE_DEG:
                    self._current_rep_issues.add("arms_not_synced")
                if not torso_stable_ok:
                    self._current_rep_issues.add("using_momentum")
                if response["top_reached"]:
                    pass  # confirmed overhead — no issue to flag
                elif self.smoothed_angle >= TOP_ANGLE and not wrist_overhead_ok:
                    self._current_rep_issues.add("not_fully_overhead")

            if entering_press:
                self.stage = "up"
            elif self.stage == "up" and self.smoothed_angle <= BOTTOM_ANGLE:
                self.stage = "down"
                rep_completed = True

            if feedback is None and not arms_in_sync:
                feedback = "Press both arms together — one is lagging behind the other."
            if feedback is None and not torso_stable_ok:
                feedback = "Keep your torso still — don't lean back to press."
            if (
                feedback is None
                and self.smoothed_angle >= TOP_ANGLE
                and not wrist_overhead_ok
            ):
                feedback = "Press all the way overhead, not out to the side."

            if rep_completed:
                rep_duration = (
                    (t - self.rep_start_time)
                    if self.rep_start_time is not None
                    else None
                )
                if rep_duration and rep_duration > 0:
                    rep_avg_speed = self._rep_angle_acc / rep_duration

                unusable = angle_diff > SYNC_BLOCK_TOLERANCE_DEG

                valid = (
                    not unusable
                    and rep_duration is not None
                    and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                    and self._rep_angle_acc >= MIN_ANGLE_DELTA
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
                        feedback = f"Rep {self.rep_count} counted, but watch your form ({issue_text})."
                    else:
                        rep_form_quality = "good"
                        self.good_reps += 1
                        if rep_class in ("good", "fast"):
                            feedback = f"Clean rep — pressed and lowered with control ({rep_duration:.2f}s)."
                        else:
                            feedback = (
                                f"Good rep, nice and controlled ({rep_duration:.2f}s)."
                            )
                else:
                    rep_completed = False
                    if unusable:
                        feedback = (
                            "That wasn't a synchronized two-arm press — not counted."
                        )
                    elif rep_duration is not None and rep_duration < MIN_REP_DURATION:
                        feedback = (
                            "Too fast — that one wasn't counted, control the movement."
                        )
                    elif rep_duration is not None and rep_duration > MAX_REP_DURATION:
                        feedback = "That rep took too long — not counted. Keep moving."
                    else:
                        feedback = "Not enough range of motion — not counted."

                self.rep_start_time = None
                self._rep_angle_acc = 0.0
                self._current_rep_issues = set()
                self._rep_start_torso_incline = None

            elif (
                not wrist_near_rack_ok
                and self.stage == "down"
                and self.rep_start_time is None
            ):
                # Not actually resting in a rack position (e.g. arms fully
                # down at the sides) — informational only, doesn't block.
                if feedback is None:
                    feedback = (
                        "Start from the rack position — weights at shoulder height."
                    )

        self.last_angle = self.smoothed_angle

        if feedback is None and not self.ready:
            feedback = (
                "Get into position, dumbbells at shoulder height, to start counting."
            )
        if feedback is None:
            feedback = "Good form — keep going."

        response.update(
            {
                "stage": self.stage,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_duration": rep_duration,
                "rep_avg_speed": rep_avg_speed,
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "feedback": feedback,
            }
        )
        return response


class ArnoldPressSession:
    """Full Arnold-press session: one shared pose model + one analyzer.

    Same convention as `LegRaiseSession` / `PushupSession` — `target_reps`
    / `target_sets` / `set_number` are the coach-assigned plan, supplied
    by the websocket route from query params. The frontend never decides
    on its own whether a set/exercise is done; `session_complete` and
    `exercise_complete` are computed here.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = ArnoldPressAnalyzer(target_reps)
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
