"""
Shared MediaPipe Pose Landmarker wrapper.

Why this file exists
---------------------
The old implementation created a *separate* PoseLandmarker instance for the
left arm and another one for the right arm, and "both arms" mode ran BOTH of
those detectors on the *same frame* — i.e. it ran the (expensive) pose model
twice per frame for no reason, doubling latency and doing twice the work for
identical output.

`PoseEngine` runs the model exactly once per frame. Anything that needs pose
landmarks (single-arm or both-arm curl analysis) shares one engine instance
and reads the same landmark list.
"""

import os
from typing import Optional

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.components.containers.landmark import NormalizedLandmark

MODEL_PATH = "./src/landmark-packages/pose_landmarker.task"

MIN_DETECTION_CONFIDENCE = 0.5
MIN_PRESENCE_CONFIDENCE = 0.5
MIN_TRACKING_CONFIDENCE = 0.5

# Pose landmark indices (MediaPipe BlazePose topology)
NOSE = 0
LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_ELBOW = 13
RIGHT_ELBOW = 14
LEFT_WRIST = 15
RIGHT_WRIST = 16
LEFT_HIP = 23
RIGHT_HIP = 24


class PoseEngine:
    """Owns exactly one PoseLandmarker. Call `detect()` once per frame."""

    def __init__(self):
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(f"{MODEL_PATH} not found.")

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

        # MediaPipe's VIDEO mode requires strictly increasing timestamps.
        self._last_timestamp_ms: Optional[int] = None

    def detect(self, frame, timestamp_ms: int) -> Optional[list[NormalizedLandmark]]:
        """Run pose detection once. Returns the 33-point landmark list, or
        None if no person was detected (or the frame/timestamp was invalid)."""

        # Guard against non-monotonic / duplicate timestamps, which would
        # otherwise raise inside the MediaPipe C++ runtime and kill the
        # websocket loop.
        if (
            self._last_timestamp_ms is not None
            and timestamp_ms <= self._last_timestamp_ms
        ):
            timestamp_ms = self._last_timestamp_ms + 1
        self._last_timestamp_ms = timestamp_ms

        if frame is None or frame.size == 0:
            return None

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self.landmarker.detect_for_video(mp_image, timestamp_ms)

        if not result.pose_landmarks:
            return None

        return result.pose_landmarks[0]

    def close(self):
        self.landmarker.close()

    @staticmethod
    def landmarks_to_json(landmarks: list[NormalizedLandmark]) -> list[dict]:
        return [
            {
                "x": lm.x,
                "y": lm.y,
                "z": lm.z,
                "visibility": getattr(lm, "visibility", None),
            }
            for lm in landmarks
        ]
