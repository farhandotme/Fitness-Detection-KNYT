"""
Russian Twist rep counting + posture correction.

Design
------
`RussianTwistAnalyzer` is a pure, stateful analyzer[cite: 2]. It expects a
33-point pose landmark list each frame. It tracks the lateral displacement
of the hands relative to the hips in 3D space to count reps, and monitors
the ankles to ensure the core is engaged and legs aren't swinging wildly.

A full repetition consists of twisting to one side and then twisting to the
opposite side.
"""

import math
from typing import Any, Optional
from src.engines.poseEngine import (
    LEFT_ANKLE,
    LEFT_HIP,
    LEFT_WRIST,
    RIGHT_ANKLE,
    RIGHT_HIP,
    RIGHT_WRIST,
    PoseEngine,
)

MIN_LANDMARK_VISIBILITY = 0.5
MIN_REQUIRED_LANDMARKS = 33


class RussianTwistAnalyzer:
    """Stateful Russian Twist rep counter + posture checker[cite: 2]."""

    def __init__(self, target_reps: Optional[int] = None):
        self.target_reps = target_reps

        # Rep counting state
        self.rep_count = 0
        self.good_reps = 0
        self.flawed_reps = 0
        self.left_count = 0
        self.right_count = 0

        self.phase = "center"
        self.last_touched_side = None

        # Signal processing state
        self.session_start_time: Optional[float] = None
        self.last_t_s: Optional[float] = None
        self.smoothed_signal = 0.0
        self.signal_max = 0.10  # Lowered baseline to catch initial movements faster

        # Leg stability state
        self.prev_left_ankle = None
        self.prev_right_ankle = None
        self.ankle_speed_ema = 0.0

    def _is_complete(self) -> bool:
        return self.target_reps is not None and self.rep_count >= self.target_reps

    def _get_raw_signal(self, landmarks) -> float:
        """
        Calculates the lateral displacement of the wrists relative to the hips.
        Uses 3D dot products (X and Z axis) so it works perfectly from a front,
        side (profile), or diagonal camera angle.
        """
        lh = landmarks[LEFT_HIP]
        rh = landmarks[RIGHT_HIP]
        lw = landmarks[LEFT_WRIST]
        rw = landmarks[RIGHT_WRIST]

        # 1. Define the body's horizontal axis (Vector from Right Hip to Left Hip)
        hx = lh.x - rh.x
        hz = lh.z - rh.z

        # Normalize the hip vector
        mag_h = math.hypot(hx, hz)
        if mag_h < 1e-4:
            hnx, hnz = 1.0, 0.0
        else:
            hnx, hnz = hx / mag_h, hz / mag_h

        # 2. Find the center of the hips and the center of the wrists
        mid_hip_x = (lh.x + rh.x) / 2.0
        mid_hip_z = (lh.z + rh.z) / 2.0

        mid_w_x = (lw.x + rw.x) / 2.0
        mid_w_z = (lw.z + rw.z) / 2.0

        # 3. Vector pointing from the body center to the hands
        wx = mid_w_x - mid_hip_x
        wz = mid_w_z - mid_hip_z

        # 4. Project the hand vector onto the hip vector using a dot product
        # Positive = User twisting to their Left. Negative = User twisting to their Right.
        raw_signal = (wx * hnx) + (wz * hnz)

        return raw_signal

    def update(self, landmarks, timestamp_ms: int) -> dict[str, Any]:
        t_s = timestamp_ms / 1000.0

        if self.session_start_time is None:
            self.session_start_time = t_s
        elapsed = max(0.0, t_s - self.session_start_time)

        response: dict[str, Any] = {
            "pose_detected": False,
            "stage": self.phase,
            "rep_count": self.rep_count,
            "good_reps": self.good_reps,
            "flawed_reps": self.flawed_reps,
            "target_reps": self.target_reps,
            "session_complete": self._is_complete(),
            "rep_completed": False,
            "rep_form_quality": None,
            "posture_ok": True,
            "posture_issues": [],
            "posture_messages": [],
            "feedback": None,
            "low_visibility": False,
            "elapsed_time": round(elapsed, 2),
            "left_angle": 0.0,
            "right_angle": 0.0,
        }

        if not landmarks or len(landmarks) < MIN_REQUIRED_LANDMARKS:
            response["feedback"] = "No person detected — step into frame."
            return response

        # 1. Check visibility of wrists
        lw = landmarks[LEFT_WRIST]
        rw = landmarks[RIGHT_WRIST]

        lw_vis = getattr(lw, "visibility", 1.0)
        rw_vis = getattr(rw, "visibility", 1.0)

        if lw_vis < MIN_LANDMARK_VISIBILITY and rw_vis < MIN_LANDMARK_VISIBILITY:
            response["pose_detected"] = True
            response["low_visibility"] = True
            response["feedback"] = (
                "Can't see your hands clearly — adjust your position."
            )
            return response

        response["pose_detected"] = True

        # 2. Time delta calculation
        dt_s = (t_s - self.last_t_s) if self.last_t_s is not None else 0.033
        dt_s = max(0.001, dt_s)
        self.last_t_s = t_s

        # 3. Process the 3D twist signal
        raw_signal = self._get_raw_signal(landmarks)

        # Smooth the signal to remove jitter (~66ms response time)
        alpha_smooth = 1.0 - math.exp(-dt_s / 0.066)
        self.smoothed_signal += alpha_smooth * (raw_signal - self.smoothed_signal)

        # Adaptive range calibration: expands quickly if they twist far, decays slowly
        curr_mag = abs(self.smoothed_signal)
        if curr_mag > self.signal_max:
            alpha_max = 1.0 - math.exp(-dt_s / 0.5)
        else:
            alpha_max = 1.0 - math.exp(-dt_s / 5.0)

        self.signal_max += alpha_max * (curr_mag - self.signal_max)
        self.signal_max = max(
            0.05, self.signal_max
        )  # Hard floor to prevent zero-division

        normalized_twist = self.smoothed_signal / self.signal_max
        normalized_twist = max(-1.5, min(1.5, normalized_twist))

        # 4. Phase Transition & Rep Counting with Hysteresis
        new_phase = self.phase
        if normalized_twist > 0.6:  # Threshold to register Left side
            new_phase = "left"
        elif normalized_twist < -0.6:  # Threshold to register Right side
            new_phase = "right"
        elif abs(normalized_twist) < 0.25:  # Must return near center to unlock
            new_phase = "center"

        rep_completed = False
        newly_completed_side = False

        if new_phase != self.phase:
            if new_phase in ["left", "right"] and new_phase != self.last_touched_side:
                if new_phase == "left":
                    self.left_count += 1
                else:
                    self.right_count += 1

                self.last_touched_side = new_phase
                newly_completed_side = True

                # A rep completes when both sides have been touched symmetrically
                new_rep_count = min(self.left_count, self.right_count)
                if new_rep_count > self.rep_count:
                    self.rep_count = new_rep_count
                    rep_completed = True

            self.phase = new_phase
            response["stage"] = self.phase

        # 5. Leg Stability tracking
        legs_stable = self._check_leg_stability(landmarks, dt_s)

        issues = []
        messages = []
        if not legs_stable:
            issues.append("leg_swing")
            messages.append(
                "Keep your legs steady — engage your core to stop the swinging."
            )

        # 6. Assign Feedback
        feedback = None
        rep_form_quality = None

        if rep_completed:
            if issues:
                rep_form_quality = "needs_improvement"
                self.flawed_reps += 1
                feedback = f"Rep {self.rep_count} counted, but control your legs!"
            else:
                rep_form_quality = "good"
                self.good_reps += 1
                feedback = f"Clean rep #{self.rep_count}!"
        elif newly_completed_side:
            feedback = "Good, now twist to the other side."
        elif messages:
            feedback = messages[0]

        # 7. UI Display Angles (Calculated strictly for frontend visuals)
        display_angle = min(90.0, abs(normalized_twist) * 90.0)

        response.update(
            {
                "rep_count": self.rep_count,
                "good_reps": self.good_reps,
                "flawed_reps": self.flawed_reps,
                "session_complete": self._is_complete(),
                "rep_completed": rep_completed,
                "rep_form_quality": rep_form_quality,
                "posture_ok": len(issues) == 0,
                "posture_issues": issues,
                "posture_messages": messages,
                "feedback": feedback,
                "left_angle": round(display_angle if normalized_twist > 0 else 0.0, 1),
                "right_angle": round(display_angle if normalized_twist < 0 else 0.0, 1),
            }
        )

        return response

    def _check_leg_stability(self, landmarks, dt_s: float) -> bool:
        la = landmarks[LEFT_ANKLE]
        ra = landmarks[RIGHT_ANKLE]

        la_vis = getattr(la, "visibility", 1.0) > MIN_LANDMARK_VISIBILITY
        ra_vis = getattr(ra, "visibility", 1.0) > MIN_LANDMARK_VISIBILITY

        speed_l = 0.0
        if la_vis and self.prev_left_ankle:
            dist = math.hypot(
                la.x - self.prev_left_ankle[0], la.y - self.prev_left_ankle[1]
            )
            speed_l = dist / dt_s

        speed_r = 0.0
        if ra_vis and self.prev_right_ankle:
            dist = math.hypot(
                ra.x - self.prev_right_ankle[0], ra.y - self.prev_right_ankle[1]
            )
            speed_r = dist / dt_s

        self.prev_left_ankle = (la.x, la.y) if la_vis else None
        self.prev_right_ankle = (ra.x, ra.y) if ra_vis else None

        max_speed = max(speed_l, speed_r)

        # Smooth speed to prevent tracking noise from falsely flagging instability
        alpha_speed = 1.0 - math.exp(-dt_s / 0.1)
        self.ankle_speed_ema += alpha_speed * (max_speed - self.ankle_speed_ema)

        # Threshold for excessive leg swing
        return self.ankle_speed_ema < 1.5


class RussianTwistSession:
    """Russian Twist session wrapper: manages the pose model and analyzer[cite: 2]."""

    def __init__(
        self,
        target_reps: Optional[int] = None,
        target_sets: int = 1,
        set_number: int = 1,
    ):
        self.engine = PoseEngine()
        self.analyzer = RussianTwistAnalyzer(target_reps)
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

        # Backend-validated plan progress[cite: 1]
        result["exercise_complete"] = bool(
            result["session_complete"] and self.set_number >= self.target_sets
        )

        return result

    def close(self):
        self.engine.close()
