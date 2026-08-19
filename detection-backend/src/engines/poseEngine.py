import math
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

# ---------------------------------------------------------------------
# BASE CONFIDENCE (Restored for Distance Detection)
# ---------------------------------------------------------------------
# Restored to 0.5. This is required to detect people who are far away.
# If this is higher, distant people become invisible.
DEFAULT_MIN_DETECTION_CONFIDENCE = 0.5
DEFAULT_MIN_PRESENCE_CONFIDENCE = 0.5
DEFAULT_MIN_TRACKING_CONFIDENCE = 0.5

MAX_HOLD_FRAMES = 4

# ---------------------------------------------------------------------
# HUMAN SHAPE FILTER
# ---------------------------------------------------------------------
# Visibility requirements lowered so a distant or slightly turned human
# is still counted.
MIN_CORE_VISIBILITY = 0.5
MIN_LIMB_VISIBILITY = 0.4
MIN_HEAD_VISIBILITY = 0.4
MIN_LIMB_VISIBLE_COUNT = 2

# Minimum sizes drastically reduced so people far away from the camera
# are not accidentally filtered out.
MIN_SHOULDER_WIDTH = 0.015
MIN_HIP_WIDTH = 0.015
MIN_TORSO_LENGTH = 0.03

# Proportions: Wide enough to allow natural leaning/bending,
# but strict enough to block bizarre, hallucinated object proportions.
MIN_TORSO_TO_SHOULDER_RATIO = 0.5
MAX_TORSO_TO_SHOULDER_RATIO = 3.5

PERSON_CONFIRM_FRAMES = 4  # Reduced from 5 to 4 for slightly faster lock-on

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


def _landmark_visibility(landmark) -> float:
    v = getattr(landmark, "visibility", None)
    return v if v is not None else 0.0


def is_plausible_person(landmarks) -> bool:
    if not landmarks:
        return False

    # 1. Head Check: A shadow or chair rarely has a face. We just need *one*
    # head point (ear, eye, nose) to be somewhat visible.
    head_visible = any(
        _landmark_visibility(landmarks[i]) >= MIN_HEAD_VISIBILITY
        for i in (NOSE, LEFT_EYE, RIGHT_EYE, LEFT_EAR, RIGHT_EAR)
    )
    if not head_visible:
        return False

    # 2. Core Check: Shoulders and hips must exist.
    core = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)
    if any(_landmark_visibility(landmarks[i]) < MIN_CORE_VISIBILITY for i in core):
        return False

    # 3. Limb Check: Must have at least 2 limb points visible.
    limb_visible = sum(
        1
        for i in (
            LEFT_KNEE,
            RIGHT_KNEE,
            LEFT_ANKLE,
            RIGHT_ANKLE,
            LEFT_ELBOW,
            RIGHT_ELBOW,
        )
        if _landmark_visibility(landmarks[i]) >= MIN_LIMB_VISIBILITY
    )
    if limb_visible < MIN_LIMB_VISIBLE_COUNT:
        return False

    l_sh, r_sh = landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER]
    l_hip, r_hip = landmarks[LEFT_HIP], landmarks[RIGHT_HIP]

    # 4. Size Check: Allows very small bounds for distant people.
    shoulder_width = math.hypot(l_sh.x - r_sh.x, l_sh.y - r_sh.y)
    hip_width = math.hypot(l_hip.x - r_hip.x, l_hip.y - r_hip.y)
    if shoulder_width < MIN_SHOULDER_WIDTH or hip_width < MIN_HIP_WIDTH:
        return False

    mid_shoulder = ((l_sh.x + r_sh.x) / 2.0, (l_sh.y + r_sh.y) / 2.0)
    mid_hip = ((l_hip.x + r_hip.x) / 2.0, (l_hip.y + r_hip.y) / 2.0)
    torso_length = math.hypot(
        mid_shoulder[0] - mid_hip[0], mid_shoulder[1] - mid_hip[1]
    )
    if torso_length < MIN_TORSO_LENGTH:
        return False

    # 5. Proportion Check: Filters out tall skinny objects (like poles or doorframes)
    # that the model mistakes for a torso.
    ratio = torso_length / max(shoulder_width, 1e-6)
    if ratio < MIN_TORSO_TO_SHOULDER_RATIO or ratio > MAX_TORSO_TO_SHOULDER_RATIO:
        return False

    return True


class PoseEngine:
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

        self._plausible_streak = 0
        self._person_confirmed = False

    def detect(
        self, frame, timestamp_ms: int = 0
    ) -> Optional[list[NormalizedLandmark]]:
        if frame is None or getattr(frame, "size", 0) == 0:
            return None

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        if self.running_mode == vision.RunningMode.IMAGE:
            result = self.landmarker.detect(mp_image)
            raw = result.pose_landmarks[0] if result.pose_landmarks else None
            if raw is not None and is_plausible_person(raw):
                self._last_landmarks = raw
                self._missed_frames = 0
                return raw
            return None

        if (
            self._last_timestamp_ms is not None
            and timestamp_ms <= self._last_timestamp_ms
        ):
            timestamp_ms = self._last_timestamp_ms + 1
        self._last_timestamp_ms = timestamp_ms

        result = self.landmarker.detect_for_video(mp_image, timestamp_ms)
        raw = result.pose_landmarks[0] if result.pose_landmarks else None
        return self._gate_video_frame(raw)

    def _gate_video_frame(
        self, raw: Optional[list[NormalizedLandmark]]
    ) -> Optional[list[NormalizedLandmark]]:
        if raw is not None and is_plausible_person(raw):
            self._plausible_streak += 1
            self._missed_frames = 0
            self._last_landmarks = raw
            if self._plausible_streak >= PERSON_CONFIRM_FRAMES:
                self._person_confirmed = True
            return self._last_landmarks if self._person_confirmed else None

        self._plausible_streak = 0
        if (
            self._person_confirmed
            and self._last_landmarks is not None
            and self._missed_frames < MAX_HOLD_FRAMES
        ):
            self._missed_frames += 1
            return self._last_landmarks

        self._person_confirmed = False
        self._last_landmarks = None
        self._missed_frames = 0
        return None

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
