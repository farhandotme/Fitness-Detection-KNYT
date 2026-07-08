import math
import os
import time
from typing import Any, Optional

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

# -------------------------------
# Configuration
# -------------------------------

MODEL_PATH = "pose_landmarker.task"

MIN_DETECTION_CONFIDENCE = 0.6
MIN_PRESENCE_CONFIDENCE = 0.6
MIN_TRACKING_CONFIDENCE = 0.6

# BlazePose 33-point indices
LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_ELBOW = 13
RIGHT_ELBOW = 14
LEFT_WRIST = 15
RIGHT_WRIST = 16
LEFT_HIP = 23
RIGHT_HIP = 24
LEFT_KNEE = 25
RIGHT_KNEE = 26
LEFT_ANKLE = 27
RIGHT_ANKLE = 28

# down_angle / up_angle need a gap between them (hysteresis band).
EXERCISES = {
    "bicep_curl": {
        "joints": (LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST),
        "down_angle": 160,
        "up_angle": 50,
        # optional: min angle delta to count a rep as valid (to avoid tiny movements)
        "min_angle_delta": 25,
    },
    "squat": {
        "joints": (LEFT_HIP, LEFT_KNEE, LEFT_ANKLE),
        "down_angle": 160,
        "up_angle": 90,
        "min_angle_delta": 20,
    },
    "pushup": {
        "joints": (LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST),
        "down_angle": 160,
        "up_angle": 70,
        "min_angle_delta": 20,
    },
}


class RepCounter:
    def __init__(self, exercise: str = "bicep_curl"):
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(f"{MODEL_PATH} not found.")

        if exercise not in EXERCISES:
            raise ValueError(f"Unknown exercise: {exercise}")

        self.exercise = exercise
        self.config = EXERCISES[exercise]

        base_options = mp_python.BaseOptions(model_asset_path=MODEL_PATH)

        options = vision.PoseLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_poses=1,
            min_pose_detection_confidence=MIN_DETECTION_CONFIDENCE,
            min_pose_presence_confidence=MIN_PRESENCE_CONFIDENCE,
            min_tracking_confidence=MIN_TRACKING_CONFIDENCE,
        )

        self.landmarker = vision.PoseLandmarker.create_from_options(options)

        # Hysteresis state machine — this is what stops double-counting
        self.stage = "down"
        self.rep_count = 0
        self.current_angle: Optional[float] = None

        # Timing & speed tracking
        self.last_timestamp_ms: Optional[int] = None
        self.last_angle: Optional[float] = None
        self.rep_start_time: Optional[float] = None
        self.rep_end_time: Optional[float] = None
        self.rep_durations: list[float] = []
        self.rep_speeds: list[float] = []  # angular speed deg/s per rep
        self._rep_angle_acc: float = (
            0.0  # cumulative absolute angle change during current rep
        )
        self.frames_since_rep_start: int = 0

        # thresholds (seconds) - tune per exercise/user
        self.thresholds = {
            "too_slow": 2.5,  # >= 2.5s
            "slow": 1.5,  # >=1.5s and <2.5s
            "good": 0.8,  # >=0.8s and <1.5s
            "fast": 0.4,  # >=0.4s and <0.8s
            "too_fast": 0.0,  # <0.4s
        }

        # smoothing: simple exponential smoothing factor for angles to reduce jitter
        self.angle_smooth_alpha = 0.6
        self.smoothed_angle: Optional[float] = None

    # -------------------------------------

    def angle(self, a, b, c) -> float:
        ang = math.degrees(
            math.atan2(c.y - b.y, c.x - b.x) - math.atan2(a.y - b.y, a.x - b.x)
        )

        ang = abs(ang)

        if ang > 180:
            ang = 360 - ang

        return ang

    # -------------------------------------

    def update_rep_state(self, angle: float) -> bool:
        rep_completed = False
        down_angle = self.config["down_angle"]
        up_angle = self.config["up_angle"]

        if self.stage == "down" and angle < up_angle:
            # start of upward phase
            self.stage = "up"

        elif self.stage == "up" and angle > down_angle:
            # returned to down -> full rep cycle completed
            self.stage = "down"
            # check if the movement had sufficient range
            if self._rep_angle_acc >= self.config.get("min_angle_delta", 0):
                self.rep_count += 1
                rep_completed = True
            # else: ignore small twitch
        return rep_completed

    # -------------------------------------

    def classify_rep_by_duration(self, duration: Optional[float]) -> Optional[str]:
        if duration is None:
            return None
        th = self.thresholds
        d = duration
        if d >= th["too_slow"]:
            return "too_slow"
        if d >= th["slow"]:
            return "slow"
        if d >= th["good"]:
            return "good"
        if d >= th["fast"]:
            return "fast"
        return "too_fast"

    # -------------------------------------

    def detect(
        self,
        frame,
        timestamp_ms: int,
    ) -> dict[str, Any]:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self.landmarker.detect_for_video(mp_image, timestamp_ms)

        response = {
            "pose_detected": False,
            "angle": None,
            "angle_velocity": None,
            "smoothed_angle": None,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "rep_completed": False,
            "rep_duration": None,
            "rep_avg_speed": None,
            "rep_classification": None,
            "feedback": None,
            "landmarks": [],
        }

        if not result.pose_landmarks:
            self.last_timestamp_ms = timestamp_ms
            return response

        landmarks = result.pose_landmarks[0]
        a_idx, b_idx, c_idx = self.config["joints"]
        raw_angle = self.angle(landmarks[a_idx], landmarks[b_idx], landmarks[c_idx])

        # smoothing
        if self.smoothed_angle is None:
            self.smoothed_angle = raw_angle
        else:
            self.smoothed_angle = (
                self.angle_smooth_alpha * raw_angle
                + (1 - self.angle_smooth_alpha) * self.smoothed_angle
            )

        t = timestamp_ms / 1000.0

        # per-frame velocity (deg/s)
        angle_velocity = None
        if self.last_angle is not None and self.last_timestamp_ms is not None:
            dt = t - (self.last_timestamp_ms / 1000.0)
            if dt > 0:
                angle_velocity = (self.smoothed_angle - self.last_angle) / dt
            else:
                angle_velocity = 0.0

        # detect rep start: transition down -> up on this frame
        previous_stage = self.stage
        # if we're currently in 'down' state and the smoothed angle crosses up_angle, mark start
        if previous_stage == "down" and self.smoothed_angle < self.config["up_angle"]:
            self.rep_start_time = t
            self._rep_angle_acc = 0.0
            self.frames_since_rep_start = 0

        # accumulate absolute angle change during the rep
        if self.last_angle is not None:
            self._rep_angle_acc += abs(self.smoothed_angle - self.last_angle)
            self.frames_since_rep_start += 1

        # update rep state machine and detect completion
        rep_completed = False
        rep_completed = self.update_rep_state(self.smoothed_angle)

        rep_duration = None
        rep_avg_speed = None
        rep_class = None
        feedback = None

        if rep_completed:
            self.rep_end_time = t
            if self.rep_start_time is not None:
                rep_duration = self.rep_end_time - self.rep_start_time
            else:
                rep_duration = None

            if rep_duration and rep_duration > 0:
                rep_avg_speed = self._rep_angle_acc / rep_duration
            else:
                rep_avg_speed = None

            # store history
            if rep_duration:
                self.rep_durations.append(rep_duration)
            if rep_avg_speed:
                self.rep_speeds.append(rep_avg_speed)

            # classification
            rep_class = self.classify_rep_by_duration(rep_duration)

            # feedback message (instructor style)
            if rep_class in ("good", "fast"):
                feedback = (
                    f"Nice rep — {rep_class.replace('_', ' ')} ({rep_duration:.2f}s)."
                )
            elif rep_class in ("slow", "too_slow"):
                feedback = (
                    f"Slow down and control the movement — last rep {rep_duration:.2f}s; "
                    f"target {self.thresholds['good']}–{self.thresholds['slow']}s."
                )
            elif rep_class == "too_fast":
                feedback = (
                    f"Too fast — control the movement. Last rep {rep_duration:.2f}s; "
                    f"aim for ~{self.thresholds['good']}s per rep."
                )
            else:
                feedback = f"Rep recorded ({rep_duration:.2f}s)."

            # reset per-rep accumulators
            self.rep_start_time = None
            self._rep_angle_acc = 0.0
            self.frames_since_rep_start = 0

        # update last frame info
        self.last_angle = self.smoothed_angle
        self.last_timestamp_ms = timestamp_ms

        # fill response
        response["pose_detected"] = True
        response["angle"] = raw_angle
        response["smoothed_angle"] = self.smoothed_angle
        response["angle_velocity"] = angle_velocity
        response["stage"] = self.stage
        response["rep_count"] = self.rep_count
        response["rep_completed"] = rep_completed
        response["rep_duration"] = rep_duration
        response["rep_avg_speed"] = rep_avg_speed
        response["rep_classification"] = rep_class
        response["feedback"] = feedback

        for lm in landmarks:
            response["landmarks"].append(
                {
                    "x": lm.x,
                    "y": lm.y,
                    "z": lm.z,
                    "visibility": getattr(lm, "visibility", None),
                }
            )

        return response

    # -------------------------------------

    def reset(self):
        self.stage = "down"
        self.rep_count = 0
        self.last_timestamp_ms = None
        self.last_angle = None
        self.rep_start_time = None
        self.rep_end_time = None
        self.rep_durations = []
        self.rep_speeds = []
        self._rep_angle_acc = 0.0
        self.smoothed_angle = None

    # -------------------------------------

    def close(self):
        self.landmarker.close()


# -------------------------------
# Example runtime loop (webcam)
# -------------------------------
if __name__ == "__main__":
    # quick demo: webcam read and print instructor feedback on rep completion
    rc = RepCounter(exercise="bicep_curl")

    cap = cv2.VideoCapture(0)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_ms = int(1000 / fps)

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            timestamp_ms = int(time.time() * 1000)
            out = rc.detect(frame, timestamp_ms)

            # overlay small HUD
            htxt = f"Reps: {out['rep_count']} Stage: {out['stage']}"
            cv2.putText(
                frame, htxt, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2
            )

            if out["pose_detected"]:
                angtxt = f"Angle: {out['angle']:.1f} sm:{out['smoothed_angle']:.1f}"
                cv2.putText(
                    frame,
                    angtxt,
                    (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 0),
                    2,
                )

            if out["rep_completed"]:
                # print feedback and also show on frame
                print(out["feedback"])
                cv2.putText(
                    frame,
                    out["feedback"],
                    (10, 90),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 200, 255),
                    2,
                )

            cv2.imshow("RepCounter", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        rc.close()
