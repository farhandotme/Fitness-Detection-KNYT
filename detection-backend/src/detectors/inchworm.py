"""
Inchworm detector.

THE MOVEMENT
------------
An inchworm rep is a full standing <-> plank cycle:

    1. Standing tall  — feet hip-width, body upright. This is the resting
       / start position and also where a completed rep ends.
    2. Walk-out        — hinge at the hips and walk the hands forward along
       the floor until the body is a straight, extended plank.
    3. Plank + hold    — hands land directly below the shoulders, body in
       one straight line, core tight, glutes squeezed, neck neutral, eyes
       looking slightly ahead of the hands. Per the brief this position is
       held for about one second before reversing.
    4. Walk-back        — walk the hands back in toward the feet and stand
       back up tall, completing the rep.

WHY THIS ISN'T A COPY OF `pushup.py` OR `hindu_pushup.py`
-----------------------------------------------------------
Push-ups and Hindu push-ups both live entirely on the floor — the analyzer
only ever has to decide *whether the floor position is being held right
now* and drive a rep off an angle/arc that oscillates while grounded.
Inchworms are the opposite: the floor plank is only the midpoint of a rep
that STARTS and ENDS standing. So the primary state machine here toggles
between two full-body postures (standing vs. plank) rather than an angle
threshold, and a rep only counts if:

    - the user actually left standing and reached a confirmed plank
      (walked out, not just leaned over),
    - they held that plank for >= ~1 second (the brief's explicit hold),
    - and they returned all the way back to a confirmed standing posture
      (walked back in, not just collapsed to the floor).

Camera-angle-independent standing/plank classification reuses the same
three-vote geometry pushup.py pioneered (leg-vertical ratio, torso
incline, bounding-box aspect) — the physical postures are the same
push-up "floor" and "standing" shapes, just used as the two poles of one
full cycle instead of "exercising" vs. "not exercising".
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    LEFT_WRIST,
    NOSE,
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
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 3


# ---- standing <-> plank classification (same geometry pushup.py uses for
# its floor gate — here both poles are meaningful body positions, not just
# "exercising" vs "resting") ----
LEG_VERTICAL_STANDING_MIN = 0.85  # hip-to-feet vertical gap / torso length
LEG_VERTICAL_PLANK_MAX = 0.45
TORSO_INCLINE_STANDING_MIN_DEG = 55.0
TORSO_INCLINE_PLANK_MAX_DEG = 35.0
BBOX_ASPECT_PLANK_MIN = 1.2  # width/height of visible-landmark bbox
BBOX_ASPECT_STANDING_MAX = 0.75

STABLE_FRAMES = 5  # consecutive good frames before a posture is "confirmed"
GRACE_FRAMES = 8  # consecutive bad frames tolerated before it's un-confirmed

# The brief's explicit hold requirement.
MIN_HOLD_SECONDS = 1.0

# A walk-out/walk-back that never actually settles shouldn't stall forever —
# if a rep attempt (leaving standing to returning to standing) drags on this
# long without completing, quietly reset instead of leaving stale state.
MAX_ATTEMPT_SECONDS = 25.0

# "Hands directly below shoulders" — horizontal offset between wrist and
# shoulder, normalized by shoulder width. Small offset = hands stacked
# under the shoulders like the brief specifies.
HAND_SHOULDER_OFFSET_MAX = 0.55

# Body-line straightness in the plank (core tight / glutes squeezed reads,
# in landmarks, as "no hip sag or pike") — identical formula to
# pushup.py's alignment check.
HIP_SAG_THRESHOLD = 0.18
HIP_PIKE_THRESHOLD = -0.18

# Soft, non-blocking quality cues.
KNEE_STRAIGHT_MIN_DEG = 155.0  # legs should be close to straight in the hold
NECK_DROOP_MAX = 0.42  # nose.y this far below the shoulder line = head hanging

# View-mode classification (shoulder width / torso length)
SIDE_VIEW_RATIO_MAX = 0.45
FRONT_VIEW_RATIO_MIN = 0.85

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


def _angle3_deg(a, b, c) -> float:
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


def _torso_incline_deg(mid_shoulder, mid_hip) -> Optional[float]:
    dx = mid_hip.x - mid_shoulder.x
    dy = mid_hip.y - mid_shoulder.y
    if dx == 0 and dy == 0:
        return None
    return math.degrees(math.atan2(abs(dy), max(abs(dx), 1e-9)))


def _bbox_aspect(points: list) -> Optional[float]:
    if len(points) < 4:
        return None
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    if height <= 1e-6:
        return None
    return width / height


def _assess_stance(
    leg_vertical_ratio: Optional[float],
    torso_incline_deg: Optional[float],
    bbox_aspect: Optional[float],
) -> tuple[bool, bool]:
    """Votes across three independent, camera-agnostic cues. Returns
    (is_plank, is_standing) — both require agreement, not just a majority,
    so a lone ambiguous cue (e.g. mid walk-out) can never flip the result
    on its own."""
    standing_votes = 0
    plank_votes = 0

    if leg_vertical_ratio is not None:
        if leg_vertical_ratio >= LEG_VERTICAL_STANDING_MIN:
            standing_votes += 2
        elif leg_vertical_ratio <= LEG_VERTICAL_PLANK_MAX:
            plank_votes += 2

    if torso_incline_deg is not None:
        if torso_incline_deg >= TORSO_INCLINE_STANDING_MIN_DEG:
            standing_votes += 1
        elif torso_incline_deg <= TORSO_INCLINE_PLANK_MAX_DEG:
            plank_votes += 1

    if bbox_aspect is not None:
        if bbox_aspect >= BBOX_ASPECT_PLANK_MIN:
            plank_votes += 1
        elif bbox_aspect <= BBOX_ASPECT_STANDING_MAX:
            standing_votes += 1

    is_plank = plank_votes >= 2 and standing_votes == 0
    is_standing = standing_votes >= 2 and plank_votes == 0
    return is_plank, is_standing


def _framing_feedback(points: list) -> Optional[str]:
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


class InchwormAnalyzer:
    """Stateful inchworm rep counter.

    Rep = standing -> confirmed plank (hands under shoulders, body
    straight) -> held for >= MIN_HOLD_SECONDS -> confirmed standing again.
    Reaching the plank but standing back up before the hold is satisfied
    does NOT count — it's tracked separately as a "partial" attempt so the
    person gets told exactly why it didn't count.
    """

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        # "standing" = home/rest position (start & end of a rep)
        # "plank"    = extended position (the counted midpoint of a rep)
        self.stage = "standing"

        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.partial_rep_count = 0

        self.session_start_time: Optional[float] = None

        # Plank-confirmation hysteresis
        self._plank_streak = 0
        self._plank_bad_streak = 0
        self.ready = False  # confirmed plank position

        # Standing-confirmation hysteresis
        self._standing_streak = 0
        self._standing_bad_streak = 0
        self.standing_confirmed = True  # sessions start at rest, standing

        # In-flight rep bookkeeping
        self._attempt_start_time: Optional[float] = None
        self._hold_start_time: Optional[float] = None
        self._hold_confirmed = False
        self._current_rep_issues: set[str] = set()

    # ---------------------------------------------------------------
    def _classify_hold(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 2.5:
            return "great_control"
        if duration >= 1.4:
            return "solid_hold"
        if duration >= MIN_HOLD_SECONDS:
            return "just_made_it"
        return "too_short"

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
            "standing_confirmed": self.standing_confirmed,
            "torso_incline": None,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "partial_rep_count": self.partial_rep_count,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_duration": None,
            "rep_hold_duration": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "hold_progress": 0.0,
            "hold_elapsed": None,
            "hold_required": MIN_HOLD_SECONDS,
            "hold_confirmed": False,
            "hands_aligned": True,
            "legs_straight": True,
            "neck_neutral": True,
            "alignment_ok": True,
            "alignment_issue": None,
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
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]
        nose = landmarks[NOSE]

        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
        if not torso_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your torso clearly — make sure your shoulders "
                "and hips are both in frame."
            )
            return response

        response["pose_detected"] = True

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)
        shoulder_width = max(_dist(l_shoulder, r_shoulder), 1e-6)

        view_mode = _view_mode(shoulder_width, torso_length)
        response["view_mode"] = view_mode

        leg_far = _leg_far_point(l_ankle, r_ankle, l_knee, r_knee)
        leg_vertical_ratio = (
            abs(mid_hip.y - leg_far.y) / torso_length if leg_far is not None else None
        )
        torso_incline = _torso_incline_deg(mid_shoulder, mid_hip)
        response["torso_incline"] = (
            round(torso_incline, 1) if torso_incline is not None else None
        )

        bbox_candidates = [
            p
            for p in (
                l_shoulder,
                r_shoulder,
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

        # ---- camera framing (independent of inchworm form) ----
        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        # ---- THE critical check: standing vs. plank, camera-angle-agnostic ----
        is_plank, is_standing = _assess_stance(
            leg_vertical_ratio, torso_incline, bbox_aspect
        )

        if is_plank:
            self._plank_streak += 1
            self._plank_bad_streak = 0
        else:
            self._plank_streak = 0
            self._plank_bad_streak += 1

        if self._plank_streak >= STABLE_FRAMES:
            self.ready = True
        elif self._plank_bad_streak >= GRACE_FRAMES:
            self.ready = False
        # else: keep previous state — short grace period for tracking noise

        if is_standing:
            self._standing_streak += 1
            self._standing_bad_streak = 0
        else:
            self._standing_streak = 0
            self._standing_bad_streak += 1

        if self._standing_streak >= STABLE_FRAMES:
            self.standing_confirmed = True
        elif self._standing_bad_streak >= GRACE_FRAMES:
            self.standing_confirmed = False

        response["ready"] = self.ready
        response["standing_confirmed"] = self.standing_confirmed
        response["position_ok"] = self.ready

        # ---- hands-under-shoulders (only meaningful once actually in plank) ----
        hands_aligned = True
        if self.ready:
            wrist_offsets = []
            if _visible((l_wrist,)):
                wrist_offsets.append(abs(l_wrist.x - l_shoulder.x) / shoulder_width)
            if _visible((r_wrist,)):
                wrist_offsets.append(abs(r_wrist.x - r_shoulder.x) / shoulder_width)
            if wrist_offsets:
                hands_aligned = (
                    sum(wrist_offsets) / len(wrist_offsets) <= HAND_SHOULDER_OFFSET_MAX
                )
        response["hands_aligned"] = hands_aligned

        # ---- body-line straightness — core tight / glutes squeezed reads as
        # no hip sag or pike (identical formula to pushup.py) ----
        alignment_issue = None
        alignment_message = None
        if self.ready and view_mode in ("side", "angled") and leg_far is not None:
            dx = leg_far.x - mid_shoulder.x
            if abs(dx) > 0.05:
                frac = (mid_hip.x - mid_shoulder.x) / dx
                expected_hip_y = mid_shoulder.y + frac * (leg_far.y - mid_shoulder.y)
                deviation = (mid_hip.y - expected_hip_y) / torso_length
                if deviation > HIP_SAG_THRESHOLD:
                    alignment_issue = "hip_sag"
                    alignment_message = (
                        "Squeeze your core and glutes — your hips are sagging. "
                        "Keep a straight line from shoulders to heels."
                    )
                elif deviation < HIP_PIKE_THRESHOLD:
                    alignment_issue = "hip_pike"
                    alignment_message = (
                        "Lower your hips slightly — you're piking up. Keep a "
                        "straight line from shoulders to heels."
                    )
        if not hands_aligned and alignment_issue is None:
            alignment_issue = "hands_not_under_shoulders"
            alignment_message = (
                "Walk your hands in so they land directly below your shoulders."
            )
        response["alignment_ok"] = alignment_issue is None
        response["alignment_issue"] = alignment_issue

        # ---- soft quality cues: legs straight, neck neutral (never block a rep) ----
        legs_straight = True
        if self.ready:
            knee_angles = []
            if _visible((l_hip, l_knee, l_ankle)):
                knee_angles.append(_angle3_deg(l_hip, l_knee, l_ankle))
            if _visible((r_hip, r_knee, r_ankle)):
                knee_angles.append(_angle3_deg(r_hip, r_knee, r_ankle))
            if knee_angles:
                legs_straight = (
                    sum(knee_angles) / len(knee_angles) >= KNEE_STRAIGHT_MIN_DEG
                )
        response["legs_straight"] = legs_straight

        neck_neutral = True
        if self.ready and _visible((nose,)) and view_mode in ("side", "angled"):
            neck_neutral = (mid_shoulder.y - nose.y) / torso_length > -NECK_DROOP_MAX
        response["neck_neutral"] = neck_neutral

        feedback = framing_message

        # ---- position guidance when not actively holding a confirmed plank ----
        if self.stage == "standing" and not self.ready:
            position_message = (
                "Stand tall, feet hip-width apart, then hinge forward and "
                "walk your hands out to a full plank."
            )
        elif self.stage == "plank" and not self.ready:
            position_message = (
                "Walk your hands back toward your feet and stand back up tall."
            )
        else:
            position_message = None
        response["position_message"] = position_message

        # ---- rep state machine ----
        rep_completed = False
        rep_duration = rep_hold_duration = rep_class = rep_form_quality = None

        # Guard against a stalled attempt (e.g. camera cut out mid rep).
        if (
            self._attempt_start_time is not None
            and t - self._attempt_start_time > MAX_ATTEMPT_SECONDS
        ):
            self._attempt_start_time = None
            self._hold_start_time = None
            self._hold_confirmed = False
            self._current_rep_issues = set()
            self.stage = "standing"

        if self.stage == "standing":
            if self.ready:
                # Just walked out into a confirmed plank.
                self.stage = "plank"
                self._attempt_start_time = t
                self._hold_start_time = t
                self._hold_confirmed = False
                self._current_rep_issues = set()
                feedback = feedback or "Plank reached — hold it steady."
        else:  # self.stage == "plank"
            if alignment_issue:
                self._current_rep_issues.add(alignment_issue)

            if self.ready:
                # Still holding — track hold duration.
                if self._hold_start_time is None:
                    self._hold_start_time = t
                hold_elapsed = t - self._hold_start_time
                response["hold_elapsed"] = round(hold_elapsed, 2)
                response["hold_progress"] = min(1.0, hold_elapsed / MIN_HOLD_SECONDS)

                if not self._hold_confirmed and hold_elapsed >= MIN_HOLD_SECONDS:
                    self._hold_confirmed = True
                    feedback = feedback or (
                        "Hold complete — walk your hands back and stand up."
                    )
                response["hold_confirmed"] = self._hold_confirmed

                if not legs_straight:
                    self._current_rep_issues.add("bent_knees")
                if not neck_neutral:
                    self._current_rep_issues.add("neck_not_neutral")

            elif self.standing_confirmed:
                # Walked all the way back to standing — the rep attempt resolves here.
                rep_duration = (
                    (t - self._attempt_start_time)
                    if self._attempt_start_time is not None
                    else None
                )
                rep_hold_duration = (
                    (t - self._hold_start_time) if self._hold_start_time is not None
                    else None
                )
                # Use the last-known hold_elapsed if the plank was lost the
                # instant before standing was confirmed (rare, single-frame
                # edge case with the grace-frame hysteresis above).
                if rep_hold_duration is None:
                    rep_hold_duration = 0.0

                if self._hold_confirmed:
                    self.rep_count += 1
                    rep_completed = True
                    rep_class = self._classify_hold(rep_hold_duration)

                    if self._current_rep_issues:
                        rep_form_quality = "needs_improvement"
                        self.flawed_reps += 1
                        issue_text = ", ".join(
                            i.replace("_", " ") for i in sorted(self._current_rep_issues)
                        )
                        feedback = f"Rep {self.rep_count} counted, but watch your form ({issue_text})."
                    else:
                        rep_form_quality = "good"
                        self.good_reps += 1
                        feedback = (
                            f"Clean rep — held {rep_hold_duration:.1f}s in a solid plank."
                        )
                else:
                    self.partial_rep_count += 1
                    feedback = (
                        "You stood up before holding the plank for a full "
                        f"second (held {rep_hold_duration:.1f}s) — not counted."
                    )

                self.stage = "standing"
                self._attempt_start_time = None
                self._hold_start_time = None
                self._hold_confirmed = False
                self._current_rep_issues = set()
            # else: mid walk-back, neither plank nor standing confirmed yet —
            # just wait, no state change.

        if feedback is None and alignment_issue:
            feedback = alignment_message
        if feedback is None and self.stage == "plank" and not legs_straight:
            feedback = "Straighten your legs for a deeper hamstring stretch."
        if feedback is None and self.stage == "plank" and not neck_neutral:
            feedback = "Keep your neck neutral — eyes looking slightly ahead, not down."
        if feedback is None and self.stage == "standing" and not self.ready:
            feedback = position_message
        if feedback is None:
            feedback = "Good form — keep going."

        response.update(
            {
                "stage": self.stage,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "partial_rep_count": self.partial_rep_count,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_duration": rep_duration,
                "rep_hold_duration": rep_hold_duration,
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "feedback": feedback,
            }
        )
        return response


class InchwormSession:
    """Full inchworm session: one shared pose model + one analyzer.

    Same `target_reps` / `target_sets` / `set_number` contract as
    `PushupSession` — the backend, not the frontend, decides when a set
    or the whole assigned plan is complete.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = InchwormAnalyzer(target_reps)
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
