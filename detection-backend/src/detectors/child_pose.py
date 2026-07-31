"""
Child's Pose (Balasana) detector — a REP counter, not a hold timer.

THE MOVEMENT
------------
Start in tabletop (hands and knees, spine roughly horizontal, hips over
knees, shoulders over wrists). A rep is:

    1. Tabletop  — the rest/start position described above.
    2. Fold      — push the hips back until they settle onto the heels
       while the chest lowers and folds forward over the thighs, arms
       reaching out along the floor, forehead toward the ground.
    3. Child's Pose — hips resting near the heels, chest low, held
       briefly.
    4. Push back up to Tabletop to complete the rep.

WHY "HIP-TO-HEEL DISTANCE" IS THE PRIMARY SIGNAL
---------------------------------------------------
The single most distinctive, unambiguous feature of this movement is
that the hips travel from well in front of/above the heels (tabletop) to
resting right on top of them (Child's Pose). Unlike the hip-arc trick
used in hindu_pushup.py / superman.py (which relies on a shoulder-to-leg
LINE that changes shape through the whole movement), the reference used
here — shin length, i.e. dist(knee, ankle) — is a **rigid bone segment**
that does not change with pose. Normalizing hip-to-heel distance by shin
length gives a clean, largely linear signal that shrinks monotonically as
the person sits back: high in tabletop, low at the bottom of the fold.
This sidesteps the amplification problems found while calibrating
hindu_pushup.py's line-deviation formula, where small pose changes near
the anchor produced disproportionately large signal swings.

WHY THAT ALONE ISN'T SUFFICIENT FORM
---------------------------------------
Sitting the hips back onto the heels without lowering the chest is a
different (and much easier) position — closer to kneeling upright /
sitting in seiza — not Child's Pose. So a second, independent signal
tracks whether the chest actually dropped: `chest_fold`, the shoulder's
height relative to the hip. In tabletop the shoulder and hip sit at
roughly the same height (flat spine); in a real fold the shoulder ends
up clearly BELOW hip height (chest low to the floor, arms extended
forward). This is checked once, precisely, at the exact instant the
Child's Pose stage is entered — never continuously — for the same reason
documented at length in hindu_pushup.py and superman.py: the chest starts
dropping before the hip-to-heel distance has finished closing, so a
continuous "near the pose" check would misread correct, expected motion
as a defect. A shortfall here never blocks the rep from counting — it
only downgrades that rep to "needs_improvement" with a specific,
actionable message.

WHY THE FLOOR/STANDING GATE USES TABLETOP AS THE REFERENCE SHAPE
---------------------------------------------------------------------
Tabletop, like a plank, has hands and feet both on the floor with the
torso spanning between them — a wide, low silhouette from the side, just
like every other floor exercise in this codebase. Child's Pose is, if
anything, even more compact and low. So a single wide-bbox gate (as used
in superman.py) stays valid across the whole rep without needing to
tolerate a large shape change mid-motion, unlike hindu_pushup.py's
Downward-Dog-vs-plank problem.
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_HEEL,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_HEEL,
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


# ---- fold thresholds (hip-to-heel distance normalized by shin length —
# see module docstring. High in tabletop, low at the bottom of the fold). ----
TABLETOP_MIN = 1.55   # fold_ratio at/above this = confirmed Tabletop (rest state)
POSE_MAX = 1.05        # fold_ratio at/below this = confirmed Child's Pose
MIN_FOLD_DELTA = 0.55  # total fold-ratio travel required for a rep to "count"
MIN_REP_DURATION = 0.6    # seconds — faster than this = bounce, not a rep
MAX_REP_DURATION = 15.0   # seconds — slower than this = stalled, not a rep

# Chest-fold quality check (shoulder height relative to hip height,
# normalized by shin length) — snapshotted once at the exact instant
# Child's Pose is entered (see module docstring for why).
MIN_CHEST_FOLD = 0.35

# "Sink lower" partial-attempt detection (Tabletop -> Pose leg only,
# mirrors hindu_pushup.py's asymmetric partial-rep check). Must leave a
# valid band between POSE_MAX and TABLETOP_MIN.
PARTIAL_BOUNCE_MARGIN = 0.05
PARTIAL_REP_MARGIN = 0.12
PARTIAL_MIN_APPROACH = 0.12


# View-mode classification — the hip-to-heel travel is a front-to-back
# motion a head-on camera would flatten to noise, same reasoning as
# hindu_pushup.py / superman.py.
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


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _heel_point(l_heel, r_heel, l_ankle, r_ankle) -> Optional[_Point]:
    """Prefer the actual heel landmark (anatomically precise for "sitting
    back onto the heels"); fall back to ankle if the heel isn't tracked
    confidently."""
    heels = [p for p in (l_heel, r_heel) if _visible((p,))]
    if len(heels) == 2:
        return _midpoint(*heels)
    if len(heels) == 1:
        return _Point(heels[0].x, heels[0].y)
    ankles = [p for p in (l_ankle, r_ankle) if _visible((p,))]
    if len(ankles) == 2:
        return _midpoint(*ankles)
    if len(ankles) == 1:
        return _Point(ankles[0].x, ankles[0].y)
    return None


def _view_mode(shoulder_width: float, torso_length: float) -> str:
    ratio = shoulder_width / max(torso_length, 1e-6)
    if ratio <= SIDE_VIEW_RATIO_MAX:
        return "side"
    if ratio >= FRONT_VIEW_RATIO_MIN:
        return "front"
    return "angled"


# -------------------------------------------------------------------------
# Floor-stance detection.
#
# An earlier version of this gate used bounding-box aspect ratio (wide =
# floor, narrow = standing) — the same trick used successfully in
# superman.py. It does NOT work here: a real (if flawed) variation of this
# exercise is sitting the hips back onto the heels while keeping the torso
# upright instead of folding forward — and that configuration makes the
# overall silhouette noticeably TALLER (shoulder stays high while hip
# drops toward the heel), which pushed bbox aspect below the floor
# threshold and caused the gate to reject a genuine, if imperfect, floor
# position mid-rep. That's exactly the false-negative failure mode to
# avoid.
#
# The fix: gate on shin verticality instead — |knee.y - ankle.y| relative
# to shin length. On the floor (tabletop, mid-fold, Child's Pose, or the
# "sat back but didn't fold forward" variant above) the shin lies flat
# along the ground in every case, so this ratio stays small regardless of
# what the torso is doing. Standing, the shin is vertical, so the ratio
# approaches 1. This decouples "are you kneeling" from "how are you
# folding" entirely — the torso configuration can no longer interfere
# with the floor gate.
# -------------------------------------------------------------------------
KNEELING_SHIN_VERTICALITY_MAX = 0.55   # ratio at/below this = confirmed kneeling
STANDING_SHIN_VERTICALITY_MIN = 0.75   # ratio at/above this = confirmed standing

STABLE_FLOOR_FRAMES = 5
GRACE_FRAMES = 8

# View-mode classification — the hip-to-heel travel is a front-to-back
# motion a head-on camera would flatten to noise, same reasoning as
# hindu_pushup.py / superman.py.
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


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _heel_point(l_heel, r_heel, l_ankle, r_ankle) -> Optional[_Point]:
    """Prefer the actual heel landmark (anatomically precise for "sitting
    back onto the heels"); fall back to ankle if the heel isn't tracked
    confidently."""
    heels = [p for p in (l_heel, r_heel) if _visible((p,))]
    if len(heels) == 2:
        return _midpoint(*heels)
    if len(heels) == 1:
        return _Point(heels[0].x, heels[0].y)
    ankles = [p for p in (l_ankle, r_ankle) if _visible((p,))]
    if len(ankles) == 2:
        return _midpoint(*ankles)
    if len(ankles) == 1:
        return _Point(ankles[0].x, ankles[0].y)
    return None


def _view_mode(shoulder_width: float, torso_length: float) -> str:
    ratio = shoulder_width / max(torso_length, 1e-6)
    if ratio <= SIDE_VIEW_RATIO_MAX:
        return "side"
    if ratio >= FRONT_VIEW_RATIO_MIN:
        return "front"
    return "angled"


def _assess_floor_stance(
    mid_knee: Optional[_Point],
    mid_ankle: Optional[_Point],
    shin_length: float,
) -> tuple[bool, bool]:
    """(is_floor_stance, is_standing) — see the module-level comment block
    above this section for why shin verticality, not bbox aspect, is the
    right signal here."""
    if mid_knee is None or mid_ankle is None or shin_length <= 1e-6:
        return False, False

    verticality = abs(mid_knee.y - mid_ankle.y) / shin_length
    is_floor = verticality <= KNEELING_SHIN_VERTICALITY_MAX
    is_standing = verticality >= STANDING_SHIN_VERTICALITY_MIN
    return is_floor, is_standing


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

    if len(points) < 4:
        return None

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return "You're too close to the camera — back up so your whole body fits in frame."
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class ChildsPoseAnalyzer:
    """Stateful Child's Pose rep counter.

    Rep = one full Tabletop -> Child's Pose -> Tabletop cycle, validated by:
      - real fold range (MIN_FOLD_DELTA of hip-to-heel travel)
      - sane timing (MIN_REP_DURATION..MAX_REP_DURATION)

    Chest-fold depth at the pose is a quality check only — it can mark a
    rep "needs_improvement" but never blocks it from counting, so a real
    rep (hips sat back, even if the chest didn't fully lower) is never
    silently dropped.
    """

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        # "tabletop" = rest position (start & end of a rep)
        # "pose"     = Child's Pose (far point of a rep)
        self.stage = "tabletop"
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.partial_rep_count = 0

        self.smoothed_fold: Optional[float] = None
        self.last_fold: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None
        self.rep_start_time: Optional[float] = None
        self._rep_fold_acc = 0.0
        self.fold_smooth_alpha = 0.5

        self.session_start_time: Optional[float] = None

        # "Sink lower" partial-attempt detection (Tabletop -> Pose leg only)
        self._attempt_min_fold: Optional[float] = None
        self._attempt_flagged = False

        # Whole-rep quality tracking, snapshotted at the Pose entry instant
        self._best_chest_fold: Optional[float] = None
        self._current_rep_issues: set[str] = set()

        # Floor-stance gating hysteresis
        self._floor_streak = 0
        self._bad_streak = 0
        self.ready = False

    # ---------------------------------------------------------------
    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 5.0:
            return "too_slow"
        if duration >= 3.0:
            return "slow"
        if duration >= 1.0:
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
            "fold_ratio": None,
            "smoothed_fold_ratio": None,
            "chest_fold": None,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "partial_rep_count": self.partial_rep_count,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_duration": None,
            "rep_avg_speed": None,
            "rep_classification": None,
            "rep_form_quality": None,
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
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]
        l_heel, r_heel = landmarks[LEFT_HEEL], landmarks[RIGHT_HEEL]

        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
        legs_visible = _visible((l_knee, r_knee, l_ankle, r_ankle))

        if not torso_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your torso — make sure your shoulders and hips "
                "are both in frame."
            )
            return response

        if not legs_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your legs clearly — make sure your knees and "
                "ankles are visible in frame."
            )
            return response

        response["pose_detected"] = True

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        mid_knee = _midpoint(l_knee, r_knee)
        mid_ankle = _midpoint(l_ankle, r_ankle)
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)
        shoulder_width = _dist(l_shoulder, r_shoulder)
        shin_length = max(_dist(mid_knee, mid_ankle), 1e-6)

        view_mode = _view_mode(shoulder_width, torso_length)
        response["view_mode"] = view_mode

        mid_heel = _heel_point(l_heel, r_heel, l_ankle, r_ankle)

        bbox_candidates = [
            p
            for p in (l_shoulder, r_shoulder, l_hip, r_hip, l_knee, r_knee, l_ankle, r_ankle)
            if _visible((p,))
        ]
        bbox_points = [_Point(p.x, p.y) for p in bbox_candidates]

        # ---- camera framing (independent of exercise form) ----
        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        # ---- THE critical check: kneeling on the floor, not standing.
        # Uses shin verticality (knee/ankle), not silhouette shape — see
        # the comment above _assess_floor_stance for why. ----
        is_floor, is_standing = _assess_floor_stance(mid_knee, mid_ankle, shin_length)

        if is_floor:
            self._floor_streak += 1
            self._bad_streak = 0
        else:
            self._floor_streak = 0
            self._bad_streak += 1

        if self._floor_streak >= STABLE_FLOOR_FRAMES:
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES:
            self.ready = False

        view_ok = view_mode != "front"
        position_ok = self.ready and view_ok
        response["position_ok"] = position_ok
        response["ready"] = self.ready

        if view_mode == "front":
            position_message = (
                "Turn side-on to the camera — Child's Pose needs a side "
                "view to track the fold accurately."
            )
        elif is_standing:
            position_message = (
                "Get onto the floor in tabletop position — hands and "
                "knees down, back flat — to start counting."
            )
        elif not self.ready:
            position_message = (
                "Get into tabletop — hands and knees on the floor, back "
                "flat — to start counting."
            )
        else:
            position_message = None
        response["position_message"] = position_message

        # ---- primary signal: hip-to-heel distance normalized by shin
        # length (a rigid bone segment — see module docstring). High in
        # tabletop, low at the bottom of the fold. ----
        raw_fold = None
        if mid_heel is not None:
            raw_fold = _dist(mid_hip, mid_heel) / shin_length

        if raw_fold is None:
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your heels clearly — make sure your feet are "
                "visible in frame."
            )
            return response

        if self.smoothed_fold is None:
            self.smoothed_fold = raw_fold
        else:
            self.smoothed_fold = (
                self.fold_smooth_alpha * raw_fold
                + (1 - self.fold_smooth_alpha) * self.smoothed_fold
            )

        # ---- chest-fold quality signal: shoulder height relative to hip
        # height, normalized by shin length. Positive & large = shoulder
        # clearly below hip (chest lowered, genuine forward fold). ----
        chest_fold = (mid_shoulder.y - mid_hip.y) / shin_length

        feedback = framing_message

        # ---- rep state machine — only progresses with a confirmed stance ----
        rep_completed = False
        rep_duration = rep_avg_speed = rep_class = rep_form_quality = None
        partial_feedback = None

        if not position_ok:
            if self.rep_start_time is not None:
                self.rep_start_time = None
                self._rep_fold_acc = 0.0
                self._best_chest_fold = None
                self._current_rep_issues = set()
                if feedback is None:
                    feedback = (
                        "Lost the floor position mid-rep — not counted. "
                        "Reset to tabletop and try again."
                    )
            if feedback is None:
                feedback = position_message
        else:
            # ---- "sink lower" partial-attempt detection (Tabletop -> Pose
            # leg only, mirrors hindu_pushup.py's asymmetric check) ----
            if self.stage == "tabletop":
                if (
                    self._attempt_min_fold is None
                    or self.smoothed_fold < self._attempt_min_fold
                ):
                    self._attempt_min_fold = self.smoothed_fold
                elif (
                    not self._attempt_flagged
                    and self._attempt_min_fold is not None
                    and self.smoothed_fold - self._attempt_min_fold > PARTIAL_BOUNCE_MARGIN
                    and self._attempt_min_fold > POSE_MAX + PARTIAL_REP_MARGIN
                    and TABLETOP_MIN - self._attempt_min_fold > PARTIAL_MIN_APPROACH
                ):
                    self._attempt_flagged = True
                    self.partial_rep_count += 1
                    partial_feedback = (
                        "Sit your hips further back toward your heels — "
                        "you're stopping short of the full fold."
                    )

                if self.smoothed_fold > TABLETOP_MIN - 0.05:
                    self._attempt_min_fold = None
                    self._attempt_flagged = False

            # ---- stage transitions ----
            if self.stage == "tabletop" and self.smoothed_fold < POSE_MAX:
                self.rep_start_time = t
                self._rep_fold_acc = 0.0
                self._best_chest_fold = chest_fold

            if self.last_fold is not None:
                self._rep_fold_acc += abs(self.smoothed_fold - self.last_fold)

            # Track the BEST (deepest) chest_fold seen at any point while in
            # the pose, not a single instant — the hip can cross the
            # fold_ratio threshold into "pose" before the chest has finished
            # lowering (they aren't perfectly synchronized), so snapshotting
            # only the entry frame could unfairly flag a rep that goes on to
            # fold deeply moments later. This mirrors hindu_pushup.py's
            # `_rep_min_elbow`, which tracks an extremum across the whole
            # window instead of a single frame, for the same reason.
            if self.stage == "pose":
                if self._best_chest_fold is None or chest_fold > self._best_chest_fold:
                    self._best_chest_fold = chest_fold

            if self.stage == "tabletop" and self.smoothed_fold < POSE_MAX:
                self.stage = "pose"
                self._current_rep_issues = set()
            elif self.stage == "pose" and self.smoothed_fold > TABLETOP_MIN:
                self.stage = "tabletop"
                if self._best_chest_fold is not None and (
                    self._best_chest_fold < MIN_CHEST_FOLD
                ):
                    self._current_rep_issues.add("chest_not_lowered")
                rep_completed = True

            if feedback is None:
                feedback = partial_feedback

            if rep_completed:
                rep_duration = (
                    (t - self.rep_start_time) if self.rep_start_time is not None else None
                )
                if rep_duration and rep_duration > 0:
                    rep_avg_speed = self._rep_fold_acc / rep_duration

                valid = (
                    rep_duration is not None
                    and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                    and self._rep_fold_acc >= MIN_FOLD_DELTA
                )

                if valid:
                    self.rep_count += 1
                    rep_class = self._classify_tempo(rep_duration)

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
                        if rep_class in ("good", "fast"):
                            feedback = f"Clean rep — {rep_class} tempo ({rep_duration:.2f}s)."
                        elif rep_class in ("slow", "too_slow"):
                            feedback = f"Good full fold, nice and controlled ({rep_duration:.2f}s)."
                        else:
                            feedback = f"Clean rep, but control the tempo ({rep_duration:.2f}s)."
                else:
                    rep_completed = False
                    if rep_duration is not None and rep_duration < MIN_REP_DURATION:
                        feedback = "Too fast — that one wasn't counted, control the movement."
                    elif rep_duration is not None and rep_duration > MAX_REP_DURATION:
                        feedback = "That rep took too long — not counted. Keep moving."
                    else:
                        feedback = "Not enough range of motion — not counted."

                self.rep_start_time = None
                self._rep_fold_acc = 0.0
                self._best_chest_fold = None
                self._current_rep_issues = set()

        self.last_fold = self.smoothed_fold
        self.last_timestamp_s = t

        if feedback is None and not self.ready:
            feedback = (
                "Get into tabletop — hands and knees on the floor, back "
                "flat — to start counting."
            )
        if feedback is None:
            feedback = "Good form — keep going."

        response.update(
            {
                "fold_ratio": raw_fold,
                "smoothed_fold_ratio": self.smoothed_fold,
                "chest_fold": chest_fold,
                "stage": self.stage,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "partial_rep_count": self.partial_rep_count,
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


class ChildsPoseSession:
    """Full Child's Pose session: one shared pose model + one analyzer.

    Same coach-assigned-plan convention as `HinduPushupSession` — the
    frontend supplies `target_reps` / `target_sets` / `set_number` via
    query params, and this class is the sole source of truth for
    `session_complete` / `exercise_complete`.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = ChildsPoseAnalyzer(target_reps)
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