import math
import os
from typing import Any, Optional

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

MODEL_PATH = "./src/landmark-packages/pose_landmarker.task"

MIN_DETECTION_CONFIDENCE = 0.6
MIN_PRESENCE_CONFIDENCE = 0.6
MIN_TRACKING_CONFIDENCE = 0.6
MIN_LANDMARK_VISIBILITY = 0.5

LEFT_SHOULDER = 11
LEFT_ELBOW = 13
LEFT_WRIST = 15


class bicep_curl:
    def __init__(self):
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(f"{MODEL_PATH} not found.")

        self.config = {
            "joints": (LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST),
            "down_angle": 160,
            "up_angle": 50,
            "min_angle_delta": 25,
            "min_rep_duration": 0.25,
        }

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

        self.stage = "down"
        self.rep_count = 0
        self.current_angle: Optional[float] = None

        self.last_timestamp_ms: Optional[int] = None
        self.last_angle: Optional[float] = None
        self.rep_start_time: Optional[float] = None
        self.rep_end_time: Optional[float] = None
        self.rep_durations: list[float] = []
        self.rep_speeds: list[float] = []
        self._rep_angle_acc: float = 0.0
        self.frames_since_rep_start: int = 0

        self.thresholds = {
            "too_slow": 2.5,
            "slow": 1.5,
            "good": 0.8,
            "fast": 0.4,
            "too_fast": 0.0,
        }

        self.angle_smooth_alpha = 0.6
        self.smoothed_angle: Optional[float] = None

    def angle(self, a, b, c) -> float:
        ang = math.degrees(
            math.atan2(c.y - b.y, c.x - b.x) - math.atan2(a.y - b.y, a.x - b.x)
        )
        ang = abs(ang)
        if ang > 180:
            ang = 360 - ang
        return ang

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

    def update_rep_state(self, angle: float) -> bool:
        rep_completed = False
        down_angle = self.config["down_angle"]
        up_angle = self.config["up_angle"]

        if self.stage == "down" and angle < up_angle:
            self.stage = "up"
        elif self.stage == "up" and angle > down_angle:
            self.stage = "down"
            if self._rep_angle_acc >= self.config.get("min_angle_delta", 0):
                rep_completed = True
                self.rep_count += 1
        return rep_completed

    def detect(self, frame, timestamp_ms: int) -> dict[str, Any]:
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
            "low_visibility": False,
            "landmarks": [],
        }

        if not result.pose_landmarks:
            self.last_timestamp_ms = timestamp_ms
            return response

        landmarks = result.pose_landmarks[0]
        a_idx, b_idx, c_idx = self.config["joints"]
        a, b, c = landmarks[a_idx], landmarks[b_idx], landmarks[c_idx]

        visibilities = [getattr(p, "visibility", 1.0) for p in (a, b, c)]
        if any(v is not None and v < MIN_LANDMARK_VISIBILITY for v in visibilities):
            response["pose_detected"] = True
            response["angle"] = self.last_angle
            response["smoothed_angle"] = self.smoothed_angle
            response["stage"] = self.stage
            response["rep_count"] = self.rep_count
            response["low_visibility"] = True
            response["landmarks"] = [
                {
                    "x": lm.x,
                    "y": lm.y,
                    "z": lm.z,
                    "visibility": getattr(lm, "visibility", None),
                }
                for lm in landmarks
            ]
            self.last_timestamp_ms = timestamp_ms
            return response

        raw_angle = self.angle(a, b, c)

        if self.smoothed_angle is None:
            self.smoothed_angle = raw_angle
        else:
            self.smoothed_angle = (
                self.angle_smooth_alpha * raw_angle
                + (1 - self.angle_smooth_alpha) * self.smoothed_angle
            )

        t = timestamp_ms / 1000.0

        angle_velocity = None
        if self.last_angle is not None and self.last_timestamp_ms is not None:
            dt = t - (self.last_timestamp_ms / 1000.0)
            if dt > 0:
                angle_velocity = (self.smoothed_angle - self.last_angle) / dt

        if self.stage == "down" and self.smoothed_angle < self.config["up_angle"]:
            self.rep_start_time = t
            self._rep_angle_acc = 0.0
            self.frames_since_rep_start = 0

        if self.last_angle is not None:
            self._rep_angle_acc += abs(self.smoothed_angle - self.last_angle)
            self.frames_since_rep_start += 1

        rep_completed = self.update_rep_state(self.smoothed_angle)

        rep_duration = None
        rep_avg_speed = None
        rep_class = None
        feedback = None

        if rep_completed:
            self.rep_end_time = t
            if self.rep_start_time is not None:
                rep_duration = self.rep_end_time - self.rep_start_time

            if rep_duration and rep_duration > 0:
                rep_avg_speed = self._rep_angle_acc / rep_duration

            if rep_duration is not None and rep_duration >= self.config.get(
                "min_rep_duration", 0
            ):
                self.rep_durations.append(rep_duration)
                if rep_avg_speed is not None:
                    self.rep_speeds.append(rep_avg_speed)
                rep_class = self.classify_rep_by_duration(rep_duration)

                if rep_class in ("good", "fast"):
                    feedback = f"Nice rep — {rep_class.replace('_', ' ')} ({rep_duration:.2f}s)."
                elif rep_class in ("slow", "too_slow"):
                    feedback = f"Slow down and control it — {rep_duration:.2f}s."
                elif rep_class == "too_fast":
                    feedback = f"Too fast — control the movement ({rep_duration:.2f}s)."
                else:
                    feedback = f"Rep recorded ({rep_duration:.2f}s)."
            else:
                rep_completed = False
                self.rep_count -= 1 if self.rep_count > 0 else 0

            self.rep_start_time = None
            self._rep_angle_acc = 0.0
            self.frames_since_rep_start = 0

        self.last_angle = self.smoothed_angle
        self.last_timestamp_ms = timestamp_ms

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
        response["landmarks"] = [
            {
                "x": lm.x,
                "y": lm.y,
                "z": lm.z,
                "visibility": getattr(lm, "visibility", None),
            }
            for lm in landmarks
        ]
        return response

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

    def close(self):
        self.landmarker.close()
