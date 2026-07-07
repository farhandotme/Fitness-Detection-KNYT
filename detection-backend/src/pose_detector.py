import math
import os
from typing import Any

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
# Rep only counts on a full down -> up -> down cycle, not a single crossing.
EXERCISES = {
    "bicep_curl": {
        "joints": (LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST),
        "down_angle": 160,
        "up_angle": 50,
    },
    "squat": {
        "joints": (LEFT_HIP, LEFT_KNEE, LEFT_ANKLE),
        "down_angle": 160,
        "up_angle": 90,
    },
    "pushup": {
        "joints": (LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST),
        "down_angle": 160,
        "up_angle": 70,
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
        self.current_angle = None

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
            self.stage = "up"

        elif self.stage == "up" and angle > down_angle:
            self.stage = "down"
            self.rep_count += 1
            rep_completed = True

        return rep_completed

    # -------------------------------------

    def detect(
        self,
        frame,
        timestamp_ms: int,
    ) -> dict[str, Any]:

        rgb = cv2.cvtColor(
            frame,
            cv2.COLOR_BGR2RGB,
        )

        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=rgb,
        )

        result = self.landmarker.detect_for_video(
            mp_image,
            timestamp_ms,
        )

        response = {
            "pose_detected": False,
            "angle": None,
            "stage": self.stage,
            "rep_count": self.rep_count,
            "rep_completed": False,
            "landmarks": [],
        }

        if not result.pose_landmarks:
            return response

        landmarks = result.pose_landmarks[0]

        a_idx, b_idx, c_idx = self.config["joints"]

        angle = self.angle(
            landmarks[a_idx],
            landmarks[b_idx],
            landmarks[c_idx],
        )

        self.current_angle = angle

        rep_completed = self.update_rep_state(angle)

        response["pose_detected"] = True
        response["angle"] = angle
        response["stage"] = self.stage
        response["rep_count"] = self.rep_count
        response["rep_completed"] = rep_completed

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

    # -------------------------------------

    def close(self):

        self.landmarker.close()
