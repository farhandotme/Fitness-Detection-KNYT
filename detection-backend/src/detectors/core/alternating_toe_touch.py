import math
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

# Landmark visibility: torso must be strong, limbs can be slightly weaker.
MIN_LANDMARK_VISIBILITY = 0.2  # relaxed from 0.4 for real webcams
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 3


# ---- readiness gating ----
STABLE_READY_FRAMES = 3  # was 5; locks ready faster
GRACE_FRAMES = 20  # ~0.65s tolerance before dropping ready

# ---- reach-proximity thresholds (normalized by robust scale) ----
# proximity = dist(wrist, opposite ankle) / scale
# scale = max(shoulder_width, torso_length)
TOUCH_MAX_RATIO = 2.0  # <= this means “reaching”
NEUTRAL_MIN_RATIO = 3.0  # >= this means “rest” for the active side
FULL_TOUCH_RATIO = 1.2  # closer-than-this is a “good touch”

CONFIRM_FRAMES = 2  # consecutive frames to confirm phase change

# ---- rep tempo thresholds ----
MIN_REP_DURATION = 0.3  # seconds (fast but controllable)
MAX_REP_DURATION = 5.0  # seconds (slow but still valid)

# Optional safeguard: don’t allow reach phase to run forever
MAX_REACH_PHASE_DURATION = 2.0  # seconds in reaching_* before forcing neutral

# ---- cheat-form thresholds (quality flags, do not block counting) ----
KNEE_STRAIGHT_MIN_DEG = 140.0  # allow a bit more bend than 150°; still flag

# ---- camera framing ----
FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_FAR = 0.12


class _Point:
    __slots__ = ("x", "y")

    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y


def _midpoint(a, b) -> _Point:
    return _Point((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _visible(points) -> bool:
    for p in points:
        if p is None:
            return False
        v = getattr(p, "visibility", None)
        if v is not None and v < MIN_LANDMARK_VISIBILITY:
            return False
    return True


def _angle_at(a, b, c) -> Optional[float]:
    """Angle at vertex b, between rays b->a and b->c, in degrees."""
    first = (a.x - b.x, a.y - b.y)
    second = (c.x - b.x, c.y - b.y)
    first_len = math.hypot(*first)
    second_len = math.hypot(*second)
    if first_len < 1e-7 or second_len < 1e-7:
        return None
    cosine = (first[0] * second[0] + first[1] * second[1]) / (first_len * second_len)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _framing_feedback(points: list) -> Optional[str]:
    # Edge clipping check
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — reposition so your whole "
                "body, hands to feet, stays visible."
            )

    if len(points) < 4:
        return None

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    span = max(width, height)

    # Only check “too far”; no “too close” cutoff here.
    if span < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class AlternatingToeTouchAnalyzer:
    """Stateful alternating-toe-touch rep counter."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        # neutral / reaching_right / reaching_left
        self.phase = "neutral"
        self._pending_phase: Optional[str] = None
        self._pending_streak = 0

        self.rep_start_time: Optional[float] = None
        self.session_start_time: Optional[float] = None

        # Readiness gating
        self._ready_streak = 0
        self._bad_streak = 0
        self._visibility_bad_streak = 0
        self.ready = False

        # Per-rep quality tracking
        self._rep_closest_ratio: Optional[float] = None
        self._rep_min_knee_angle: Optional[float] = None
        self._last_touched_side: Optional[str] = None

    # ---------------------------------------------------------------
    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 3.0:
            return "too_slow"
        if duration >= 1.6:
            return "slow"
        if duration >= 0.7:
            return "good"
        if duration >= MIN_REP_DURATION:
            return "fast"
        return "too_fast"

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _reset_rep_trackers(self) -> None:
        self._rep_closest_ratio = None
        self._rep_min_knee_angle = None

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
            "phase": self.phase,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_duration": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "rep_flaws": [],
            "right_reach_ratio": None,
            "left_reach_ratio": None,
            "knee_angle": None,
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

        # --- person and visibility gating ---
        if landmarks is None or not _looks_like_a_person(landmarks):
            self._visibility_bad_streak += 1
            if self._visibility_bad_streak >= GRACE_FRAMES:
                self._invalidate_in_progress_rep()
                self.ready = False
            response["feedback"] = (
                "No person detected — lie in view of the camera with your "
                "whole body, hands to feet, visible."
            )
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
        if not torso_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._visibility_bad_streak += 1
            if self._visibility_bad_streak >= GRACE_FRAMES:
                self._invalidate_in_progress_rep()
                self.ready = False
            response["feedback"] = (
                "Can't see your torso clearly — make sure your shoulders "
                "and hips are both in frame."
            )
            return response

        limbs_visible = _visible((l_wrist, r_wrist, l_knee, r_knee, l_ankle, r_ankle))
        if not limbs_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._visibility_bad_streak += 1
            if self._visibility_bad_streak >= GRACE_FRAMES:
                self._invalidate_in_progress_rep()
                self.ready = False
            response["feedback"] = (
                "Can't see your hands and feet clearly — reposition so "
                "your whole body is in frame."
            )
            return response

        response["pose_detected"] = True
        self._visibility_bad_streak = 0

        # ---- robust scale reference ----
        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        shoulder_width = _dist(l_shoulder, r_shoulder)
        torso_length = _dist(mid_shoulder, mid_hip)
        scale = max(shoulder_width, torso_length, 1e-6)

        # Cross-body reach distances
        right_reach_ratio = _dist(r_wrist, l_ankle) / scale
        left_reach_ratio = _dist(l_wrist, r_ankle) / scale

        left_knee_angle = _angle_at(l_hip, l_knee, l_ankle)
        right_knee_angle = _angle_at(r_hip, r_knee, r_ankle)
        knee_angles = [a for a in (left_knee_angle, right_knee_angle) if a is not None]
        knee_angle = sum(knee_angles) / len(knee_angles) if knee_angles else None

        framing_points = [
            l_shoulder,
            r_shoulder,
            l_hip,
            r_hip,
            l_wrist,
            r_wrist,
            l_ankle,
            r_ankle,
        ]
        framing_message = _framing_feedback(framing_points)
        framing_ok = framing_message is None

        if framing_ok:
            self._ready_streak += 1
            self._bad_streak = 0
        else:
            self._ready_streak = 0
            self._bad_streak += 1

        if self._ready_streak >= STABLE_READY_FRAMES:
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES:
            if self.ready:
                self._invalidate_in_progress_rep()
            self.ready = False

        position_message: Optional[str] = None
        if not framing_ok:
            position_message = framing_message
        elif not self.ready:
            position_message = (
                "Get into position — lying down, in view of the camera, to begin."
            )

        position_ok = self.ready and framing_ok
        response.update(
            {
                "position_ok": position_ok,
                "position_message": position_message,
                "ready": self.ready,
                "right_reach_ratio": round(right_reach_ratio, 3),
                "left_reach_ratio": round(left_reach_ratio, 3),
                "knee_angle": round(knee_angle, 1) if knee_angle is not None else None,
                "framing_ok": framing_ok,
                "framing_message": framing_message,
            }
        )

        if not self.ready:
            response["feedback"] = position_message
            return response

        # ---- per-rep quality trackers ----
        if self.phase == "neutral":
            self._reset_rep_trackers()

        if self.phase in ("reaching_right", "reaching_left") or self._pending_phase in (
            "reaching_right",
            "reaching_left",
        ):
            active_ratio = (
                right_reach_ratio
                if (
                    self.phase == "reaching_right"
                    or self._pending_phase == "reaching_right"
                )
                else left_reach_ratio
            )
            self._rep_closest_ratio = (
                active_ratio
                if self._rep_closest_ratio is None
                else min(self._rep_closest_ratio, active_ratio)
            )
            if knee_angle is not None:
                self._rep_min_knee_angle = (
                    knee_angle
                    if self._rep_min_knee_angle is None
                    else min(self._rep_min_knee_angle, knee_angle)
                )

        # ---- candidate phase ----
        if self.phase == "reaching_right":
            if right_reach_ratio >= NEUTRAL_MIN_RATIO:
                candidate_phase = "neutral"
            elif right_reach_ratio <= TOUCH_MAX_RATIO:
                candidate_phase = "reaching_right"
            else:
                candidate_phase = None
        elif self.phase == "reaching_left":
            if left_reach_ratio >= NEUTRAL_MIN_RATIO:
                candidate_phase = "neutral"
            elif left_reach_ratio <= TOUCH_MAX_RATIO:
                candidate_phase = "reaching_left"
            else:
                candidate_phase = None
        else:  # neutral
            right_touch = right_reach_ratio <= TOUCH_MAX_RATIO
            left_touch = left_reach_ratio <= TOUCH_MAX_RATIO
            if right_touch and left_touch:
                candidate_phase = (
                    "reaching_right"
                    if right_reach_ratio <= left_reach_ratio
                    else "reaching_left"
                )
            elif right_touch:
                candidate_phase = "reaching_right"
            elif left_touch:
                candidate_phase = "reaching_left"
            else:
                candidate_phase = None

        # Timeout safeguard: if we’ve been in reach too long, force neutral
        if (
            self.phase in ("reaching_right", "reaching_left")
            and self.rep_start_time is not None
            and t - self.rep_start_time > MAX_REACH_PHASE_DURATION
            and candidate_phase is None
        ):
            candidate_phase = "neutral"

        feedback = framing_message
        rep_completed = False
        rep_duration = rep_class = rep_form_quality = None
        rep_flaws: list[str] = []

        # Debounce phase change
        if candidate_phase is not None and candidate_phase == self._pending_phase:
            self._pending_streak += 1
        elif candidate_phase is not None:
            self._pending_phase = candidate_phase
            self._pending_streak = 1
        else:
            self._pending_phase = None
            self._pending_streak = 0

        if (
            candidate_phase is not None
            and self._pending_streak >= CONFIRM_FRAMES
            and candidate_phase != self.phase
        ):
            if candidate_phase in ("reaching_right", "reaching_left"):
                self.phase = candidate_phase
                if self.rep_start_time is None:
                    self.rep_start_time = t
                side = "right" if candidate_phase == "reaching_right" else "left"
                feedback = f"Reaching {side} — now lower back down with control."
            else:  # candidate_phase == "neutral"
                if self.phase in ("reaching_right", "reaching_left"):
                    touched_side = "right" if self.phase == "reaching_right" else "left"
                    duration = (
                        (t - self.rep_start_time)
                        if self.rep_start_time is not None
                        else None
                    )
                    valid = (
                        duration is not None
                        and MIN_REP_DURATION <= duration <= MAX_REP_DURATION
                    )

                    if valid:
                        self.rep_count += 1
                        rep_completed = True
                        rep_duration = duration
                        rep_class = self._classify_tempo(duration)

                        if (
                            self._rep_closest_ratio is None
                            or self._rep_closest_ratio > FULL_TOUCH_RATIO
                        ):
                            rep_flaws.append("shallow_reach")
                        if (
                            self._rep_min_knee_angle is not None
                            and self._rep_min_knee_angle < KNEE_STRAIGHT_MIN_DEG
                        ):
                            rep_flaws.append("legs_bending")
                        if (
                            self._last_touched_side is not None
                            and self._last_touched_side == touched_side
                        ):
                            rep_flaws.append("not_alternating")

                        self._last_touched_side = touched_side

                        if rep_flaws:
                            rep_form_quality = "needs_improvement"
                            self.flawed_reps += 1
                            flaw_text = {
                                "shallow_reach": "reach further — really try to get your hand to your foot",
                                "legs_bending": "keep your legs straighter, don't let your knees bend",
                                "not_alternating": "alternate sides — reach the opposite hand next rep",
                            }
                            feedback = (
                                f"Rep {self.rep_count} counted, but "
                                f"{flaw_text[rep_flaws[0]]}."
                            )
                        else:
                            rep_form_quality = "good"
                            self.good_reps += 1
                            feedback = (
                                f"Clean rep — {rep_class} tempo "
                                f"({duration:.2f}s). Rep {self.rep_count}."
                            )
                    else:
                        if duration is not None and duration < MIN_REP_DURATION:
                            feedback = "Too fast — that rep wasn't counted, control the movement."
                        else:
                            feedback = (
                                "Not counted — keep the reach and return continuous."
                            )

                    self.rep_start_time = None

                self.phase = "neutral"
                self._reset_rep_trackers()

        if feedback is None:
            if self.phase != "neutral":
                feedback = "Lower back down with control."
            elif self._is_complete():
                feedback = f"Target reached — {self.target_reps} reps completed."
            else:
                feedback = "Reach one hand toward the opposite foot to begin."

        response.update(
            {
                "phase": self.phase,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_duration": rep_duration,
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "rep_flaws": rep_flaws,
                "feedback": feedback,
            }
        )
        return response

    # ---------------------------------------------------------------
    def _invalidate_in_progress_rep(self):
        """Tracking broke (or person left frame) mid-rep."""
        self._pending_phase = None
        self._pending_streak = 0
        self.rep_start_time = None
        self._reset_rep_trackers()
        self.phase = "neutral"


class AlternatingToeTouchSession:
    """Full alternating-toe-touch session: one shared pose model + one analyzer."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = AlternatingToeTouchAnalyzer(target_reps)
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
