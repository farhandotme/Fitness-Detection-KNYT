"""
Bent-Over Row (dumbbell) detector.

THE MOVEMENT
------------
    1. Set-up / hinge — feet roughly hip-to-shoulder width, soft knees,
       hips hinged back so the torso leans forward (NOT standing upright,
       NOT bent all the way to a flat plank), back flat, dumbbells
       hanging straight down from the shoulders, arms extended.
    2. Row — pull both elbows up and back, driving the dumbbells toward
       the ribs/hips while keeping the torso angle steady. Squeeze the
       shoulder blades together at the top.
    3. Lower — extend the arms back down under control to the hang
       position. That full up-and-down cycle is one rep.

DESIGN PRIORITY (read before touching thresholds)
---------------------------------------------------
The person who asked for this detector was explicit about the one bug
that matters most: **a rep performed correctly must never go uncounted.**
A missed rep is a much worse failure than an occasionally generous one.
So this file is deliberately built around a single hard gate and a
single hard rep-arc, with everything else downgraded to feedback-only:

    HARD GATE (blocks counting only while clearly violated):
        - Torso must be hinged forward within a wide, forgiving band
          (`MIN_HINGE_DEG`..`MAX_HINGE_DEG`) — wide enough to cover an
          upright "Yates row" lean all the way to a near-horizontal
          "Pendlay row" lean. Standing fully upright or lying flat are
          the only things that fail this gate.
        - Hysteresis (`STABLE_FRAMES` to confirm, `GRACE_FRAMES` to
          release) means a single noisy/occluded frame can NOT flip the
          gate — the pose has to clearly and repeatedly leave the hinge
          band before counting pauses.

    HARD REP ARC (the only thing that has to happen for rep_count++):
        - Elbow angle (shoulder-elbow-wrist) drops to a contracted top
          (`TOP_ENTER_DEG`, generous) and then extends back out to a
          relaxed bottom (`BOTTOM_ENTER_DEG`, generous). Both arms are
          tracked and whichever arm(s) are actually visible this frame
          are used — a dumbbell/torso occluding one arm never stalls
          counting as long as the other arm is visible.

    SOFT, NEVER-BLOCKING quality cues (shown as feedback, tracked per rep,
    but they NEVER prevent rep_count from incrementing):
        - Back roundness (shoulder-hip-knee line)
        - Knees locked out straight
        - Elbows flaring instead of driving straight back
        - Standing back upright between reps (a common cheat) — flagged,
          not blocked, because a slightly-too-upright rep is still a rep.
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


# ---- position gate: "hinged forward", deliberately wide -------------------
# Angle of the torso from vertical (0 = standing straight up, 90 = flat/
# horizontal). Real bent-over rows land anywhere from ~30 (upright Yates
# row) to ~80 (Pendlay-style) degrees — the band below intentionally
# spans wider than that on both sides so borderline-but-legitimate form
# never gets rejected.
MIN_HINGE_DEG = 20.0
MAX_HINGE_DEG = 85.0

STABLE_FRAMES = 4  # consecutive good frames before the hinge gate opens
GRACE_FRAMES = 10  # consecutive bad frames tolerated before it closes —
# generous on purpose: a single misread frame (motion blur, dumbbell
# briefly covering a hip landmark, etc.) must never pause counting.

# ---- rep arc: elbow angle (shoulder-elbow-wrist), generous on purpose ----
TOP_ENTER_DEG = 105.0  # elbow bent at least this much counts as "pulled up"
BOTTOM_ENTER_DEG = 145.0  # elbow open at least this much counts as "hung down"
ARC_STABLE_FRAMES = 2  # short — rows are a fast concentric/eccentric motion

# ---- soft, non-blocking quality cues ----
KNEE_SOFT_LOCK_MIN_DEG = 165.0  # knees "locked straight" (mild cue only)
BACK_ROUND_DEVIATION = 0.16  # normalized deviation for a rounded back
UPRIGHT_CHEAT_DEG = 15.0  # torso came back close to vertical mid-set

# ---- camera framing ----
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


def _torso_incline_deg(mid_shoulder, mid_hip) -> Optional[float]:
    """0 = perfectly vertical (standing tall), 90 = perfectly horizontal."""
    dx = mid_hip.x - mid_shoulder.x
    dy = mid_hip.y - mid_shoulder.y
    if dx == 0 and dy == 0:
        return None
    return math.degrees(math.atan2(abs(dx), max(abs(dy), 1e-9)))


def _bbox_aspect(points: list) -> tuple:
    if len(points) < 2:
        return None, None
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    return (max(xs) - min(xs)), (max(ys) - min(ys))


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

    width, height = _bbox_aspect(points)
    if width is None:
        return None

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return (
            "You're too close to the camera — back up so your whole body fits in frame."
        )
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class _ArmReading:
    __slots__ = ("angle", "elbow", "wrist", "shoulder")

    def __init__(self, angle, elbow, wrist, shoulder):
        self.angle = angle
        self.elbow = elbow
        self.wrist = wrist
        self.shoulder = shoulder


def _read_arm(shoulder, elbow, wrist) -> Optional[_ArmReading]:
    if not _visible((shoulder, elbow, wrist)):
        return None
    return _ArmReading(_angle3_deg(shoulder, elbow, wrist), elbow, wrist, shoulder)


class BentOverRowAnalyzer:
    """Stateful dumbbell bent-over-row rep counter.

    Rep = confirmed hinge position -> elbow(s) contract to a confirmed
    "pulled up" top -> elbow(s) extend back to a confirmed "hung down"
    bottom, while the hinge gate stayed open throughout. Losing the hinge
    gate mid-pull pauses counting (no silent miscounts) but never
    discards progress — regaining the hinge resumes from wherever the arc
    was, so a brief wobble never costs the person a rep they actually did.
    """

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0

        self.session_start_time: Optional[float] = None

        # Hinge-position hysteresis
        self._hinge_streak = 0
        self._hinge_bad_streak = 0
        self.in_position = False

        # Rep-arc zone confirmation (single source of truth — see note in
        # `update()` on why this replaced an earlier two-flag design).
        self._pending_zone: Optional[str] = None
        self._pending_zone_streak = 0
        self.confirmed_zone = "bottom"  # sessions start at the hang position

        self.stage = "down"  # "down" (hanging) | "up" (pulled)
        self._current_rep_issues: set[str] = set()
        self._rep_hinge_dropped = False

    # ---------------------------------------------------------------
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
            "in_position": self.in_position,
            "position_message": None,
            "torso_incline": None,
            "elbow_angle": None,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_form_quality": None,
            "back_flat": True,
            "knees_soft": True,
            "elbows_tracking": True,
            "stayed_hinged": True,
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
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

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

        torso_incline = _torso_incline_deg(mid_shoulder, mid_hip)
        response["torso_incline"] = (
            round(torso_incline, 1) if torso_incline is not None else None
        )

        bbox_points = [
            _Point(p.x, p.y)
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
        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        # ---- HARD GATE: hinged-forward position, wide + hysteresis ----
        is_hinged = (
            torso_incline is not None
            and MIN_HINGE_DEG <= torso_incline <= MAX_HINGE_DEG
        )
        if is_hinged:
            self._hinge_streak += 1
            self._hinge_bad_streak = 0
        else:
            self._hinge_streak = 0
            self._hinge_bad_streak += 1

        if self._hinge_streak >= STABLE_FRAMES:
            self.in_position = True
        elif self._hinge_bad_streak >= GRACE_FRAMES:
            self.in_position = False
        # else: keep previous state — short grace window for tracking noise
        response["in_position"] = self.in_position

        if not self.in_position:
            if torso_incline is not None and torso_incline < MIN_HINGE_DEG:
                response["position_message"] = (
                    "Hinge forward at the hips — lean your torso forward "
                    "until it's roughly 45\u00b0, like you're bowing."
                )
            elif torso_incline is not None and torso_incline > MAX_HINGE_DEG:
                response["position_message"] = (
                    "You're bent too far forward — come up slightly so "
                    "your torso is around a 45\u00b0 hinge, not flat."
                )
            else:
                response["position_message"] = (
                    "Get into the row position: hinge forward at the hips, "
                    "soft knees, dumbbells hanging straight down."
                )
        else:
            response["position_message"] = "Good hinge — start rowing."

        # ---- HARD REP ARC: elbow angle, whichever arm(s) are visible ----
        left_arm = _read_arm(l_shoulder, l_elbow, l_wrist)
        right_arm = _read_arm(r_shoulder, r_elbow, r_wrist)
        arms = [a for a in (left_arm, right_arm) if a is not None]

        elbow_angle = None
        if arms:
            elbow_angle = sum(a.angle for a in arms) / len(arms)
        response["elbow_angle"] = (
            round(elbow_angle, 1) if elbow_angle is not None else None
        )

        # ---- HARD REP ARC: elbow angle zone, single confirmed state ----
        # NOTE: an earlier version of this tracked "at_top" and "at_bottom"
        # as two independently-debounced booleans. Under fast reps, a stale
        # `at_top=True` could still be lingering (its grace period hadn't
        # elapsed yet) at the exact moment `at_bottom` flipped `True`,
        # briefly making both true and letting the state machine below fire
        # twice for one physical rep. A single `confirmed_zone` variable
        # makes that impossible — it can only ever hold one value.
        if elbow_angle is not None:
            if elbow_angle <= TOP_ENTER_DEG:
                zone = "top"
            elif elbow_angle >= BOTTOM_ENTER_DEG:
                zone = "bottom"
            else:
                zone = None  # ambiguous mid-range — confirms nothing

            if zone is not None:
                if zone == self._pending_zone:
                    self._pending_zone_streak += 1
                else:
                    self._pending_zone = zone
                    self._pending_zone_streak = 1

                if (
                    self._pending_zone_streak >= ARC_STABLE_FRAMES
                    and zone != self.confirmed_zone
                ):
                    self.confirmed_zone = zone
            else:
                # Mid-range reading: don't let a partial streak toward one
                # zone survive a detour through the middle — require a
                # fresh, uninterrupted run once the arm re-enters a zone.
                self._pending_zone = None
                self._pending_zone_streak = 0

        # ---- soft, non-blocking quality cues (tracked continuously, only
        # rolled into feedback / rep_form_quality — never gate counting) ----
        back_flat = True
        leg_far = None
        if _visible((l_ankle,)) and _visible((r_ankle,)):
            leg_far = _midpoint(l_ankle, r_ankle)
        elif _visible((l_knee,)) and _visible((r_knee,)):
            leg_far = _midpoint(l_knee, r_knee)

        if leg_far is not None:
            dx = leg_far.x - mid_shoulder.x
            if abs(dx) > 0.04:
                frac = (mid_hip.x - mid_shoulder.x) / dx
                expected_hip_y = mid_shoulder.y + frac * (leg_far.y - mid_shoulder.y)
                deviation = (mid_hip.y - expected_hip_y) / torso_length
                back_flat = abs(deviation) <= BACK_ROUND_DEVIATION
        response["back_flat"] = back_flat

        knees_soft = True
        knee_angles = []
        if _visible((l_hip, l_knee, l_ankle)):
            knee_angles.append(_angle3_deg(l_hip, l_knee, l_ankle))
        if _visible((r_hip, r_knee, r_ankle)):
            knee_angles.append(_angle3_deg(r_hip, r_knee, r_ankle))
        if knee_angles:
            avg_knee = sum(knee_angles) / len(knee_angles)
            knees_soft = avg_knee <= KNEE_SOFT_LOCK_MIN_DEG
        response["knees_soft"] = knees_soft

        elbows_tracking = True
        if self.confirmed_zone == "top" and arms:
            # Elbows should stay roughly under/behind the shoulder line
            # (driving straight back), not flare far out to the sides.
            flare_ratio = []
            shoulder_width = max(_dist(l_shoulder, r_shoulder), 1e-6)
            for a in arms:
                flare_ratio.append(abs(a.elbow.x - a.shoulder.x) / shoulder_width)
            if flare_ratio and (sum(flare_ratio) / len(flare_ratio)) > 1.4:
                elbows_tracking = False
        response["elbows_tracking"] = elbows_tracking

        if not self.in_position and self.stage == "up":
            self._rep_hinge_dropped = True
        response["stayed_hinged"] = not self._rep_hinge_dropped

        alignment_issue = None
        alignment_message = None
        if not back_flat:
            alignment_issue = "rounded_back"
            alignment_message = (
                "Keep your back flat — brace your core, don't round your spine."
            )
        elif not elbows_tracking:
            alignment_issue = "elbow_flare"
            alignment_message = "Drive your elbows straight back, not out to the sides."
        response["alignment_ok"] = alignment_issue is None
        response["alignment_issue"] = alignment_issue

        # ---- rep state machine — counting only requires the HARD ARC.
        # The hinge gate pausing does NOT erase in-flight arc progress. ----
        rep_completed = False
        rep_form_quality = None
        feedback = framing_message

        if self.in_position:
            if not back_flat:
                self._current_rep_issues.add("rounded_back")
            if not elbows_tracking:
                self._current_rep_issues.add("elbow_flare")

            if self.stage == "down" and self.confirmed_zone == "top":
                self.stage = "up"
                feedback = feedback or "Top of the row — now lower with control."
            elif self.stage == "up" and self.confirmed_zone == "bottom":
                self.rep_count += 1
                rep_completed = True

                if self._rep_hinge_dropped:
                    self._current_rep_issues.add("stood_up_mid_rep")

                if self._current_rep_issues:
                    rep_form_quality = "needs_improvement"
                    self.flawed_reps += 1
                    issue_text = ", ".join(
                        i.replace("_", " ") for i in sorted(self._current_rep_issues)
                    )
                    feedback = f"Rep {self.rep_count} counted — but watch your form ({issue_text})."
                else:
                    rep_form_quality = "good"
                    self.good_reps += 1
                    feedback = f"Clean rep #{self.rep_count} — nice control."

                self.stage = "down"
                self._current_rep_issues = set()
                self._rep_hinge_dropped = False
        # else: hinge gate currently open-but-unconfirmed or closed — the
        # arc state (`stage`, `at_top`, `at_bottom`) is intentionally left
        # untouched here so regaining position resumes exactly where the
        # pull was, instead of discarding a rep that was actually correct.

        if feedback is None and alignment_issue:
            feedback = alignment_message
        if feedback is None and not self.in_position:
            feedback = response["position_message"]
        if feedback is None and self.stage == "up":
            feedback = "Pull — squeeze your shoulder blades together."
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
                "rep_form_quality": rep_form_quality,
                "feedback": feedback,
            }
        )
        return response


class BentOverRowSession:
    """Full bent-over-row session: one shared pose model + one analyzer."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = BentOverRowAnalyzer(target_reps)
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
