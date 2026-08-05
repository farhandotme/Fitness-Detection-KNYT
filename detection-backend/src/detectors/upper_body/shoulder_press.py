"""
Shoulder press rep counting.

Design (kept deliberately simple — see project note: this is for everyday
gym users, not a biomechanics lab)
------------------------------------------------------------------------
A shoulder press only needs ONE number to know where the person is in the
rep: the elbow angle (shoulder-elbow-wrist). Hands start bent near the
shoulders ("bottom") and the rep is counted once the arms have gone all
the way up straight overhead and come back down to the shoulders again
("top" -> back to "bottom").

To keep this reliable and avoid the two failure modes we were explicitly
asked to avoid — (1) "it's not detecting me" and (2) "it keeps flagging
flaws that aren't real" — this file intentionally does very little beyond
that one core measurement:

  * Only ONE hard gate before counting starts: can we actually see both
    shoulders/elbows/wrists. No floor-position voting, no calibration
    step, no orientation classification like the push-up detector needs.
  * "Are you standing" is judged generously. If we can see the hips we
    use them for a loose sanity check; if the camera is framed from the
    waist up (hips not visible — very common for an overhead-press shot)
    we simply assume standing rather than blocking the count.
  * Only ONE soft form note (leaning back) — and it never stops a rep
    from counting, it's just a coaching tip. Everything else people
    might associate with "advanced" press form (bar path, wrist wobble,
    scapular tracking, etc.) is left out on purpose.
  * All on-screen messages are written the way you'd talk to a friend at
    the gym, not the way a physio would chart it.
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

CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER)

# Elbow angle (shoulder-elbow-wrist) thresholds driving the rep state
# machine. Same hysteresis-band idea as the push-up counter: you need to
# clear TOP_ANGLE to register "pressed all the way up", and drop back
# below BOTTOM_ANGLE to register "back down" and lock the rep in — the
# gap between the two stops a borderline angle from double-counting.
TOP_ANGLE = 150.0  # arms considered straight overhead
BOTTOM_ANGLE = 100.0  # elbows bent enough to count as the starting position
MIN_ANGLE_DELTA = 35.0  # total angle travel required for a rep to "count"
MIN_REP_DURATION = 0.35  # seconds — faster than this = uncontrolled/momentum
MAX_REP_DURATION = 10.0  # seconds — slower than this = probably a pause, not a rep

# "Go higher" partial-rep coaching (mirrors the push-up detector's logic)
PARTIAL_REP_MARGIN_DEG = 15.0
PARTIAL_REP_MIN_RANGE_DEG = 20.0
PARTIAL_REP_BOUNCE_DEG = 8.0

# Overhead lockout: at the top of the rep we also check the wrist has
# actually gone above the shoulder line (not just that the elbow angle
# opened up) — this is what stops "waving your arms around" from being
# counted as a press. Kept generous on purpose (a small margin, not "wrist
# above your head").
WRIST_ABOVE_SHOULDER_MARGIN = 0.02  # fraction of frame height

# Standing check — generous. If hips aren't visible we skip this
# entirely rather than block counting (see module docstring).
MAX_LEAN_FROM_VERTICAL_DEG = 45.0

# Leaning-back soft coaching note (never blocks a rep). Also skipped
# entirely if hips aren't visible.
LEAN_BACK_WARN_DEG = 18.0

STABLE_FRAMES = 5  # consecutive good frames before counting turns on
GRACE_FRAMES = 10  # consecutive bad frames tolerated before counting turns off

# Camera framing
FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.97  # bbox width or height fraction of frame
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


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 1


def _framing_feedback(points: list[_Point]) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — step back so your arms fit in the shot."
            )

    if len(points) < 3:
        return None

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "You're too close to the camera — back up a bit."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move a bit closer."

    return None


class ShoulderPressAnalyzer:
    """Stateful shoulder-press rep counter — see module docstring."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.stage = "bottom"  # "bottom" = hands at shoulders, "top" = arms overhead
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.partial_rep_count = 0

        self.smoothed_angle: Optional[float] = None
        self.last_angle: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None
        self.rep_start_time: Optional[float] = None
        self._rep_angle_acc = 0.0
        self.angle_smooth_alpha = 0.6

        self.session_start_time: Optional[float] = None

        self._attempt_max_angle: Optional[float] = None
        self._attempt_flagged = False

        self._good_streak = 0
        self._bad_streak = 0
        self.ready = False

        self._current_rep_issues: set[str] = set()

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
        if duration >= 0.35:
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
            "position_ok": False,
            "position_message": None,
            "ready": self.ready,
            "angle": None,
            "smoothed_angle": None,
            "left_elbow_angle": None,
            "right_elbow_angle": None,
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
            "lean_ok": True,
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None or not _looks_like_a_person(landmarks):
            response["feedback"] = "We can't see you yet — step into the camera view."
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]

        left_arm_ok = _visible((l_shoulder, l_elbow, l_wrist))
        right_arm_ok = _visible((r_shoulder, r_elbow, r_wrist))

        if not left_arm_ok and not right_arm_ok:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "We can't see your arms clearly — make sure your shoulders, "
                "elbows and hands are all visible in the camera."
            )
            return response

        response["pose_detected"] = True

        # ---- camera framing ----
        bbox_candidates = [
            p
            for p in (l_shoulder, r_shoulder, l_elbow, r_elbow, l_wrist, r_wrist)
            if _visible((p,))
        ]
        bbox_points = [_Point(p.x, p.y) for p in bbox_candidates]
        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        # ---- standing check — generous, skipped if hips aren't visible ----
        hips_visible = _visible((l_hip, r_hip)) and _visible((l_shoulder, r_shoulder))
        is_standing = True  # default to "yes" so we never block on a guess
        if hips_visible:
            mid_shoulder = _midpoint(l_shoulder, r_shoulder)
            mid_hip = _midpoint(l_hip, r_hip)
            dx = mid_hip.x - mid_shoulder.x
            dy = mid_hip.y - mid_shoulder.y
            lean_deg = math.degrees(math.atan2(abs(dx), max(abs(dy), 1e-6)))
            is_standing = lean_deg <= MAX_LEAN_FROM_VERTICAL_DEG
        else:
            lean_deg = None

        if is_standing:
            self._good_streak += 1
            self._bad_streak = 0
        else:
            self._good_streak = 0
            self._bad_streak += 1

        if self._good_streak >= STABLE_FRAMES:
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES:
            self.ready = False

        position_ok = self.ready and framing_message is None
        response["position_ok"] = position_ok
        response["ready"] = self.ready

        if framing_message:
            position_message = None
        elif not self.ready:
            position_message = "Stand up straight, facing the camera, with room to raise your arms overhead."
        else:
            position_message = None
        response["position_message"] = position_message

        # ---- elbow angles (drive rep counting) ----
        left_angle = _angle_deg(l_shoulder, l_elbow, l_wrist) if left_arm_ok else None
        right_angle = _angle_deg(r_shoulder, r_elbow, r_wrist) if right_arm_ok else None
        angles = [a for a in (left_angle, right_angle) if a is not None]
        raw_angle = sum(angles) / len(angles)

        if self.smoothed_angle is None:
            self.smoothed_angle = raw_angle
        else:
            self.smoothed_angle = (
                self.angle_smooth_alpha * raw_angle
                + (1 - self.angle_smooth_alpha) * self.smoothed_angle
            )

        # ---- overhead lockout check (wrist above shoulder line) ----
        wrists_up = []
        if left_arm_ok:
            wrists_up.append(l_wrist.y < l_shoulder.y - WRIST_ABOVE_SHOULDER_MARGIN)
        if right_arm_ok:
            wrists_up.append(r_wrist.y < r_shoulder.y - WRIST_ABOVE_SHOULDER_MARGIN)
        wrists_overhead = any(wrists_up) if wrists_up else False

        # ---- leaning-back soft note — skipped if hips aren't visible ----
        lean_issue = None
        if (
            position_ok
            and self.stage == "top"
            and hips_visible
            and lean_deg is not None
            and lean_deg > LEAN_BACK_WARN_DEG
        ):
            lean_issue = "leaning_back"
        response["lean_ok"] = lean_issue is None

        feedback = framing_message

        # ---- rep state machine ----
        rep_completed = False
        rep_duration = rep_class = rep_form_quality = None
        partial_feedback = None

        if not position_ok:
            if self.rep_start_time is not None:
                self.rep_start_time = None
                self._rep_angle_acc = 0.0
                self._current_rep_issues = set()
            if feedback is None:
                feedback = position_message
        else:
            if self.stage == "bottom":
                if (
                    self._attempt_max_angle is None
                    or self.smoothed_angle > self._attempt_max_angle
                ):
                    self._attempt_max_angle = self.smoothed_angle
                elif (
                    not self._attempt_flagged
                    and self._attempt_max_angle is not None
                    and self._attempt_max_angle - self.smoothed_angle
                    > PARTIAL_REP_BOUNCE_DEG
                    and self._attempt_max_angle < TOP_ANGLE - PARTIAL_REP_MARGIN_DEG
                    and self._attempt_max_angle - BOTTOM_ANGLE
                    > PARTIAL_REP_MIN_RANGE_DEG
                ):
                    self._attempt_flagged = True
                    self.partial_rep_count += 1
                    partial_feedback = (
                        "Almost — press a little higher next time, all the "
                        "way until your arms are straight above you."
                    )

                if self.smoothed_angle < BOTTOM_ANGLE + 5:
                    self._attempt_max_angle = None
                    self._attempt_flagged = False

            if (
                self.stage == "bottom"
                and self.smoothed_angle > TOP_ANGLE
                and wrists_overhead
            ):
                self.rep_start_time = t
                self._rep_angle_acc = 0.0
            if self.last_angle is not None:
                self._rep_angle_acc += abs(self.smoothed_angle - self.last_angle)

            if (
                self.stage == "bottom"
                and self.smoothed_angle > TOP_ANGLE
                and wrists_overhead
            ):
                self.stage = "top"
                self._current_rep_issues = set()
            elif self.stage == "top" and self.smoothed_angle < BOTTOM_ANGLE:
                self.stage = "bottom"
                rep_completed = True

            if self.stage == "top" and lean_issue:
                self._current_rep_issues.add(lean_issue)

            if feedback is None:
                feedback = partial_feedback

            if rep_completed:
                rep_duration = (
                    (t - self.rep_start_time)
                    if self.rep_start_time is not None
                    else None
                )

                valid = (
                    rep_duration is not None
                    and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                    and self._rep_angle_acc >= MIN_ANGLE_DELTA
                )

                if valid:
                    self.rep_count += 1
                    rep_class = self._classify_tempo(rep_duration)

                    if self._current_rep_issues:
                        rep_form_quality = "needs_improvement"
                        self.flawed_reps += 1
                        feedback = (
                            f"Rep {self.rep_count} counted — try to keep your "
                            f"back straight instead of leaning backward."
                        )
                    else:
                        rep_form_quality = "good"
                        self.good_reps += 1
                        if rep_class in ("good", "fast"):
                            feedback = f"Nice press! Rep {self.rep_count} done."
                        elif rep_class in ("slow", "too_slow"):
                            feedback = (
                                f"Good control on that one — rep {self.rep_count} done."
                            )
                        else:
                            feedback = f"Rep {self.rep_count} counted — try a smoother, steadier pace."
                else:
                    rep_completed = False
                    if rep_duration is not None and rep_duration < MIN_REP_DURATION:
                        feedback = "That was too fast to count — slow down a little."
                    elif rep_duration is not None and rep_duration > MAX_REP_DURATION:
                        feedback = (
                            "That took a while, so it wasn't counted — keep moving."
                        )
                    else:
                        feedback = (
                            "Not quite enough movement to count — press further up."
                        )

                self.rep_start_time = None
                self._rep_angle_acc = 0.0
                self._current_rep_issues = set()

        self.last_angle = self.smoothed_angle
        self.last_timestamp_s = t

        if feedback is None and lean_issue:
            feedback = (
                "Keep your back straight — try not to lean backward as you press."
            )
        if feedback is None and not self.ready:
            feedback = (
                "Stand facing the camera with your arms visible to start counting."
            )
        if feedback is None:
            feedback = "Good form — keep going."

        response.update(
            {
                "angle": raw_angle,
                "smoothed_angle": self.smoothed_angle,
                "left_elbow_angle": left_angle,
                "right_elbow_angle": right_angle,
                "stage": self.stage,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_duration": rep_duration,
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "lean_ok": lean_issue is None,
                "feedback": feedback,
            }
        )
        return response


class ShoulderPressSession:
    """Full shoulder-press session: one shared pose model + one analyzer.

    Same `target_reps` / `target_sets` / `set_number` contract as the
    other exercises (see PushupSession) — the backend, not the frontend,
    is the source of truth for whether a set / the whole plan is done.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = ShoulderPressAnalyzer(target_reps)
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
