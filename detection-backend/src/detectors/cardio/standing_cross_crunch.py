"""
Standing Cross Crunch rep counter.

What this move looks like
--------------------------
Standing tall, hands clasped/interlocked behind the head, elbows out wide.
The user drives one knee up toward waist height while rotating the torso
so the *opposite* elbow travels down and across the body toward that
raised knee (a standing version of a bicycle crunch), then resets back to
standing before driving the other knee up. One rep = one knee-raise +
crunch on one side. A "set" of this exercise is inherently alternating —
left, right, left, right — so this analyzer enforces that ordering
explicitly instead of just counting knee raises.

Design (mirrors `PushupAnalyzer` / `SidePlankAnalyzer`)
--------------------------------------------------------
* A single scalar per leg — the normalized vertical gap between hip and
  knee — drives the rep state machine, exactly like elbow angle drives
  push-ups. Small gap = knee raised near hip height ("up"); large gap =
  standing tall ("down"). Hysteresis bands (`KNEE_UP_MAX_GAP` /
  `KNEE_DOWN_MIN_GAP`) stop noisy tracking from flickering the stage.
* A hard **position gate** — hands must stay near the head — must hold
  for the rep to count at all, the same way push-ups require a verified
  floor plank and side planks require a verified straight body line. If
  the person drops their hands mid-attempt, that attempt is discarded,
  never counted, exactly like a broken plank resets the rep in progress.
* Which knee is raised is only ever attributed to a rep if it is
  *unambiguously* the raised one (a clear gap margin over the other leg,
  `MIN_SIDE_DOMINANCE`) — this stops a two-footed jump or a shifting
  weight from being misread as a rep.
* **Alternation is enforced, not assumed.** The user may start on
  whichever side they like — the first completed rep sets the expected
  next side. Every rep after that must land on the side that isn't the
  last one counted. A same-side repeat (e.g. right, right) is a real,
  measurable rep of knee-raise + crunch, but it breaks the required
  left-right-left-right cadence for this exercise, so it is **not**
  added to `rep_count` — it's surfaced as `alternation_broken` with
  feedback telling the user which side to switch to, and it does not
  otherwise disturb the counted history (`last_completed_side` /
  `expected_next_side` are left as they were).
* Whether the torso actually rotated enough to bring the opposite elbow
  across to the knee (as opposed to just a straight-up knee raise with no
  twist) is graded as rep *quality* (`good` vs `needs_improvement`),
  the same tier `hip_sag` / `hip_pike` sit at for push-ups: it does not
  block the rep from counting, since the primary, unambiguous signal for
  "a rep happened on this side" is the knee raise + return, and refusing
  to count a real rep over a soft form nuance is exactly the kind of
  false negative this detector is built to avoid.
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
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)

# ---- hands-behind-head gate (wrist -> ear distance, normalized by torso) ----
# Hysteresis: once gated "ok", the wrist has to drift further away before we
# call it broken; once broken, it has to come back noticeably closer before
# we trust it again. Stops a borderline distance flickering every frame.
HANDS_HEAD_BROKEN_DIST = 0.75
HANDS_HEAD_RESUME_DIST = 0.55

# ---- knee-raise gate: (knee.y - hip.y) / torso_length ----
# In image coordinates y grows downward, so standing-tall has a large
# positive gap (knee well below hip) and a raised-to-hip-height knee has a
# gap near/at zero. Same hysteresis-band convention as DOWN_ANGLE/UP_ANGLE
# in the push-up analyzer.
KNEE_UP_MAX_GAP = 0.32  # knee has risen to roughly hip height or above
KNEE_DOWN_MIN_GAP = 0.70  # back down to standing before the rep resets
MIN_SIDE_DOMINANCE = 0.14  # how much lower the *other* knee's gap must be

# Standing (non-raised) leg should stay reasonably straight — otherwise this
# reads more like a squat than a standing knee raise. Soft gate: skipped
# entirely if the far leg isn't reliably visible, rather than blocking the
# rep on a tracking gap.
STANCE_LEG_STRAIGHT_MIN_DEG = 135.0

# ---- crunch/cross quality: opposite-elbow-to-raised-knee distance ----
# normalized by torso length. Small = elbow travelled across to meet the
# knee (a real twist happened). This only affects rep *quality*, never
# whether the rep counts.
CROSS_GOOD_MAX = 0.75

MIN_REP_DURATION = 0.25  # seconds — faster than this reads as bounce/momentum
MAX_REP_DURATION = 6.0  # seconds — slower than this reads as a stall, not a rep

STABLE_FRAMES = 5  # consecutive good frames before counting turns on
GRACE_FRAMES = 8  # consecutive bad frames tolerated before counting turns off

# Camera framing (full body, standing — tall bounding box expected)
FRAME_EDGE_MARGIN = 0.03
BBOX_HEIGHT_TOO_CLOSE = 0.98
BBOX_HEIGHT_TOO_FAR = 0.35


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


def _framing_feedback(points: list[_Point]) -> Optional[str]:
    """Standing full-body framing check — the whole body, head to feet,
    needs to be visible for the knee-height math to mean anything."""
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — step back so your whole body, "
                "head to feet, is visible."
            )

    if len(points) < 4:
        return None

    ys = [p.y for p in points]
    height = max(ys) - min(ys)

    if height > BBOX_HEIGHT_TOO_CLOSE:
        return "You're too close to the camera — step back so your whole body fits in frame."
    if height < BBOX_HEIGHT_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


def _other(side: str) -> str:
    return "right" if side == "left" else "left"


class StandingCrossCrunchAnalyzer:
    """Stateful standing-cross-crunch rep counter with enforced
    left/right alternation."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        # Rep state machine — one shared stage, not per-leg, since only
        # one knee is ever legitimately raised at a time.
        self.stage = "down"  # "down" = standing tall; "up" = one knee raised
        self.active_side: Optional[str] = None  # which side is mid-rep

        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.alternation_breaks = 0

        # Alternation bookkeeping
        self.last_completed_side: Optional[str] = None
        self.expected_next_side: Optional[str] = None

        self.rep_start_time: Optional[float] = None
        self._min_cross_dist: Optional[float] = None
        self.last_timestamp_s: Optional[float] = None
        self.session_start_time: Optional[float] = None

        # Hands-behind-head gate, with its own hysteresis state
        self._hands_ok_state = False

        # Position gating (hands-behind-head + framing), same
        # streak-based debounce as the push-up floor-position gate.
        self._good_streak = 0
        self._bad_streak = 0
        self.ready = False

    # ---------------------------------------------------------------
    def _classify_tempo(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        if duration >= 2.2:
            return "too_slow"
        if duration >= 1.2:
            return "slow"
        if duration >= 0.5:
            return "good"
        if duration >= 0.25:
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
            "hands_ok": self._hands_ok_state,
            "stage": self.stage,
            "current_side": self.active_side,
            "last_completed_side": self.last_completed_side,
            "expected_next_side": self.expected_next_side,
            "left_knee_gap": None,
            "right_knee_gap": None,
            "cross_distance": None,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "alternation_breaks": self.alternation_breaks,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_side": None,
            "rep_duration": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "alternation_broken": False,
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
        l_ear, r_ear = landmarks[LEFT_EAR], landmarks[RIGHT_EAR]
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

        # ---- hands-behind-head check (each wrist vs. its own-side ear,
        # falling back to nose if an ear isn't tracked reliably) ----
        def _head_ref(ear, wrist_visible_pair):
            if _visible((ear,)):
                return ear
            return nose if _visible((nose,)) else None

        l_head_ref = _head_ref(l_ear, (l_wrist,))
        r_head_ref = _head_ref(r_ear, (r_wrist,))

        l_wrist_ok = _visible((l_wrist,)) and l_head_ref is not None
        r_wrist_ok = _visible((r_wrist,)) and r_head_ref is not None

        l_hand_dist = _dist(l_wrist, l_head_ref) / torso_length if l_wrist_ok else None
        r_hand_dist = _dist(r_wrist, r_head_ref) / torso_length if r_wrist_ok else None

        hand_dists = [d for d in (l_hand_dist, r_hand_dist) if d is not None]
        hands_visible = len(hand_dists) > 0

        if hands_visible:
            worst = max(hand_dists)
            if self._hands_ok_state:
                hands_ok_now = worst < HANDS_HEAD_BROKEN_DIST
            else:
                hands_ok_now = worst < HANDS_HEAD_RESUME_DIST
        else:
            hands_ok_now = False
        self._hands_ok_state = hands_ok_now
        response["hands_ok"] = hands_ok_now

        # ---- camera framing ----
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
        framing_message = _framing_feedback(bbox_points)
        response["framing_ok"] = framing_message is None
        response["framing_message"] = framing_message

        # ---- combined position gate, debounced like the push-up floor gate ----
        position_good_this_frame = hands_ok_now and framing_message is None
        if position_good_this_frame:
            self._good_streak += 1
            self._bad_streak = 0
        else:
            self._good_streak = 0
            self._bad_streak += 1

        if self._good_streak >= STABLE_FRAMES:
            self.ready = True
        elif self._bad_streak >= GRACE_FRAMES:
            self.ready = False

        position_ok = self.ready
        response["position_ok"] = position_ok
        response["ready"] = self.ready

        if not hands_visible:
            position_message = (
                "Can't see your hands — clasp them behind your head, "
                "elbows out, and make sure your arms are in frame."
            )
        elif not hands_ok_now:
            position_message = (
                "Keep your hands behind your head throughout the move — "
                "don't let them drop."
            )
        elif framing_message:
            position_message = framing_message
        else:
            position_message = None
        response["position_message"] = position_message

        # ---- knee-height gaps (drive the rep state machine) ----
        l_knee_gap = (
            (l_knee.y - l_hip.y) / torso_length if _visible((l_knee,)) else None
        )
        r_knee_gap = (
            (r_knee.y - r_hip.y) / torso_length if _visible((r_knee,)) else None
        )
        response["left_knee_gap"] = (
            round(l_knee_gap, 3) if l_knee_gap is not None else None
        )
        response["right_knee_gap"] = (
            round(r_knee_gap, 3) if r_knee_gap is not None else None
        )

        # ---- which side (if any) is unambiguously raised this frame ----
        raised_side = None
        if l_knee_gap is not None and r_knee_gap is not None:
            if (
                l_knee_gap <= KNEE_UP_MAX_GAP
                and (r_knee_gap - l_knee_gap) >= MIN_SIDE_DOMINANCE
            ):
                raised_side = "left"
            elif (
                r_knee_gap <= KNEE_UP_MAX_GAP
                and (l_knee_gap - r_knee_gap) >= MIN_SIDE_DOMINANCE
            ):
                raised_side = "right"

        # ---- crunch/cross distance for whichever side is currently active ----
        cross_distance = None
        if self.active_side == "left" and _visible((r_elbow,)):
            cross_distance = _dist(r_elbow, l_knee) / torso_length
        elif self.active_side == "right" and _visible((l_elbow,)):
            cross_distance = _dist(l_elbow, r_knee) / torso_length
        response["cross_distance"] = (
            round(cross_distance, 3) if cross_distance is not None else None
        )

        feedback = position_message
        rep_completed = False
        rep_side = None
        rep_duration = rep_class = rep_form_quality = None
        alternation_broken = False

        if not position_ok:
            if self.stage == "up":
                # Position broke mid-rep — the attempt is discarded, exactly
                # like a broken plank/floor position resets an in-progress
                # push-up rep. Nothing is counted for it.
                self.stage = "down"
                self.active_side = None
                self.rep_start_time = None
                self._min_cross_dist = None
                if feedback is None:
                    feedback = (
                        "Lost position mid-rep — not counted. Reset to "
                        "standing and try again."
                    )
            if feedback is None:
                feedback = position_message
        else:
            if self.stage == "down":
                if raised_side is not None:
                    self.stage = "up"
                    self.active_side = raised_side
                    self.rep_start_time = t
                    self._min_cross_dist = cross_distance
                elif (
                    l_knee_gap is not None
                    and r_knee_gap is not None
                    and min(l_knee_gap, r_knee_gap) < KNEE_DOWN_MIN_GAP
                    and feedback is None
                ):
                    feedback = (
                        "Lift your knee higher and rotate your elbow across "
                        "to meet it."
                    )
            elif self.stage == "up":
                if cross_distance is not None:
                    if (
                        self._min_cross_dist is None
                        or cross_distance < self._min_cross_dist
                    ):
                        self._min_cross_dist = cross_distance

                active_gap = l_knee_gap if self.active_side == "left" else r_knee_gap

                # If the *other* leg suddenly becomes the clearly-raised one
                # before the active side has come back down, treat this as
                # a fresh attempt on the other side rather than forcing a
                # close on a leg that's still up — this favors not missing
                # a real rep over rigidly requiring a full return-to-down.
                if (
                    raised_side is not None
                    and raised_side != self.active_side
                    and active_gap is not None
                    and active_gap < KNEE_DOWN_MIN_GAP
                ):
                    pass  # keep tracking the original side; ambiguous frame, ignore
                elif active_gap is not None and active_gap >= KNEE_DOWN_MIN_GAP:
                    # Knee back down — this attempt is complete.
                    rep_duration = (
                        (t - self.rep_start_time)
                        if self.rep_start_time is not None
                        else None
                    )
                    duration_valid = (
                        rep_duration is not None
                        and MIN_REP_DURATION <= rep_duration <= MAX_REP_DURATION
                    )

                    side = self.active_side
                    rep_side = side

                    if duration_valid:
                        rep_class = self._classify_tempo(rep_duration)
                        quality_good = (
                            self._min_cross_dist is not None
                            and self._min_cross_dist <= CROSS_GOOD_MAX
                        )
                        rep_form_quality = (
                            "good" if quality_good else "needs_improvement"
                        )

                        # ---- alternation check ----
                        if (
                            self.expected_next_side is None
                            or side == self.expected_next_side
                        ):
                            rep_completed = True
                            self.rep_count += 1
                            if quality_good:
                                self.good_reps += 1
                            else:
                                self.flawed_reps += 1
                            self.last_completed_side = side
                            self.expected_next_side = _other(side)

                            if quality_good:
                                feedback = (
                                    f"Rep {self.rep_count} counted — clean "
                                    f"{side} side ({rep_class})."
                                )
                            else:
                                feedback = (
                                    f"Rep {self.rep_count} counted, but bring "
                                    f"your elbow further across to your knee."
                                )
                        else:
                            alternation_broken = True
                            self.alternation_breaks += 1
                            feedback = (
                                f"That was {side} again — alternate sides. "
                                f"Switch to your {self.expected_next_side} knee next."
                            )
                    else:
                        if rep_duration is not None and rep_duration < MIN_REP_DURATION:
                            feedback = "Too fast — that one wasn't counted, control the movement."
                        elif (
                            rep_duration is not None and rep_duration > MAX_REP_DURATION
                        ):
                            feedback = (
                                "That rep took too long — not counted. Keep moving."
                            )
                        else:
                            feedback = "Not enough range of motion — not counted."

                    self.stage = "down"
                    self.active_side = None
                    self.rep_start_time = None
                    self._min_cross_dist = None

        if feedback is None and position_ok and not self.ready:
            feedback = (
                "Clasp your hands behind your head and stand tall to " "start counting."
            )
        if feedback is None:
            feedback = "Good form — keep going."

        self.last_timestamp_s = t

        response.update(
            {
                "stage": self.stage,
                "current_side": self.active_side,
                "last_completed_side": self.last_completed_side,
                "expected_next_side": self.expected_next_side,
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "alternation_breaks": self.alternation_breaks,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_side": rep_side,
                "rep_duration": rep_duration,
                "rep_classification": rep_class,
                "rep_form_quality": rep_form_quality,
                "alternation_broken": alternation_broken,
                "feedback": feedback,
            }
        )
        return response


class StandingCrossCrunchSession:
    """Full standing-cross-crunch session: one shared pose model + one
    analyzer.

    Same convention as `PushupSession` / `SidePlankSession` — `target_reps`
    / `target_sets` / `set_number` are the coach-assigned plan, supplied by
    the caller (the websocket route) from query params. The frontend never
    decides on its own whether a set/exercise is complete;
    `session_complete` and `exercise_complete` are both computed here.
    """

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = StandingCrossCrunchAnalyzer(target_reps)
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
