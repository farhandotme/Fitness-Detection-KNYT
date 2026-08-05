"""
Bicycle Crunch tracker — alternating elbow-to-opposite-knee rep counter.

Design
------
Like the Russian twist, this is an alternating-sides exercise, not an
up/down one, so it gets the same three-state `center` / `left` / `right`
phase machine instead of a rep up/down state machine — see
`russian_twist.py`'s module docstring for the fuller rationale, it
applies here unchanged.

Signal
------
A bicycle crunch alternates: right elbow drives toward the left knee
while the left leg extends, then left elbow toward the right knee while
the right leg extends. That's directly, cheaply measurable in 2D from
pretty much any camera angle that has the elbows and knees in frame —
no depth estimate needed anywhere in this one (a deliberate choice after
`russian_twist.py` needed real work to get an accurate 2D-only magnitude;
this exercise doesn't have that problem at all):

    d_R2L = dist(right_elbow, left_knee)  / torso_length
    d_L2R = dist(left_elbow, right_knee)  / torso_length
    crunch_signal = d_L2R - d_R2L

Positive `crunch_signal` = left knee is the one being approached (right
elbow crossing over) → labeled the **"left"** side here. Negative = the
right knee is being approached (left elbow crossing over) → **"right"**.
Both distances are normalized by `torso_length` (shoulder-to-hip
distance) so it's not sensitive to camera zoom/distance.

Unlike the Russian twist's shoulder/hip ratio, this signal needs **no
baseline recalibration at all** — it's already zero-centered by
construction (a symmetric, neutral pose naturally gives `d_R2L ≈ d_L2R`,
so `crunch_signal ≈ 0`), which sidesteps the whole class of bug that
`russian_twist.py` hit (its baseline had to be "which pose counts as
center," and recalibrating that mid-movement was what caused held twists
to silently erode to zero). There's nothing to recalibrate here, so that
failure mode doesn't exist for this exercise.

What *is* reused from that lesson: the enter/exit rotation thresholds
that drive the phase machine are a fraction of a running **envelope** of
how much crossover this specific person/setup/flexibility actually
produces (`_envelope`), not a fixed absolute distance — same reasoning
as the Russian twist's adaptive thresholds, just applied to a normalized
distance instead of a normalized angle. This part of the design carries
over cleanly precisely because it's a peak-follower, not a
recalibrate-toward-current-value baseline — it doesn't have the erosion
bug's failure mode in the first place.

Two counting modes, one event stream
-------------------------------------
Identical convention to the Russian twist: every confirmed center->side
transition (confirmed via the same dwell/hysteresis mechanism as the
phase machine below) is a "side touch." `left_count` /
`right_count` increment per side; `rep_count` increments once every
*second* touch (a left+right pair), so the frontend can show both the
split and the combined total from the same event stream. A repeated
touch on the same side without visiting the other side first counts for
neither — bicycle crunches are inherently alternating, so a non-
alternating "touch" isn't a valid rep by definition, same reasoning as
the Russian twist.

Gates
-----
The only thing that gates counting at all is landmark visibility —
everything else is feedback, never a blocker. This wasn't the first
design: the original version also hard-gated on "hands near head" and
"knees raised to roughly hip height," debounced with a stability streak
the same way the Russian twist gates its seated position. That turned
out to be a real bug, not just an overcautious default — a correct
bicycle crunch has one leg extended low while the other tucks high, so
the *average* knee height swings enormously within a single, perfectly
good rep. A hard gate on that average could use up its grace frames
during totally normal motion and silently flip `ready` false mid-set,
which would stop everything downstream from being counted even though
the person was doing it right. Same reasoning applied to leg
alternation, which used to block a side touch from counting if the
non-crunching leg wasn't extended enough — now it's advisory
(`legs_alternating` / `leg_message` still get computed and surfaced),
but it never withholds a count. The exercise's own alternating-touch
requirement (through the phase machine below) is what actually defines
a valid rep; a secondary form-quality heuristic shouldn't be able to
override that and erase a real one.

  * **Framing** — full body in frame, not too close/far. Feedback only.
  * **Shoulders + hips visible** — the one hard requirement left. They
    anchor `torso_length` (the scale everything else is normalized
    against) and are essentially always visible lying on your back
    facing the camera. Elbows and knees are used for the core signal
    regardless of their own visibility score — they used to be part of
    this hard gate too, and that was still too strict: hands-behind-head
    is an inherently self-occluding pose, so MediaPipe can report low
    elbow confidence even when the person is doing everything right and
    is clearly in frame. A position estimate MediaPipe isn't fully
    confident in is still almost always more useful than refusing to
    count at all.
  * **Hands-near-head / knees-raised** — advisory coaching tips only
    (`base_message`), not a `ready` gate.
  * **Leg alternation** — advisory only (`legs_alternating` /
    `leg_message`), not a counting gate.
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_EAR,
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    LEFT_WRIST,
    NOSE,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_EAR,
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
# Hard requirement — deliberately just these four, not all eight. Elbows
# and knees used to be required here too, and that was still too strict:
# hands-behind-head is an inherently self-occluding pose (elbows point
# back near the head/hair), so MediaPipe can report visibility well
# under any reasonable threshold for the elbows specifically, even when
# the person is doing everything correctly and is clearly visible
# overall. Shoulders and hips anchor `torso_length` (the scale everything
# else is normalized against) and are essentially always visible lying
# on your back facing the camera, so they're the only real hard
# requirement. Elbows/knees are used for the signal regardless of their
# visibility score below — MediaPipe still returns a position estimate
# even when it's not fully confident, and that estimate is almost always
# far more useful than refusing to count at all.
REQUIRED_LANDMARKS = (
    LEFT_SHOULDER,
    RIGHT_SHOULDER,
    LEFT_HIP,
    RIGHT_HIP,
)
CORE_VISIBILITY_MIN = 0.3

ANGLE_SMOOTH_ALPHA = 0.65
STABLE_FRAMES = 2  # consecutive frames required to commit a phase change

# ---- adaptive envelope thresholds (normalized-distance units, not
# degrees — same "fraction of recently-observed range" idea as the
# Russian twist, just applied to crunch_signal instead of an angle) ----
ENVELOPE_DECAY = 0.985
ENVELOPE_MIN = 0.18
ENVELOPE_MAX = 1.3
ENTER_FRACTION = 0.45
EXIT_FRACTION = 0.20
PARTIAL_FRACTION = 0.15
ENTER_FLOOR = 0.10
EXIT_FLOOR = 0.045
PARTIAL_FLOOR = 0.03

# ---- base position gate ----
HANDS_NEAR_HEAD_MAX = 0.75  # wrist-to-ear distance / torso_length
KNEES_RAISED_MARGIN = 0.20  # knees may sit this much below hip height (normalized)

# ---- leg alternation gate (counting gate only) ----
LEG_ALT_MIN_DIFF = 0.12  # extending leg must be at least this much longer (normalized)

# ---- camera framing ----
FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.95
BBOX_TOO_FAR = 0.10


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


def _bbox_points(points: list[_Point]) -> Optional[tuple[float, float, float, float]]:
    if not points:
        return None
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    return min(xs), max(xs), min(ys), max(ys)


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

    box = _bbox_points(points)
    if box is None:
        return None
    min_x, max_x, min_y, max_y = box
    width, height = max_x - min_x, max_y - min_y

    if width > BBOX_TOO_CLOSE or height > BBOX_TOO_CLOSE:
        return (
            "You're too close to the camera — back up so your whole body fits in frame."
        )
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."
    return None


class BicycleCrunchAnalyzer:
    """Stateful bicycle crunch alternating rep counter.

    No rep up/down state machine — same three-state `center` / `left` /
    `right` phase machine as `RussianTwistAnalyzer`, driven by
    `crunch_signal` instead of a rotation angle. See module docstring.
    """

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        # Phase machine
        self.phase = "center"  # "center" | "left" | "right"
        self._candidate_phase = "center"
        self._candidate_streak = 0

        self.smoothed_signal: Optional[float] = None

        # Running envelope of observed |crunch_signal| — thresholds are a
        # fraction of this, not a fixed absolute distance.
        self._envelope = ENVELOPE_MIN

        # Counting
        self.left_count = 0
        self.right_count = 0
        self.rep_count = 0
        self._last_counted_side: Optional[str] = None
        self._touch_count = 0

        # "Cross over further" partial-attempt detection
        self._attempt_peak = 0.0
        self._attempt_flagged = False

        # Base-position streak (kept for potential future use/telemetry —
        # not currently gating anything, see update()).
        self._base_streak = 0
        self.ready = False

        self.session_start_time: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None

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
            "base_ok": False,
            "base_message": None,
            "ready": self.ready,
            "framing_ok": True,
            "framing_message": None,
            "crunch_signal": None,
            "raw_crunch_signal": None,
            "signal_envelope": None,
            "phase": self.phase,
            "left_count": self.left_count,
            "right_count": self.right_count,
            "rep_count": self.rep_count,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "side_completed": False,
            "side_completed_which": None,
            "legs_alternating": True,
            "legs_visible": False,
            "leg_message": None,
            "low_visibility": False,
            "feedback": None,
            "elapsed_time": round(elapsed, 2),
        }

        if landmarks is None:
            response["feedback"] = "No person detected — step into frame."
            return response

        required_ok = all(
            landmarks[i].visibility is not None
            and landmarks[i].visibility > CORE_VISIBILITY_MIN
            for i in REQUIRED_LANDMARKS
        )
        if not required_ok:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your torso clearly — adjust the camera so your "
                "shoulders and hips are both visible."
            )
            return response

        response["pose_detected"] = True

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_elbow, r_elbow = landmarks[LEFT_ELBOW], landmarks[RIGHT_ELBOW]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]
        l_ear, r_ear = landmarks[LEFT_EAR], landmarks[RIGHT_EAR]
        nose = landmarks[NOSE]

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)

        bbox_candidates = [
            _Point(p.x, p.y)
            for p in (
                l_shoulder,
                r_shoulder,
                l_hip,
                r_hip,
                l_elbow,
                r_elbow,
                l_knee,
                r_knee,
                l_ankle,
                r_ankle,
            )
            if _visible((p,))
        ]
        framing_message = _framing_feedback(bbox_candidates)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        # ---- base position gate ----
        # Only landmark visibility gates `ready` now. Hands-near-head and
        # knees-raised are useful coaching signals but were originally
        # wired as hard blockers using a streak/grace debounce — and that
        # was a mistake: real bicycle-crunch form has one leg extended low
        # while the other tucks high, so the *average* knee height swings
        # a lot within a single, perfectly correct rep. A hard gate on
        # that average could flip `ready` false mid-set (using up its
        # grace frames during a normal extension) and silently stop
        # everything downstream from being counted — the same class of
        # bug the Russian twist's seated-lean gate had. So these are
        # advisory feedback only now, never a block.
        head_ref = None
        if _visible((nose,)):
            head_ref = nose
        elif _visible((l_ear, r_ear)):
            head_ref = _midpoint(l_ear, r_ear)

        hands_near_head = True  # best-effort: don't advise on what we can't see
        if head_ref is not None and _visible((l_wrist, r_wrist)):
            l_hand_dist = _dist(l_wrist, head_ref) / torso_length
            r_hand_dist = _dist(r_wrist, head_ref) / torso_length
            hands_near_head = min(l_hand_dist, r_hand_dist) <= HANDS_NEAR_HEAD_MAX

        knees_raised = (
            mid_hip.y - _midpoint(l_knee, r_knee).y
        ) > -KNEES_RAISED_MARGIN * torso_length

        if not knees_raised:
            base_advisory_message = "Lift your knees toward your chest."
        elif not hands_near_head:
            base_advisory_message = "Bring your hands up behind your head."
        else:
            base_advisory_message = None

        # `ready` only reflects "can I trust the signal at all" — i.e. the
        # required landmarks have been visible for a few consecutive
        # frames (already true here, since `required_ok` gated earlier in
        # this function on every single frame). There's nothing left to
        # debounce; if we got this far, the landmarks are visible now.
        self._base_streak += 1
        self.ready = True

        base_ok = self.ready
        response["base_ok"] = base_ok
        response["ready"] = self.ready
        response["base_message"] = base_advisory_message

        # ---- core signal: elbow-to-opposite-knee distance difference ----
        d_r2l = _dist(r_elbow, l_knee) / torso_length
        d_l2r = _dist(l_elbow, r_knee) / torso_length
        raw_signal = d_l2r - d_r2l  # positive = left side (right elbow -> left knee)

        if self.smoothed_signal is None:
            self.smoothed_signal = raw_signal
        else:
            self.smoothed_signal = (
                ANGLE_SMOOTH_ALPHA * raw_signal
                + (1 - ANGLE_SMOOTH_ALPHA) * self.smoothed_signal
            )
        response["raw_crunch_signal"] = round(raw_signal, 3)
        response["crunch_signal"] = round(self.smoothed_signal, 3)

        # ---- adaptive envelope ----
        self._envelope = max(abs(self.smoothed_signal), self._envelope * ENVELOPE_DECAY)
        self._envelope = max(ENVELOPE_MIN, min(ENVELOPE_MAX, self._envelope))
        response["signal_envelope"] = round(self._envelope, 3)

        enter = max(ENTER_FLOOR, ENTER_FRACTION * self._envelope)
        exit_ = max(EXIT_FLOOR, EXIT_FRACTION * self._envelope)
        partial = max(PARTIAL_FLOOR, PARTIAL_FRACTION * self._envelope)

        # ---- leg alternation (counting gate only) ----
        legs_visible = _visible((l_ankle, r_ankle))
        legs_alternating = True
        leg_message = None
        if legs_visible:
            l_leg_ext = _dist(l_hip, l_ankle) / torso_length
            r_leg_ext = _dist(r_hip, r_ankle) / torso_length
        else:
            l_leg_ext = r_leg_ext = None
        response["legs_visible"] = legs_visible

        feedback = framing_message

        # `base_ok` is always true here (see gate above — required
        # landmarks were already confirmed visible earlier in this
        # function, which is the only thing `ready` reflects now), so
        # there is no separate "not ready yet" branch to fall into.
        sig = self.smoothed_signal

        # ---- hysteresis phase classification ----
        if self.phase == "center":
            if sig >= enter:
                target_phase = "left"
            elif sig <= -enter:
                target_phase = "right"
            else:
                target_phase = "center"
        else:
            if abs(sig) <= exit_:
                target_phase = "center"
            else:
                target_phase = self.phase

        if target_phase == self._candidate_phase:
            self._candidate_streak += 1
        else:
            self._candidate_phase = target_phase
            self._candidate_streak = 1

        phase_changed = False
        if (
            self._candidate_streak >= STABLE_FRAMES
            and self._candidate_phase != self.phase
        ):
            self.phase = self._candidate_phase
            phase_changed = True

            if self.phase in ("left", "right"):
                side = self.phase
                # "left" = right elbow -> left knee, so the RIGHT leg is
                # the one that should be extending (pedaling out) while
                # the LEFT leg stays tucked; and vice versa for "right".
                # This is advisory only (see comment above) — a rep
                # still counts even with imperfect leg form, since the
                # elbow-to-knee crossover itself is what actually
                # defines the rep.
                extending_leg, crunching_leg = (
                    (r_leg_ext, l_leg_ext) if side == "left" else (l_leg_ext, r_leg_ext)
                )
                if legs_visible:
                    legs_alternating = (
                        extending_leg - crunching_leg
                    ) >= LEG_ALT_MIN_DIFF
                    leg_message = (
                        None
                        if legs_alternating
                        else ("Try extending your other leg out further like pedaling.")
                    )
                response["legs_alternating"] = legs_alternating
                response["leg_message"] = leg_message

                # A timing-based "too fast" rejection used to live here,
                # but MIN_TOUCH_DURATION (0.10s) sits right at the
                # theoretical minimum the dwell mechanism above already
                # takes (STABLE_FRAMES * one frame interval — e.g. 3 *
                # ~33ms = 99ms at 30fps), so it was rejecting genuinely-
                # paced reps essentially at random depending on rounding,
                # not because anyone actually moved implausibly fast. The
                # dwell requirement already filters real jitter/glitches;
                # this check added no protection beyond that and only
                # caused missed reps, so it's gone rather than re-tuned.

                if side == self._last_counted_side:
                    feedback = "Switch to the other side to keep the rep going."
                else:
                    if side == "left":
                        self.left_count += 1
                    else:
                        self.right_count += 1
                    response["side_completed"] = True
                    response["side_completed_which"] = side

                    self._touch_count += 1
                    if self._touch_count % 2 == 0:
                        self.rep_count += 1
                        response["rep_completed"] = True
                        feedback = f"Rep {self.rep_count} — nice, keep pedaling."
                    else:
                        feedback = (
                            f"{side.capitalize()} side — now switch to the other side."
                        )

                    self._last_counted_side = side

            self._attempt_peak = 0.0
            self._attempt_flagged = False

        # ---- "Cross over further" partial-attempt detection ----
        if not phase_changed and self.phase == "center":
            if abs(sig) > abs(self._attempt_peak):
                self._attempt_peak = sig
            elif (
                not self._attempt_flagged
                and abs(self._attempt_peak) >= partial
                and abs(self._attempt_peak) < enter
                and abs(sig) < abs(self._attempt_peak) - exit_ / 2
            ):
                self._attempt_flagged = True
                direction = "left" if self._attempt_peak > 0 else "right"
                if feedback is None:
                    feedback = f"Cross over further to the {direction}."

            if abs(sig) < exit_ / 2:
                self._attempt_peak = 0.0
                self._attempt_flagged = False

        response["phase"] = self.phase
        # Refresh cumulative counters from current state — they were
        # populated at the top of this function before this frame's
        # possible increment, so re-assigning here (rather than relying
        # on the stale top-of-function values) keeps `side_completed` /
        # `rep_completed` and the counts they describe consistent within
        # the same message instead of the count trailing by one frame.
        response["left_count"] = self.left_count
        response["right_count"] = self.right_count
        response["rep_count"] = self.rep_count

        if feedback is None:
            feedback = "Keep pedaling — elbow to the opposite knee."

        response["feedback"] = feedback
        response["session_complete"] = self._is_complete()
        self.last_timestamp_s = t
        return response


class BicycleCrunchSession:
    """Full bicycle crunch session: one shared pose model + one analyzer.

    Same convention as `RussianTwistSession` / `PushupSession`:
    `target_reps` / `target_sets` / `set_number` are the coach-assigned
    plan, supplied by the caller from query params. `session_complete` /
    `exercise_complete` are computed here, not on the frontend.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = BicycleCrunchAnalyzer(target_reps)
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
