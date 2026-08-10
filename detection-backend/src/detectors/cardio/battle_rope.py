"""
Battle Rope Cardio (alternating waves) — the classic battle-rope
conditioning move: an athletic stance (feet wider than shoulder-width,
knees softly bent, core braced), one rope end in each hand, driving one
arm up while the other comes down in a fast, continuous alternating
rhythm. Hands travel up to roughly shoulder height and back down toward
the thighs on each stroke.
(References: https://www.asphaltgreen.org/blog/the-beginners-guide-to-the-battle-ropes-5-essential-exercises-for-strength-and-conditioning/,
https://aerobis.com/blogs/fitness/battle-rope-workout-how-to-use-battle-ropes,
https://garagegympro.com/battle-rope-workout/)

Rebuilt as a HOLD exercise, matching `plank_hold.py`'s contract
--------------------------------------------------------------------
This exercise is programmed in TIME everywhere it's described ("30-40
seconds", "at least 30 seconds"), not a rep count, and the frontend's
hold panel expects the exact response shape `PlankHoldAnalyzer` produces
(`hold_state`, `is_holding`, `hold_seconds`, `current_streak_seconds`,
`posture_issues`, ...). Sending the old rep-counter shape
(`lead_arm`/`rep_count`/no `hold_state` at all) is what crashed the
panel. This version mirrors that contract field-for-field, adapting one
core idea:

    A plank's "holding" check is a single frame's joint angles — the
    position is either correct THIS INSTANT or it isn't. Battle rope
    waves have no static "correct instant" to check; the thing being
    verified is that the person is CONTINUOUSLY, ACTUALLY ALTERNATING,
    which can only be known by having recently observed a real switch.

So `is_holding` here requires all of: good framing, standing in an
athletic stance (not sitting/crouched out of the exercise entirely), AND
a confirmed left/right arm-lead switch within the last
`IDLE_TIMEOUT_SECONDS` — i.e. actual, ongoing wave motion, not a static
asymmetric pose held still (which would age out of the idle window and
correctly stop being "holding"). Everything else — the monotonic
`hold_seconds`/resettable `current_streak_seconds` split, per-frame
pause-and-instantly-resume on a bad frame (deliberately no grace-frame
counter here — see `plank_hold.py`'s docstring on why that split already
makes single bad frames self-healing without one), the hard-break vs.
soft-flaw tiering, rolling `form_score` — is carried over unchanged.

Wave detection signal
-----------------------
Same single relative signal used successfully once this analyzer's rep-
counting bug got fixed (see prior revision history): both wrists'
height relative to the shoulders, normalized by torso length (a stable,
non-moving body-scale reference), compared directly against each other:

    wave_diff = (shoulder.y - L_wrist.y)/torso_length
              - (shoulder.y - R_wrist.y)/torso_length

Strongly positive => left arm clearly higher (leading). Strongly
negative => the reverse. A switch is confirmed on a debounced sign flip
of this ONE relative signal — not a joint condition requiring both arms
to independently cross separate absolute thresholds on the same frame,
which is physically unreachable for two continuously, independently
moving limbs and was the bug in the very first version of this file.

Hard breaks vs. soft flaws (position / cheat-form detection)
------------------------------------------------------------------
Hard breaks (pause the hold timer, same tier as plank's knee-on-ground /
bad alignment — "this isn't the exercise anymore"):
  * bad camera framing
  * not standing in an athletic stance at all
  * no confirmed arm-lead switch within `IDLE_TIMEOUT_SECONDS` (stopped
    waving / just holding a static pose)

Soft flaws (`posture_issues`, tracked and scored, never pause the timer):
  * `shallow_wave` — small amplitude, from the most recently completed
    half-wave's peak `wave_diff`.
  * `locked_knees` — standing too tall instead of a soft quarter-squat
    ("athletic stance" — aerobis.com).
  * `stance_too_narrow` — feet not "a little wider than your hips"
    (aerobis.com).
  * `hunching_forward` — torso folding forward instead of a "tall,
    neutral spine" (aerobis.com).
"""

import math
from collections import deque
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

MIN_LANDMARK_VISIBILITY = 0.4
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)


def _looks_like_a_person(landmarks) -> bool:
    visible_core = sum(
        1
        for i in CORE_LANDMARKS
        if landmarks[i].visibility is not None and landmarks[i].visibility > 0.6
    )
    return visible_core >= 3


MIN_STANDING_INCLINE_DEG = 25.0  # torso must read at least this close to
# vertical to count as "in the athletic stance at all" — a hard-break
# gate (analogous to plank's MAX_STANDING_RATIO, inverted: this exercise
# must be standing, not horizontal). Deliberately loose — natural
# forward hip-hinge lean during a wave is normal; this only excludes
# clearly not-standing (sitting, crouched down, out of frame entirely).

# ---- wave signal: a single relative measure ----
# wave_diff = left wave_height - right wave_height, where
# wave_height = (shoulder.y - wrist.y) / torso_length (positive = wrist
# above shoulder). Strongly positive means the LEFT arm is clearly
# higher than the right; strongly negative means the reverse.
WAVE_DIFF_ENTER = 0.45  # required |wave_diff| to confirm a lead switch —
# generous on purpose; a real alternating wave clears this easily.
FULL_WAVE_DIFF = 0.75  # rewards a genuinely full swing (closer to true
# "shoulder height to thigh"), only affects the shallow_wave flag.

CONFIRM_FRAMES = 2  # consecutive agreeing frames before a lead-switch is
# confirmed — kept low; this is a fast, continuous movement, and
# requiring more confirm frames risks missing real switches entirely.

IDLE_TIMEOUT_SECONDS = 2.5  # no confirmed switch within this window means
# the person has stopped actually waving (a static pose, or just
# resting) — this is the hard break that keeps a held-still asymmetric
# position from being falsely counted as "holding" indefinitely.

# ---- soft cheat-form / position thresholds (never pause the timer) ----
KNEE_BENT_MAX_DEG = 168.0  # knees must stay softer than this, or it
# reads as standing too tall instead of a "quarter squat" athletic
# stance (aerobis.com).
STANCE_MIN_RATIO = 0.85  # ankle distance over shoulder width — feet
# should be "a little wider than your hips" (aerobis.com).
TORSO_LEAN_FLAW_MAX_DEG = 50.0  # torso incline from vertical must not
# drop below this, or it reads as hunching/rounding forward instead of
# a "tall, neutral spine" (aerobis.com). Deliberately a higher (stricter)
# bar than MIN_STANDING_INCLINE_DEG's hard-break floor — this is the
# "doing it, but not cleanly" zone.

# Per-issue form_score penalty (applied per frame while holding).
MISTAKE_PENALTY = {
    "shallow_wave": 20,
    "locked_knees": 15,
    "stance_too_narrow": 15,
    "hunching_forward": 15,
}

# form_score is sampled into this rolling window roughly once a second
# (not every frame) so `avg_form_score` reflects the last ~SCORE_HISTORY
# seconds of holding rather than being dominated by frame rate.
SCORE_HISTORY = 30
SCORE_SAMPLE_INTERVAL = 1.0  # seconds

# ---- camera framing ----
FRAME_EDGE_MARGIN = 0.03
BBOX_TOO_CLOSE = 0.97
BBOX_TOO_FAR = 0.10


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


def _torso_vertical_incline_deg(mid_shoulder, mid_hip) -> Optional[float]:
    """Degrees from horizontal (90 = perfectly upright, 0 = lying flat)."""
    dx = mid_hip.x - mid_shoulder.x
    dy = mid_hip.y - mid_shoulder.y
    if dx == 0 and dy == 0:
        return None
    return math.degrees(math.atan2(abs(dy), max(abs(dx), 1e-9)))


def _framing_feedback(points: list) -> Optional[str]:
    for p in points:
        if (
            p.x < FRAME_EDGE_MARGIN
            or p.x > 1 - FRAME_EDGE_MARGIN
            or p.y < FRAME_EDGE_MARGIN
            or p.y > 1 - FRAME_EDGE_MARGIN
        ):
            return (
                "You're partly out of frame — back up so your whole body, "
                "including your hands and feet, stays visible."
            )

    if len(points) < 4:
        return None

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    if height > BBOX_TOO_CLOSE:
        return (
            "You're too close to the camera — back up so your full body fits in frame."
        )
    if width < BBOX_TOO_FAR and height < BBOX_TOO_FAR:
        return "You're too far from the camera — move closer for accurate tracking."

    return None


class BattleRopeCardioAnalyzer:
    """Stateful battle-rope hold timer + form checker — same contract
    shape as `PlankHoldAnalyzer`: a monotonic `hold_seconds` that only
    advances while genuinely, continuously alternating waves in an
    athletic stance, pausing (never resetting) on any bad frame, plus
    non-blocking form/position flags."""

    def __init__(self, target_seconds: Optional[int] = None):
        self.target_seconds = target_seconds

        self.hold_active = False  # is the timer running THIS frame
        self.started = False  # has the timer ever run at all
        self.hold_seconds = 0.0
        self.good_seconds = 0.0
        self.flawed_seconds = 0.0
        self.current_streak_seconds = 0.0
        self.best_streak_seconds = 0.0
        self.break_count = 0

        self.last_timestamp_s: Optional[float] = None
        self.session_start_time: Optional[float] = None

        self._was_complete = False  # for edge-triggering `target_reached`

        self.form_scores: "deque[int]" = deque(maxlen=SCORE_HISTORY)
        self._last_score_sample_time: Optional[float] = None

        # Wave-switch tracking
        self.lead: Optional[str] = None
        self._pending_lead: Optional[str] = None
        self._pending_streak = 0
        self._last_switch_time: Optional[float] = None
        self.wave_count = 0  # supplementary telemetry, does not drive completion

        # Amplitude of the most recently completed half-wave, and the
        # extreme reached by whichever half-wave is currently in progress.
        self._last_wave_amplitude: Optional[float] = None
        self._extreme_diff: Optional[float] = None

    # ---------------------------------------------------------------
    def _is_complete(self) -> bool:
        return (
            self.target_seconds is not None and self.hold_seconds >= self.target_seconds
        )

    def _register_broken_frame(self):
        if self.hold_active:
            self.break_count += 1
        self.hold_active = False
        self.current_streak_seconds = 0.0

    def _progress_fields(self) -> dict:
        return {
            "hold_seconds": round(self.hold_seconds, 2),
            "good_seconds": round(self.good_seconds, 2),
            "flawed_seconds": round(self.flawed_seconds, 2),
            "current_streak_seconds": round(self.current_streak_seconds, 2),
            "best_streak_seconds": round(self.best_streak_seconds, 2),
            "break_count": self.break_count,
            "session_complete": self._is_complete(),
        }

    @staticmethod
    def _avg(values) -> Optional[int]:
        if not values:
            return None
        return round(sum(values) / len(values))

    # ---------------------------------------------------------------
    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t = timestamp_ms / 1000.0
        if self.session_start_time is None:
            self.session_start_time = t
        elapsed = max(0.0, t - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "hold_state": (
                "holding"
                if self.started and self.hold_active
                else ("broken" if self.started else "not_started")
            ),
            "is_holding": False,
            "target_seconds": self.target_seconds,
            "target_reached": False,
            "hold_quality": None,
            "posture_ok": True,
            "posture_issues": [],
            "posture_messages": [],
            "framing_ok": True,
            "framing_message": None,
            "form_score": None,
            "avg_form_score": self._avg(self.form_scores),
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
            "wave_count": self.wave_count,
            "lead_arm": self.lead,
            "wave_diff": None,
            "left_wave_height": None,
            "right_wave_height": None,
            "knee_angle": None,
            "stance_ratio": None,
            "torso_incline": None,
        }
        response.update(self._progress_fields())

        dt = 0.0
        if self.last_timestamp_s is not None:
            dt = max(0.0, min(t - self.last_timestamp_s, 0.5))  # clamp huge gaps
        self.last_timestamp_s = t

        if landmarks is None or not _looks_like_a_person(landmarks):
            self._register_broken_frame()
            response["feedback"] = (
                "No person detected — stand facing the camera with your "
                "whole body visible."
            )
            response.update(self._progress_fields())
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_wrist, r_wrist = landmarks[LEFT_WRIST], landmarks[RIGHT_WRIST]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        torso_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip))
        arms_visible = _visible((l_wrist, r_wrist))
        legs_visible = _visible((l_knee, r_knee, l_ankle, r_ankle))

        if not torso_visible or not arms_visible or not legs_visible:
            response["pose_detected"] = True
            response["low_visibility"] = True
            self._register_broken_frame()
            response["feedback"] = (
                "Can't see your body clearly — step back so your shoulders, "
                "hips, hands, and feet are all in frame."
            )
            response.update(self._progress_fields())
            return response

        response["pose_detected"] = True

        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        mid_hip = _midpoint(l_hip, r_hip)
        torso_length = max(_dist(mid_shoulder, mid_hip), 1e-6)
        shoulder_width = max(_dist(l_shoulder, r_shoulder), 1e-6)
        ankle_dist = _dist(l_ankle, r_ankle)
        stance_ratio = ankle_dist / shoulder_width

        left_wave = (l_shoulder.y - l_wrist.y) / torso_length
        right_wave = (r_shoulder.y - r_wrist.y) / torso_length
        wave_diff = left_wave - right_wave

        left_knee_angle = _angle_at(l_hip, l_knee, l_ankle)
        right_knee_angle = _angle_at(r_hip, r_knee, r_ankle)
        knee_angles = [a for a in (left_knee_angle, right_knee_angle) if a is not None]
        knee_angle = sum(knee_angles) / len(knee_angles) if knee_angles else None

        torso_incline = _torso_vertical_incline_deg(mid_shoulder, mid_hip)

        framing_points = [
            l_shoulder,
            r_shoulder,
            l_hip,
            r_hip,
            l_knee,
            r_knee,
            l_ankle,
            r_ankle,
        ]
        framing_message = _framing_feedback(framing_points)
        framing_ok = framing_message is None

        response.update(
            {
                "framing_ok": framing_ok,
                "framing_message": framing_message,
                "wave_diff": round(wave_diff, 3),
                "left_wave_height": round(left_wave, 3),
                "right_wave_height": round(right_wave, 3),
                "knee_angle": round(knee_angle, 1) if knee_angle is not None else None,
                "stance_ratio": round(stance_ratio, 3),
                "torso_incline": (
                    round(torso_incline, 1) if torso_incline is not None else None
                ),
            }
        )

        # ---- track the furthest excursion of the half-wave in progress,
        # regardless of confirmation state, so the amplitude used for the
        # shallow_wave flaw reflects the real swing, not just whichever
        # single frame happened to confirm the switch.
        if self._extreme_diff is None:
            self._extreme_diff = wave_diff
        elif wave_diff > 0 and self._extreme_diff > 0:
            self._extreme_diff = max(self._extreme_diff, wave_diff)
        elif wave_diff < 0 and self._extreme_diff < 0:
            self._extreme_diff = min(self._extreme_diff, wave_diff)
        elif abs(wave_diff) > abs(self._extreme_diff):
            self._extreme_diff = wave_diff

        if wave_diff >= WAVE_DIFF_ENTER:
            candidate_lead = "left"
        elif wave_diff <= -WAVE_DIFF_ENTER:
            candidate_lead = "right"
        else:
            candidate_lead = None  # dead zone — mid-wave, don't force a flip

        if candidate_lead is not None and candidate_lead == self._pending_lead:
            self._pending_streak += 1
        elif candidate_lead is not None:
            self._pending_lead = candidate_lead
            self._pending_streak = 1
        else:
            self._pending_lead = None
            self._pending_streak = 0

        if (
            candidate_lead is not None
            and self._pending_streak >= CONFIRM_FRAMES
            and candidate_lead != self.lead
        ):
            if self.lead is not None:
                # A real half-wave just completed — bank its amplitude and
                # count it (the very first switch only establishes which
                # arm leads; there's no prior half-wave to have completed).
                self._last_wave_amplitude = self._extreme_diff
                self.wave_count += 1
            self.lead = candidate_lead
            self._last_switch_time = t
            self._extreme_diff = wave_diff

        # ---- resolve hold-validity this frame ----
        actively_alternating = (
            self._last_switch_time is not None
            and (t - self._last_switch_time) <= IDLE_TIMEOUT_SECONDS
        )
        is_standing = (
            torso_incline is not None and torso_incline >= MIN_STANDING_INCLINE_DEG
        )
        holding_now = framing_ok and is_standing and actively_alternating

        # ---- form tiering (only meaningful while holding) ----
        issues: list[str] = []
        messages: list[str] = []
        if holding_now:
            if (
                self._last_wave_amplitude is None
                or abs(self._last_wave_amplitude) < FULL_WAVE_DIFF
            ):
                issues.append("shallow_wave")
                messages.append(
                    "Drive the wave bigger — hand up to shoulder height, down toward your thigh."
                )
            if knee_angle is not None and knee_angle >= KNEE_BENT_MAX_DEG:
                issues.append("locked_knees")
                messages.append(
                    "Soften your knees into a quarter squat, athletic stance."
                )
            if stance_ratio < STANCE_MIN_RATIO:
                issues.append("stance_too_narrow")
                messages.append(
                    "Widen your stance — feet a little wider than your hips."
                )
            if torso_incline is not None and torso_incline < TORSO_LEAN_FLAW_MAX_DEG:
                issues.append("hunching_forward")
                messages.append(
                    "Keep your chest up and spine neutral — don't round forward."
                )

        # ---- advance / pause the timer ----
        form_score = None
        hold_quality = None
        if holding_now:
            if not self.hold_active:
                self.current_streak_seconds = 0.0
            self.hold_active = True
            self.started = True

            self.hold_seconds += dt
            self.current_streak_seconds += dt
            if self.current_streak_seconds > self.best_streak_seconds:
                self.best_streak_seconds = self.current_streak_seconds

            if issues:
                self.flawed_seconds += dt
                hold_quality = "needs_improvement"
            else:
                self.good_seconds += dt
                hold_quality = "good"

            form_score = 100
            for issue in issues:
                form_score -= MISTAKE_PENALTY.get(issue, 10)
            form_score = max(0, form_score)

            if (
                self._last_score_sample_time is None
                or t - self._last_score_sample_time >= SCORE_SAMPLE_INTERVAL
            ):
                self.form_scores.append(form_score)
                self._last_score_sample_time = t
        else:
            self._register_broken_frame()

        is_complete = self._is_complete()
        target_reached = is_complete and not self._was_complete
        self._was_complete = is_complete

        # ---- feedback priority: framing > hard breaks > form flaws > praise ----
        feedback = framing_message
        if feedback is None and not is_standing:
            feedback = (
                "Get into an athletic stance — feet wider than your hips, "
                "knees softly bent, facing the camera."
            )
        if feedback is None and not actively_alternating:
            feedback = (
                "Start alternating — drive one arm up while the other comes down."
                if self._last_switch_time is None
                else "Keep the waves continuous — don't pause mid-set."
            )
        if feedback is None and messages:
            feedback = messages[0]
        if feedback is None and target_reached:
            feedback = f"Target reached — {self.target_seconds}s held, nice work!"
        if feedback is None and holding_now:
            feedback = "Great rhythm — keep waving!"
        if feedback is None:
            feedback = "Get back into position to resume the timer."

        response.update(
            {
                "hold_state": (
                    "holding"
                    if holding_now
                    else ("broken" if self.started else "not_started")
                ),
                "is_holding": holding_now,
                "target_reached": target_reached,
                "hold_quality": hold_quality,
                "posture_ok": len(issues) == 0,
                "posture_issues": issues,
                "posture_messages": messages,
                "form_score": form_score,
                "avg_form_score": self._avg(self.form_scores),
                "feedback": feedback,
                "wave_count": self.wave_count,
                "lead_arm": self.lead,
            }
        )
        response.update(self._progress_fields())
        return response


class BattleRopeCardioSession:
    """Full battle-rope-cardio session: one shared pose model + one
    analyzer. Same convention as `PlankHoldSession` — `target_seconds` /
    `target_sets` / `set_number` are the coach-assigned plan, supplied by
    the caller (the websocket route, from query params); the frontend
    does not decide on its own whether a set/exercise is done —
    `session_complete` (this set's hold time is met) and
    `exercise_complete` (the whole assigned plan, all sets) are both
    computed here.
    """

    def __init__(
        self,
        target_seconds: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = BattleRopeCardioAnalyzer(target_seconds)
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
