import os
from pathlib import Path
from typing import Optional

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.components.containers.landmark import NormalizedLandmark

MODEL_PATH = str(
    Path(__file__).resolve().parent.parent
    / "landmark-packages"
    / "pose_landmarker.task"
)

# Defaults tuned for general rep counting.
DEFAULT_MIN_DETECTION_CONFIDENCE = 0.7
DEFAULT_MIN_PRESENCE_CONFIDENCE = 0.7
DEFAULT_MIN_TRACKING_CONFIDENCE = 0.65

# More forgiving for full-body / farther-away exercises.
FULL_BODY_MIN_DETECTION_CONFIDENCE = 0.6
FULL_BODY_MIN_PRESENCE_CONFIDENCE = 0.6
FULL_BODY_MIN_TRACKING_CONFIDENCE = 0.55

# How many consecutive frames with no detected pose to tolerate.
MAX_HOLD_FRAMES = 4

# Pose landmark indices (MediaPipe BlazePose topology)
NOSE = 0
LEFT_EYE_INNER = 1
LEFT_EYE = 2
LEFT_EYE_OUTER = 3
RIGHT_EYE_INNER = 4
RIGHT_EYE = 5
RIGHT_EYE_OUTER = 6
LEFT_EAR = 7
RIGHT_EAR = 8
MOUTH_LEFT = 9
MOUTH_RIGHT = 10
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
LEFT_HEEL = 29
RIGHT_HEEL = 30
LEFT_FOOT_INDEX = 31
RIGHT_FOOT_INDEX = 32


class PoseEngine:
    """Owns exactly one PoseLandmarker. Call `detect()` once per frame."""

    def __init__(
        self,
        running_mode: Optional[vision.RunningMode] = None,
        min_detection_confidence: float = DEFAULT_MIN_DETECTION_CONFIDENCE,
        min_presence_confidence: float = DEFAULT_MIN_PRESENCE_CONFIDENCE,
        min_tracking_confidence: float = DEFAULT_MIN_TRACKING_CONFIDENCE,
    ):
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(f"{MODEL_PATH} not found.")

        if running_mode is None:
            running_mode = vision.RunningMode.VIDEO
        self.running_mode = running_mode

        base_options = mp_python.BaseOptions(model_asset_path=MODEL_PATH)
        options = vision.PoseLandmarkerOptions(
            base_options=base_options,
            running_mode=running_mode,
            num_poses=1,
            min_pose_detection_confidence=min_detection_confidence,
            min_pose_presence_confidence=min_presence_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self.landmarker = vision.PoseLandmarker.create_from_options(options)

        self._last_timestamp_ms: Optional[int] = None
        self._last_landmarks: Optional[list[NormalizedLandmark]] = None
        self._missed_frames = 0

    def detect(
        self, frame, timestamp_ms: int = 0
    ) -> Optional[list[NormalizedLandmark]]:
        """Run pose detection once. Returns landmarks or None."""

        if frame is None or getattr(frame, "size", 0) == 0:
            return None

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        if self.running_mode == vision.RunningMode.IMAGE:
            result = self.landmarker.detect(mp_image)
            if result.pose_landmarks:
                self._last_landmarks = result.pose_landmarks[0]
                self._missed_frames = 0
                return self._last_landmarks
            return None

        if (
            self._last_timestamp_ms is not None
            and timestamp_ms <= self._last_timestamp_ms
        ):
            timestamp_ms = self._last_timestamp_ms + 1
        self._last_timestamp_ms = timestamp_ms

        result = self.landmarker.detect_for_video(mp_image, timestamp_ms)

        if not result.pose_landmarks:
            if (
                self._last_landmarks is not None
                and self._missed_frames < MAX_HOLD_FRAMES
            ):
                self._missed_frames += 1
                return self._last_landmarks
            self._last_landmarks = None
            self._missed_frames = 0
            return None

        self._last_landmarks = result.pose_landmarks[0]
        self._missed_frames = 0
        return self._last_landmarks

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
