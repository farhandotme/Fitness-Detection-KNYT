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

MODEL_PATH = "hand_landmarker.task"

NUM_HANDS = 2
MIN_DETECTION_CONFIDENCE = 0.6
MIN_PRESENCE_CONFIDENCE = 0.6
MIN_TRACKING_CONFIDENCE = 0.6

WRIST = 0

THUMB_TIP = 4
THUMB_MCP = 2
PINKY_MCP = 17

TIP_IDS = [4, 8, 12, 16, 20]
PIP_IDS = [2, 6, 10, 14, 18]


class HandDetector:
    def __init__(self):

        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(f"{MODEL_PATH} not found.")

        base_options = mp_python.BaseOptions(model_asset_path=MODEL_PATH)

        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_hands=NUM_HANDS,
            min_hand_detection_confidence=MIN_DETECTION_CONFIDENCE,
            min_hand_presence_confidence=MIN_PRESENCE_CONFIDENCE,
            min_tracking_confidence=MIN_TRACKING_CONFIDENCE,
        )

        self.landmarker = vision.HandLandmarker.create_from_options(options)

    # -------------------------------------

    def distance(self, p1, p2):

        return math.hypot(
            p1.x - p2.x,
            p1.y - p2.y,
        )

    # -------------------------------------

    def count_fingers(self, landmarks):

        fingers = []

        thumb_tip_dist = self.distance(
            landmarks[THUMB_TIP],
            landmarks[PINKY_MCP],
        )

        thumb_mcp_dist = self.distance(
            landmarks[THUMB_MCP],
            landmarks[PINKY_MCP],
        )

        fingers.append(thumb_tip_dist > thumb_mcp_dist)

        for tip, pip in zip(TIP_IDS[1:], PIP_IDS[1:]):

            fingers.append(landmarks[tip].y < landmarks[pip].y)

        return fingers

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
            "hands": [],
            "total_fingers": 0,
        }

        if not result.hand_landmarks:
            return response

        for i, landmarks in enumerate(result.hand_landmarks):

            handedness = result.handedness[i][0].category_name

            fingers = self.count_fingers(landmarks)

            finger_count = sum(fingers)

            response["total_fingers"] += finger_count

            hand = {
                "hand": handedness,
                "finger_count": finger_count,
                "fingers": {
                    "thumb": bool(fingers[0]),
                    "index": bool(fingers[1]),
                    "middle": bool(fingers[2]),
                    "ring": bool(fingers[3]),
                    "pinky": bool(fingers[4]),
                },
                "landmarks": [],
            }

            for lm in landmarks:

                hand["landmarks"].append(
                    {
                        "x": lm.x,
                        "y": lm.y,
                        "z": lm.z,
                    }
                )

            response["hands"].append(hand)

        return response

    # -------------------------------------

    def close(self):

        self.landmarker.close()
