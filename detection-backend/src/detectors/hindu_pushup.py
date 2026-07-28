"""
Hindu Push-up detector.

WHY THIS CANNOT BE A COPY OF `pushup.py`
-----------------------------------------
A regular push-up is a hinge at the elbow only: the body stays a rigid
plank (shoulders/hips/ankles in one straight line) and only the elbow
angle changes. `pushup.py` therefore drives its rep counter off elbow
angle, and *penalizes* hip sag/pike as a form defect.

A Hindu push-up is the opposite kind of movement — the signature of the
exercise IS the hip arc:

    1. Downward Dog  — hips are the HIGHEST point of the body, forming an
       inverted "V" (piked). Arms straight, head hanging down.
    2. The dive       — hips and chest sweep down and forward together,
       skimming low over the floor. Elbows bend to lower the chest.
    3. Upward Dog/Cobra — hips are the LOWEST point, close to the floor,
       back arched, chest and head lifted up. Arms straight again.
    4. Reverse the dive back to Downward Dog to complete one rep.

So the primary signal here is a *hip-elevation arc* (identical formula to
`pushup.py`'s hip-sag/pike alignment check — but here it's the thing we
count, not the thing we penalize), gated by a genuine elbow bend during
the transition (to make sure this is an actual push-up press, not just a
yoga cat/cow flow with stiff arms) and by arm straightness at both peaks
(so partial reps that never fully open the elbows still get flagged).

Floor-stance detection also cannot reuse `pushup.py`'s standing/floor
gate as-is: that gate assumes the torso stays near-horizontal throughout
(true for a flat plank push-up), but Downward Dog deliberately inclines
the torso and lifts the hips well above shoulder height. Reused verbatim,
it would misread a *correct* Downward Dog as "standing" and silently stop
counting — exactly the false-negative failure mode we most need to avoid.
Instead we gate on the width/height bounding-box aspect ratio (which
stays wide across the whole Downdog → dive → Cobra range, since hands and
feet remain planted and spread apart) plus a "hands are down near the
floor" check, both of which hold at every point in the arc.
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    LEFT_WRIST,
    NOSE,
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


# ---- hip-arc thresholds (signed hip deviation from the shoulder->leg line,
# normalized by torso length — negative = hips piked UP above the line
# (Downward Dog), positive = hips sagged DOWN below the line (Cobra)) ----
DOWNDOG_ARC = -0.30   # arc at/below this = confirmed Downward Dog
UPDOG_ARC = 0.26       # arc at/above this = confirmed Cobra / Upward Dog
MIN_ARC_DELTA = 0.42   # total arc travel required for a rep to "count"
MIN_REP_DURATION = 0.5     # seconds — faster than this = bounce, not a rep
MAX_REP_DURATION = 15.0    # seconds — slower than this = stalled, not a rep

# Elbow-angle thresholds (shoulder-elbow-wrist), same geometry as pushup.py
MIN_DIVE_ELBOW_ANGLE = 140.0   # must bend at least this much somewhere in
                               # the dive, or this isn't a real push-up press
PEAK_EXTENSION_ANGLE = 150.0   # arms should be ~straight at both Downdog
                               # and Cobra peaks for good form (flag only)

# "Sink lower" partial-attempt detection (only checked on the Downdog ->
# Cobra leg, mirroring pushup.py's asymmetric partial-rep check)
PARTIAL_BOUNCE_MARGIN = 0.06
PARTIAL_REP_MARGIN = 0.10
PARTIAL_MIN_APPROACH = 0.18

# Head lift in Cobra (secondary / non-blocking quality check)
HEAD_LIFT_MIN = 0.05   # nose should rise at least this much above shoulder
                       # line (normalized by torso length) during Cobra

# -------------------------------------------------------------------------
# Floor-stance detection (see module docstring — cannot reuse pushup.py's)
# -------------------------------------------------------------------------
FLOOR_BBOX_ASPECT_MIN = 1.0     # width/height of visible-landmark bbox
STANDING_BBOX_ASPECT_MAX = 0.65
HANDS_NOT_RAISED_MARGIN = 0.15  # wrist.y must be no higher than
                                # shoulder.y - this*torso_length

STABLE_FLOOR_FRAMES = 5
GRACE_FRAMES = 8

# View-mode classification (shoulder width / torso length) — Hindu push-ups
# are essentially untrackable head-on, since the whole exercise is defined
# by front-to-back depth (the arc) that a front camera collapses to noise.
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


def _assess_floor_stance(
    bbox_aspect: Optional[float],
    l_wrist,
    r_wrist,
    mid_shoulder: Optional[_Point],
    torso_length: float,
) -> tuple[bool, bool]:
    """(is_floor_stance, is_standing) — robust across the WHOLE Downdog ->
    dive -> Cobra arc (see module docstring for why pushup.py's gate would
    misfire on Downward Dog specifically)."""
    if bbox_aspect is None or mid_shoulder is None:
        return False, False

    wrists = [p for p in (l_wrist, r_wrist) if _visible((p,))]
    hands_down = False
    if wrists:
        margin = HANDS_NOT_RAISED_MARGIN * torso_length
        hands_down = any(w.y >= mid_shoulder.y - margin for w in wrists)

    is_floor = bbox_aspect >= FLOOR_BBOX_ASPECT_MIN and hands_down
    is_standing = bbox_aspect <= STANDING_BBOX_ASPECT_MAX
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


class HinduPushupAnalyzer:
    """Stateful Hindu push-up rep counter.

    Rep = one full Downdog -> Cobra -> Downdog cycle, validated by:
      - real arc range (MIN_ARC_DELTA of hip-elevation travel)
      - a genuine elbow bend somewhere in the dive (MIN_DIVE_ELBOW_ANGLE) —
        without this a hip-hinge flow with locked-straight arms could
        otherwise trip the arc thresholds without ever being a push-up
      - sane timing (MIN_REP_DURATION..MAX_REP_DURATION)

    Arm straightness at the two peaks and head lift in Cobra are quality
    checks only — they can mark a rep "needs_improvement" but never block
    it from counting, so a real rep is never silently dropped.
    """

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        # "downdog" = piked/rest position (start & end of a rep)
        # "updog"   = sagged Cobra position (far point of a rep)
        self.stage = "downdog"
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.partial_rep_count = 0

        self.smoothed_arc: Optional[float] = None
        self.last_arc: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None
        self.rep_start_time: Optional[float] = None
        self._rep_arc_acc = 0.0
        self.arc_smooth_alpha = 0.5

        self.session_start_time: Optional[float] = None

        # "Sink lower" partial-attempt detection (Downdog -> Cobra leg only)
        self._attempt_max_arc: Optional[float] = None
        self._attempt_flagged = False

        # Whole-rep quality tracking, reset at the Downdog->Cobra transition
        self._rep_min_elbow: Optional[float] = None
        self._elbow_at_downdog_entry: Optional[float] = None
        self._elbow_at_updog_entry: Optional[float] = None
        self._head_lift_at_updog_entry: Optional[float] = None
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
            "hip_arc": None,
            "smoothed_hip_arc": None,
            "left_elbow_angle": None,
            "right_elbow_angle": None,
            "elbow_angle": None,
            "head_lift": None,
            "arc_velocity": None,
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
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]
        nose = landmarks[NOSE]

        left_arm_ok = _visible((l_shoulder, l_elbow, l_wrist))
        right_arm_ok = _visible((r_shoulder, r_elbow, r_wrist))
        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))

        if not left_arm_ok and not right_arm_ok:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your arms clearly — adjust the camera so your "
                "shoulders, elbows, and wrists are all in frame."
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
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)
        shoulder_width = _dist(l_shoulder, r_shoulder)

        view_mode = _view_mode(shoulder_width, torso_length)
        response["view_mode"] = view_mode

        leg_far = _leg_far_point(l_ankle, r_ankle, l_knee, r_knee)

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

        # ---- camera framing (independent of exercise form) ----
        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        # ---- THE critical check: hands+feet planted, not standing ----
        is_floor, is_standing = _assess_floor_stance(
            bbox_aspect, l_wrist, r_wrist, mid_shoulder, torso_length
        )

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

        # Hindu push-ups are essentially untrackable head-on — the whole
        # signal is a front-to-back arc that a front view collapses to
        # near-zero. Gate counting on side/angled view explicitly so a
        # front-facing camera doesn't silently produce false negatives.
        view_ok = view_mode != "front"
        position_ok = self.ready and view_ok
        response["position_ok"] = position_ok
        response["ready"] = self.ready

        if view_mode == "front":
            position_message = (
                "Turn side-on to the camera — Hindu push-ups need a side "
                "view to track the hip arc accurately."
            )
        elif is_standing:
            position_message = (
                "Get down onto the floor into Downward Dog — hands and "
                "feet planted, hips lifted high — to start counting."
            )
        elif not self.ready:
            position_message = (
                "Get into Downward Dog — hands and feet on the floor, "
                "hips pushed up high — to start counting."
            )
        else:
            position_message = None
        response["position_message"] = position_message

        # ---- elbow angles ----
        left_elbow_angle = (
            _angle_deg(l_shoulder, l_elbow, l_wrist) if left_arm_ok else None
        )
        right_elbow_angle = (
            _angle_deg(r_shoulder, r_elbow, r_wrist) if right_arm_ok else None
        )
        elbow_angles = [a for a in (left_elbow_angle, right_elbow_angle) if a is not None]
        elbow_angle = sum(elbow_angles) / len(elbow_angles)

        # ---- hip arc: signed deviation of the hip from the line joining
        # the shoulder and the far leg point, normalized by torso length.
        # Negative = hips piked above the line (Downward Dog).
        # Positive = hips sagged below the line (Cobra / Upward Dog).
        # (Identical formula to pushup.py's hip-sag/pike check — here it's
        # the primary counted signal instead of a form defect.) ----
        raw_arc = None
        if leg_far is not None:
            dx = leg_far.x - mid_shoulder.x
            if abs(dx) > 0.05:
                frac = (mid_hip.x - mid_shoulder.x) / dx
                expected_hip_y = mid_shoulder.y + frac * (leg_far.y - mid_shoulder.y)
                raw_arc = (mid_hip.y - expected_hip_y) / torso_length

        if raw_arc is None:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your legs clearly — make sure your knees or "
                "ankles are visible in frame."
            )
            return response

        if self.smoothed_arc is None:
            self.smoothed_arc = raw_arc
        else:
            self.smoothed_arc = (
                self.arc_smooth_alpha * raw_arc
                + (1 - self.arc_smooth_alpha) * self.smoothed_arc
            )

        arc_velocity = None
        if self.last_arc is not None and self.last_timestamp_s is not None:
            dt = t - self.last_timestamp_s
            if dt > 0:
                arc_velocity = (self.smoothed_arc - self.last_arc) / dt

        # ---- head lift (secondary quality check, only meaningful with a
        # visible nose and a usable side/angled view) ----
        head_lift = None
        if _visible((nose,)) and view_mode in ("side", "angled"):
            head_lift = (mid_shoulder.y - nose.y) / torso_length

        feedback = framing_message

        # ---- per-frame alignment (live feedback, not rep-blocking) ----
        # NOTE: neither arm-straightness at the two peaks NOR head lift in
        # Cobra is checked here on a loose "currently in this stage" basis.
        # Both the elbow and the head start moving back toward the next
        # position *before* the hip arc has left the peak (that's the
        # mechanism of the exercise — the return dive begins, elbows
        # bending and head dropping, while hips are still sagged low from
        # Cobra) — so a loose check would flag correct, expected movement
        # as a defect for several transit frames. This block is therefore
        # LIVE, INFORMATIONAL ONLY (never feeds the authoritative
        # rep-quality score below) and only lights up while actually
        # sitting at the peak arc value. The scored, authoritative version
        # of each check is a single precise snapshot taken at the exact
        # transition instant — see the rep state machine below.
        alignment_issue = None
        alignment_message = None
        if position_ok:
            if (
                self.stage == "updog"
                and self.smoothed_arc >= UPDOG_ARC
                and head_lift is not None
                and head_lift < HEAD_LIFT_MIN
            ):
                alignment_issue = "head_down_in_cobra"
                alignment_message = (
                    "Lift your head and chest up and look forward in the Cobra position."
                )
        response["alignment_ok"] = alignment_issue is None
        response["alignment_issue"] = alignment_issue

        # ---- rep state machine — only progresses with a confirmed stance ----
        rep_completed = False
        rep_duration = rep_avg_speed = rep_class = rep_form_quality = None
        partial_feedback = None

        if not position_ok:
            if self.rep_start_time is not None:
                self.rep_start_time = None
                self._rep_arc_acc = 0.0
                self._rep_min_elbow = None
                self._current_rep_issues = set()
                if feedback is None:
                    feedback = (
                        "Lost the floor position mid-rep — not counted. "
                        "Reset to Downward Dog and try again."
                    )
            if feedback is None:
                feedback = position_message
        else:
            # ---- "sink lower" partial-attempt detection (Downdog -> Cobra
            # leg only, mirrors pushup.py's asymmetric partial-rep check) ----
            if self.stage == "downdog":
                if (
                    self._attempt_max_arc is None
                    or self.smoothed_arc > self._attempt_max_arc
                ):
                    self._attempt_max_arc = self.smoothed_arc
                elif (
                    not self._attempt_flagged
                    and self._attempt_max_arc is not None
                    and self._attempt_max_arc - self.smoothed_arc > PARTIAL_BOUNCE_MARGIN
                    and self._attempt_max_arc < UPDOG_ARC - PARTIAL_REP_MARGIN
                    and self._attempt_max_arc - DOWNDOG_ARC > PARTIAL_MIN_APPROACH
                ):
                    self._attempt_flagged = True
                    self.partial_rep_count += 1
                    partial_feedback = (
                        "Sink your hips lower into Cobra — you're stopping "
                        "short of the full arch."
                    )

                if self.smoothed_arc < DOWNDOG_ARC + 0.05:
                    self._attempt_max_arc = None
                    self._attempt_flagged = False

            # ---- stage transitions ----
            if self.stage == "downdog" and self.smoothed_arc > UPDOG_ARC:
                self.rep_start_time = t
                self._rep_arc_acc = 0.0
                self._rep_min_elbow = elbow_angle
                self._elbow_at_updog_entry = elbow_angle
                self._head_lift_at_updog_entry = head_lift

            if self._rep_min_elbow is not None:
                self._rep_min_elbow = min(self._rep_min_elbow, elbow_angle)
            if self.last_arc is not None:
                self._rep_arc_acc += abs(self.smoothed_arc - self.last_arc)

            if self.stage == "downdog" and self.smoothed_arc > UPDOG_ARC:
                self.stage = "updog"
                self._current_rep_issues = set()
                if self._elbow_at_updog_entry is not None and (
                    self._elbow_at_updog_entry < PEAK_EXTENSION_ANGLE
                ):
                    self._current_rep_issues.add("not_extended_updog")
                if self._head_lift_at_updog_entry is not None and (
                    self._head_lift_at_updog_entry < HEAD_LIFT_MIN
                ):
                    self._current_rep_issues.add("head_down_in_cobra")
            elif self.stage == "updog" and self.smoothed_arc < DOWNDOG_ARC:
                self.stage = "downdog"
                self._elbow_at_downdog_entry = elbow_angle
                rep_completed = True

            if feedback is None:
                feedback = partial_feedback

            if rep_completed:
                rep_duration = (
                    (t - self.rep_start_time) if self.rep_start_time is not None else None
                )
                if rep_duration and rep_duration > 0:
                    rep_avg_speed = self._rep_arc_acc / rep_duration

                if self._elbow_at_downdog_entry is not None and (
                    self._elbow_at_downdog_entry < PEAK_EXTENSION_ANGLE
                ):
                    self._current_rep_issues.add("not_extended_downdog")

                dive_ok = (
                    self._rep_min_elbow is not None
                    and self._rep_min_elbow <= MIN_DIVE_ELBOW_ANGLE
                )
                if not dive_ok:
                    self._current_rep_issues.add("no_dive_bend")

                valid = (
                    rep_duration is not None
                    and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                    and self._rep_arc_acc >= MIN_ARC_DELTA
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
                            feedback = f"Good full range, nice and controlled ({rep_duration:.2f}s)."
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
                self._rep_arc_acc = 0.0
                self._rep_min_elbow = None
                self._current_rep_issues = set()

        self.last_arc = self.smoothed_arc
        self.last_timestamp_s = t

        if feedback is None and alignment_issue:
            feedback = alignment_message
        if feedback is None and not self.ready:
            feedback = (
                "Get into Downward Dog — hands and feet on the floor, hips "
                "pushed up high — to start counting."
            )
        if feedback is None:
            feedback = "Good form — keep going."

        response.update(
            {
                "hip_arc": raw_arc,
                "smoothed_hip_arc": self.smoothed_arc,
                "left_elbow_angle": left_elbow_angle,
                "right_elbow_angle": right_elbow_angle,
                "elbow_angle": elbow_angle,
                "head_lift": head_lift,
                "arc_velocity": arc_velocity,
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


class HinduPushupSession:
    """Full Hindu push-up session: one shared pose model + one analyzer.

    Same coach-assigned-plan convention as `PushupSession` — the frontend
    supplies `target_reps` / `target_sets` / `set_number` via query params,
    and this class is the sole source of truth for `session_complete` /
    `exercise_complete`.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = HinduPushupAnalyzer(target_reps)
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
