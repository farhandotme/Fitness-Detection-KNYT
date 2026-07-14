
import os
from pathlib import Path
from typing import Optional

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.components.containers.landmark import NormalizedLandmark

MODEL_PATH = str(Path(__file__).resolve().parent.parent / "landmark-packages" / "pose_landmarker.task")

# Defaults tuned for close-up rep counting (squats/curls/pushups), where the
# person fills most of the frame and landmarks are large and sharp.
DEFAULT_MIN_DETECTION_CONFIDENCE = 0.75
DEFAULT_MIN_PRESENCE_CONFIDENCE = 0.75
DEFAULT_MIN_TRACKING_CONFIDENCE = 0.7

# How many consecutive frames with *no* detected pose we tolerate before
# reporting "no person" to callers. MediaPipe's tracker briefly drops the
# pose on fast/blurry motion (very common mid-rep, especially on squats
# where the whole body moves quickly) even though the person never left
# the frame. Re-using the last good landmarks for a few frames avoids the
# analyzers seeing a false "no person detected" / losing calibration every
# time that happens, while still correctly reporting "no person" if they
# actually step out of frame.
MAX_HOLD_FRAMES = 6

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
        running_mode: vision.RunningMode = vision.RunningMode.VIDEO,
        min_detection_confidence: float = DEFAULT_MIN_DETECTION_CONFIDENCE,
        min_presence_confidence: float = DEFAULT_MIN_PRESENCE_CONFIDENCE,
        min_tracking_confidence: float = DEFAULT_MIN_TRACKING_CONFIDENCE,
    ):
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(f"{MODEL_PATH} not found.")

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

        # MediaPipe's VIDEO mode requires strictly increasing timestamps.
        self._last_timestamp_ms: Optional[int] = None

        # Short-term hold buffer for brief detection dropouts (see
        # MAX_HOLD_FRAMES above). Only meaningful in VIDEO mode.
        self._last_landmarks: Optional[list[NormalizedLandmark]] = None
        self._missed_frames = 0

    def detect(
        self, frame, timestamp_ms: int = 0
    ) -> Optional[list[NormalizedLandmark]]:
        """Run pose detection once. Returns the 33-point landmark list, or
        None if no person was detected (or the frame/timestamp was invalid).
        `timestamp_ms` is ignored in IMAGE mode (single still photos)."""

        if frame is None or frame.size == 0:
            return None

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        if self.running_mode == vision.RunningMode.IMAGE:
            result = self.landmarker.detect(mp_image)
            return result.pose_landmarks[0] if result.pose_landmarks else None

        # Guard against non-monotonic / duplicate timestamps, which would
        # otherwise raise inside the MediaPipe C++ runtime and kill the
        # websocket loop.
        if (
            self._last_timestamp_ms is not None
            and timestamp_ms <= self._last_timestamp_ms
        ):
            timestamp_ms = self._last_timestamp_ms + 1
        self._last_timestamp_ms = timestamp_ms

        result = self.landmarker.detect_for_video(mp_image, timestamp_ms)

        if not result.pose_landmarks:
            # Momentary miss — reuse the last good frame for a short window
            # instead of instantly reporting "no person".
            if (
                self._last_landmarks is not None
                and self._missed_frames < MAX_HOLD_FRAMES
            ):
                self._missed_frames += 1
                return self._last_landmarks
            self._last_landmarks = None
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
