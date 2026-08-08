"""
Line Hops / Side-to-Side Hops detector.

Movement contract
------------------
Stand with feet together (or hip-width), knees soft, next to an imaginary
line on the floor. Jump sideways with both feet together over the line,
land softly with a slight knee bend, then immediately rebound back over
the line the other way. Repeat rapidly, staying upright without twisting
the torso. (Sources: rb100.fitness, motra.com, spotebi.com, fitbod.me —
"Each hop counts as one rep.")

Design note — why this is NOT angle-threshold based
----------------------------------------------------
The lateral lunge detector counted reps by gating on knee-flexion angles,
which turned out to be fragile against a degraded camera feed (a webcam
filming a monitor introduces foreshortening/compression that reads
shallower knee bends than reality, causing valid reps to go uncounted).

Line hops are a fast, small-amplitude, side-to-side movement, so instead
of relying on a joint angle, this detector tracks the horizontal position
of the feet relative to a slowly-adapting centerline (the "line") and
counts a rep every time that position crosses from confirmed-right to
confirmed-left or vice versa. This is a hysteresis / Schmitt-trigger
pattern — the same robust technique real pedometers and rep counters use
— and it degrades gracefully: even if the exact pixel position is noisy,
crossing detection with a dead-band is far less sensitive to that noise
than an absolute angle threshold is.
"""

import math
from typing import Any, Optional

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    PoseEngine,
    RIGHT_ANKLE,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
)

# Bump this string on every edit. Printed at import time and at session
# start, and returned in every response as "detector_version" — check the
# server logs or the live response to confirm a redeploy actually took
# effect instead of silently continuing to run an old process.
DETECTOR_VERSION = "line_hop-2026-08-08c-visibility-dropout-fix"
print(f"[LineHop] loaded detector_version={DETECTOR_VERSION}")

MIN_VISIBILITY = 0.30
PERSON_VISIBILITY = 0.50
LEG_VISIBILITY = 0.28
CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)

# The "line" is not detected visually — it's inferred as wherever the
# person's feet naturally sit, tracked as a slow-moving average so it
# isn't fooled by the fast left-right hop motion itself.
CENTER_EMA_ALPHA = 0.01
STANDING_HEIGHT_EMA_ALPHA = 0.02

# Offsets are normalized by shoulder width (scale-invariant across camera
# distance). A hop must push the feet at least this far from centerline
# to confirm a side. Kept modest on purpose: a fast hop sampled at webcam
# frame rate may only be caught partway through its excursion, so
# requiring a large amplitude causes real fast hops to go uncounted.
ZONE_THRESHOLD_RATIO = 0.22
# Used only to learn the "standing" baseline height for the soft airborne
# cue below — NOT required before the opposite side can count. Fast
# hopping can go straight from confirmed-right to confirmed-left without
# ever landing in this band on a sampled frame, so gating re-arm on it
# blocked every hop after the first.
CENTER_DEADBAND_RATIO = 0.12
# A single frame past the threshold is enough — at hop speed there may
# only be one sampled frame in the excursion at all.
ZONE_CONFIRM_FRAMES = 1

# Debounce only — prevents one hop being read as two on landmark noise,
# not meant to cap hop cadence. Comfortably above a single frame at
# typical webcam rates (~30fps -> 33ms) but well under real hop timing.
MIN_REP_INTERVAL_S = 0.08
AIRBORNE_MIN_RATIO = 0.018  # soft "did they actually leave the ground" cue
FEET_TOGETHER_MAX_RATIO = 1.0  # soft "feet together" cue, not a hard gate
MAX_TORSO_LEAN_DEG = 25.0

POSITION_CONFIRM_FRAMES = 4
POSITION_GRACE_FRAMES = 5
FRAME_EDGE_MARGIN = 0.035


def _visible(points: tuple[Any, ...], threshold: float = MIN_VISIBILITY) -> bool:
    return all(
        point is not None
        and (
            getattr(point, "visibility", None) is None
            or getattr(point, "visibility", 0.0) >= threshold
        )
        for point in points
    )


def _looks_like_person(landmarks: list[Any]) -> bool:
    if len(landmarks) < 33:
        return False
    visible_core = sum(
        1
        for index in CORE_LANDMARKS
        if getattr(landmarks[index], "visibility", 0.0) >= PERSON_VISIBILITY
    )
    return visible_core >= 3


def _distance(a: Any, b: Any) -> float:
    return math.hypot(float(a.x) - float(b.x), float(a.y) - float(b.y))


def _midpoint(a: Any, b: Any) -> tuple[float, float]:
    return ((float(a.x) + float(b.x)) / 2.0, (float(a.y) + float(b.y)) / 2.0)


def _angle_at(a: Any, b: Any, c: Any) -> Optional[float]:
    first = (float(a.x) - float(b.x), float(a.y) - float(b.y))
    second = (float(c.x) - float(b.x), float(c.y) - float(b.y))
    first_len = math.hypot(*first)
    second_len = math.hypot(*second)
    if first_len < 1e-7 or second_len < 1e-7:
        return None
    cosine = (first[0] * second[0] + first[1] * second[1]) / (first_len * second_len)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _view_mode(shoulder_width: float, torso_length: float) -> str:
    ratio = shoulder_width / max(torso_length, 1e-7)
    if ratio >= 1.02:
        return "front"
    if ratio <= 0.58:
        return "side"
    return "angled"


def _torso_lean(
    mid_shoulder: tuple[float, float], mid_hip: tuple[float, float]
) -> float:
    dx = mid_hip[0] - mid_shoulder[0]
    dy = mid_hip[1] - mid_shoulder[1]
    return math.degrees(math.atan2(abs(dx), max(abs(dy), 1e-7)))


def _framing_feedback(points: list[Any]) -> Optional[str]:
    for point in points:
        if point.x < FRAME_EDGE_MARGIN or point.x > 1.0 - FRAME_EDGE_MARGIN:
            return "Move back so both hop landing zones stay inside the frame."
        if point.y < FRAME_EDGE_MARGIN or point.y > 1.0 - FRAME_EDGE_MARGIN:
            return "Keep your full body inside the frame, head to feet."
    return None


def _tempo(duration: Optional[float]) -> Optional[str]:
    if duration is None:
        return None
    if duration < 0.15:
        return "too_fast"
    if duration < 0.35:
        return "fast"
    if duration < 1.2:
        return "good"
    if duration < 2.5:
        return "slow"
    return "too_slow"


class LineHopAnalyzer:
    """Stateful front-view side-to-side line hop counter."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps
        self.rep_count = 0
        self.left_reps = 0
        self.right_reps = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.stage = "setup"
        self.ready = False

        self._position_good_streak = 0
        self._position_bad_streak = 0
        self._session_start_time: Optional[float] = None

        self._center_x: Optional[float] = None
        self._standing_hip_y: Optional[float] = None
        self._last_zone: Optional[str] = None
        self._pending_zone: Optional[str] = None
        self._zone_streak = 0
        self._armed = True
        self._last_rep_time: Optional[float] = None
        self._transition_start_time: Optional[float] = None
        self._min_hip_y_since_center: Optional[float] = None
        self._feet_together_ok_this_transition = True

    def _complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _base_response(self, elapsed: float) -> dict[str, Any]:
        return {
            "detector_version": DETECTOR_VERSION,
            "pose_detected": False,
            "view_mode": None,
            "view_advisory": None,
            "position_ok": False,
            "position_message": None,
            "ready": self.ready,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "left_reps": self.left_reps,
            "right_reps": self.right_reps,
            "current_zone": None,
            "target_reps": self.target_reps,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "session_complete": self._complete(),
            "rep_completed": False,
            "rep_duration": None,
            "rep_avg_speed": None,
            "rep_classification": None,
            "rep_form_quality": None,
            "rep_side": None,
            "lateral_offset_ratio": None,
            "left_knee_angle": None,
            "right_knee_angle": None,
            "left_angle": None,
            "right_angle": None,
            "stance_ratio": None,
            "torso_lean_deg": None,
            "alignment_ok": False,
            "alignment_issue": None,
            "framing_ok": True,
            "framing_message": None,
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
        }

    def update(
        self, landmarks: Optional[list[Any]], timestamp_ms: int
    ) -> dict[str, Any]:
        timestamp_s = timestamp_ms / 1000.0
        if self._session_start_time is None:
            self._session_start_time = timestamp_s
        elapsed = max(0.0, timestamp_s - self._session_start_time)
        response = self._base_response(elapsed)

        if landmarks is None or not _looks_like_person(landmarks):
            response["feedback"] = (
                "No person detected — face the camera with your full body visible."
            )
            self._position_good_streak = 0
            self._position_bad_streak += 1
            if self._position_bad_streak >= POSITION_GRACE_FRAMES:
                if self.ready:
                    self._last_zone = None
                    self._pending_zone = None
                    self._zone_streak = 0
                self.ready = False
            return response

        l_shoulder, r_shoulder = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
        l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]
        l_knee, r_knee = landmarks[LEFT_KNEE], landmarks[RIGHT_KNEE]
        l_ankle, r_ankle = landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE]

        legs_visible = _visible((l_hip, l_ankle), LEG_VISIBILITY) and _visible(
            (r_hip, r_ankle), LEG_VISIBILITY
        )
        core_visible = _visible((l_shoulder, r_shoulder, l_hip, r_hip), MIN_VISIBILITY)
        # NOTE: we deliberately do NOT bail out here just because visibility
        # dips below threshold. Motion blur is worst at exactly the moment
        # a hop crosses the line — the fastest part of the movement — so a
        # frame that discards itself on low visibility tends to discard
        # exactly the frames that matter most, causing intermittent missed
        # reps during fast movement. Geometry is still computed from
        # whatever coordinates the pose model returned; visibility only
        # feeds the readiness lock-on and UI messaging below.

        shoulder_width = _distance(l_shoulder, r_shoulder)
        torso_length = max(_distance(l_shoulder, l_hip), _distance(r_shoulder, r_hip))
        view_mode = _view_mode(shoulder_width, torso_length)
        # NOTE: view_mode is advisory only, never a gate — see lateral_lunge.py
        # for why hard-gating on this heuristic breaks valid sessions.
        view_advisory = (
            None
            if view_mode in ("front", "angled")
            else "Facing the camera more directly will make tracking more reliable."
        )

        framing_message = _framing_feedback(
            [l_shoulder, r_shoulder, l_hip, r_hip, l_ankle, r_ankle]
        )
        framing_ok = framing_message is None

        mid_hip = _midpoint(l_hip, r_hip)
        mid_ankle_x = (float(l_ankle.x) + float(r_ankle.x)) / 2.0
        mid_shoulder = _midpoint(l_shoulder, r_shoulder)
        torso_lean = _torso_lean(mid_shoulder, mid_hip)
        ankle_distance = _distance(l_ankle, r_ankle)
        stance_ratio = ankle_distance / max(shoulder_width, 1e-7)

        left_knee_angle = _angle_at(l_hip, l_knee, l_ankle)
        right_knee_angle = _angle_at(r_hip, r_knee, r_ankle)

        position_now_ok = core_visible and legs_visible and framing_ok
        if position_now_ok:
            self._position_good_streak += 1
            self._position_bad_streak = 0
        else:
            self._position_good_streak = 0
            self._position_bad_streak += 1
        if self._position_good_streak >= POSITION_CONFIRM_FRAMES:
            self.ready = True
        elif self._position_bad_streak >= POSITION_GRACE_FRAMES:
            # Sustained loss of lock (not a single soft frame) — this is
            # the only place zone-tracking state gets reset outside of a
            # full person-not-detected bail.
            if self.ready:
                self._last_zone = None
                self._pending_zone = None
                self._zone_streak = 0
            self.ready = False

        position_message: Optional[str] = None
        if not core_visible or not legs_visible:
            position_message = "Face the camera so your whole body stays visible."
        elif not framing_ok:
            position_message = framing_message
        elif not self.ready:
            position_message = (
                "Hold still near center for a moment while I lock onto your position."
            )

        # position_ok reflects the strict momentary snapshot (used for the
        # UI's alignment display). can_track is deliberately looser: once
        # locked on, a single low-visibility frame (e.g. motion blur at the
        # peak of a fast hop) shouldn't stop counting, only true framing
        # loss (person actually out of shot) should.
        position_ok = self.ready and position_now_ok
        can_track = self.ready and framing_ok

        response.update(
            {
                "pose_detected": True,
                "view_mode": view_mode,
                "view_advisory": view_advisory,
                "position_ok": position_ok,
                "position_message": position_message,
                "ready": self.ready,
                "left_knee_angle": (
                    round(left_knee_angle, 1) if left_knee_angle else None
                ),
                "right_knee_angle": (
                    round(right_knee_angle, 1) if right_knee_angle else None
                ),
                "left_angle": round(left_knee_angle, 1) if left_knee_angle else None,
                "right_angle": round(right_knee_angle, 1) if right_knee_angle else None,
                "stance_ratio": round(stance_ratio, 2),
                "torso_lean_deg": round(torso_lean, 1),
                "framing_ok": framing_ok,
                "framing_message": framing_message,
                "alignment_ok": position_ok and torso_lean <= MAX_TORSO_LEAN_DEG,
                "alignment_issue": (
                    position_message
                    or (
                        "Keep your chest up and avoid twisting your torso as you hop."
                        if torso_lean > MAX_TORSO_LEAN_DEG
                        else view_advisory
                    )
                ),
                "low_visibility": not _visible(
                    (l_shoulder, r_shoulder, l_hip, r_hip, l_ankle, r_ankle), 0.55
                ),
            }
        )

        if not can_track:
            response["feedback"] = (
                position_message or "Getting a lock on your position..."
            )
            # Deliberately NOT resetting zone-tracking state here — a
            # single out-of-frame or not-yet-locked-on frame shouldn't
            # erase progress; see the sustained-loss branch above for the
            # one place that actually resets it.
            return response

        # --- Adaptive centerline ("the line") ---
        if self._center_x is None:
            self._center_x = mid_ankle_x
        offset = mid_ankle_x - self._center_x
        normalized_offset = offset / max(shoulder_width, 1e-7)
        self._center_x += CENTER_EMA_ALPHA * (mid_ankle_x - self._center_x)

        # Track standing hip height near center for a soft "did they jump" cue.
        if abs(normalized_offset) <= CENTER_DEADBAND_RATIO:
            if self._standing_hip_y is None:
                self._standing_hip_y = mid_hip[1]
            else:
                self._standing_hip_y += STANDING_HEIGHT_EMA_ALPHA * (
                    mid_hip[1] - self._standing_hip_y
                )
            self._armed = True
            self._min_hip_y_since_center = mid_hip[1]
            self._feet_together_ok_this_transition = (
                stance_ratio <= FEET_TOGETHER_MAX_RATIO
            )
            self.stage = "center"
        else:
            if (
                self._min_hip_y_since_center is None
                or mid_hip[1] < self._min_hip_y_since_center
            ):
                self._min_hip_y_since_center = mid_hip[1]
            if stance_ratio > FEET_TOGETHER_MAX_RATIO:
                self._feet_together_ok_this_transition = False
            self.stage = "right" if normalized_offset > 0 else "left"

        raw_zone = (
            "right"
            if normalized_offset >= ZONE_THRESHOLD_RATIO
            else "left" if normalized_offset <= -ZONE_THRESHOLD_RATIO else None
        )
        if raw_zone is not None and raw_zone == self._pending_zone:
            self._zone_streak += 1
        elif raw_zone is not None:
            self._pending_zone = raw_zone
            self._zone_streak = 1
        else:
            self._pending_zone = None
            self._zone_streak = 0
        confirmed_zone = (
            self._pending_zone if self._zone_streak >= ZONE_CONFIRM_FRAMES else None
        )

        response["current_zone"] = confirmed_zone or self.stage
        response["lateral_offset_ratio"] = round(normalized_offset, 3)

        rep_counted = False
        if confirmed_zone is not None and confirmed_zone != self._last_zone:
            too_soon = (
                self._last_rep_time is not None
                and (timestamp_s - self._last_rep_time) < MIN_REP_INTERVAL_S
            )
            # Always recognize the side-change immediately, even if this
            # particular instance gets deduped below — otherwise a single
            # debounced hop would desync alternation tracking and silently
            # block every hop after it (this was the actual bug: fast
            # hopping could trip the debounce once and then never count
            # again because _last_zone was stuck on the old side).
            duration = (
                timestamp_s - self._last_rep_time
                if self._last_rep_time is not None
                else None
            )
            self._last_zone = confirmed_zone

            if not too_soon:
                self.rep_count += 1
                if confirmed_zone == "left":
                    self.left_reps += 1
                else:
                    self.right_reps += 1

                issues = set()
                if (
                    self._standing_hip_y is not None
                    and self._min_hip_y_since_center is not None
                ):
                    air_rise = self._standing_hip_y - self._min_hip_y_since_center
                    normalized_rise = air_rise / max(shoulder_width, 1e-7)
                    if normalized_rise < AIRBORNE_MIN_RATIO:
                        issues.add("no_visible_hop")
                if not self._feet_together_ok_this_transition:
                    issues.add("feet_apart")
                if torso_lean > MAX_TORSO_LEAN_DEG:
                    issues.add("twisting")

                quality = "good" if not issues else "needs_improvement"
                if quality == "good":
                    self.good_reps += 1
                else:
                    self.flawed_reps += 1

                response.update(
                    {
                        "rep_completed": True,
                        "rep_side": confirmed_zone,
                        "rep_duration": round(duration, 3) if duration else None,
                        "rep_avg_speed": (
                            round(1.0 / duration, 2)
                            if duration and duration > 0
                            else None
                        ),
                        "rep_classification": _tempo(duration),
                        "rep_form_quality": quality,
                    }
                )

                self._last_rep_time = timestamp_s
                rep_counted = True

        if rep_counted:
            response["feedback"] = (
                f"Rep {self.rep_count} — hop {response['rep_side']} counted."
            )
        elif position_message:
            response["feedback"] = position_message
        elif self.stage == "center":
            response["feedback"] = (
                "Hop side to side over the line, landing soft on both feet."
            )
        elif self._complete():
            response["feedback"] = (
                f"Target reached — {self.target_reps} hops completed."
            )
        else:
            response["feedback"] = (
                "Keep the rhythm going — quick, light hops side to side."
            )

        response.update(
            {
                "stage": self.stage,
                "rep_count": self.rep_count,
                "left_reps": self.left_reps,
                "right_reps": self.right_reps,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._complete(),
            }
        )
        return response


class LineHopSession:
    """Standalone detector session using one shared PoseEngine."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = LineHopAnalyzer(target_reps)
        self.target_sets = max(1, target_sets)
        self.set_number = max(1, min(set_number, self.target_sets))
        print(
            f"[LineHop] session start detector_version={DETECTOR_VERSION} "
            f"ZONE_THRESHOLD_RATIO={ZONE_THRESHOLD_RATIO} "
            f"CENTER_DEADBAND_RATIO={CENTER_DEADBAND_RATIO} "
            f"ZONE_CONFIRM_FRAMES={ZONE_CONFIRM_FRAMES} "
            f"MIN_REP_INTERVAL_S={MIN_REP_INTERVAL_S}"
        )

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
