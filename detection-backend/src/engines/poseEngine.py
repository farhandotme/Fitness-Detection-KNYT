import logging
import math
import os
from pathlib import Path
from typing import Optional

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.components.containers.landmark import NormalizedLandmark

logger = logging.getLogger(__name__)

MODEL_PATH = str(
    Path(__file__).resolve().parent.parent
    / "landmark-packages"
    / "pose_landmarker.task"
)

# --- Raw MediaPipe confidence --------------------------------------------
# MediaPipe's own PoseLandmarkerOptions defaults are 0.5 / 0.5 / 0.5. This
# file previously ran all three at 0.35 -- *below* what Google ships by
# default. That's most of why the raw detector was willing to "find a
# pose" in furniture, posters, shadows, a second person in the background,
# etc.: at 0.35 it accepts guesses it isn't even confident about.
#
# We restore the documented defaults here and handle the human/not-human
# decision with the plausibility checks below instead. That split matters:
# it means "reject non-human junk" and "keep finding the real person at
# hard angles" are now two independent knobs instead of one knob you have
# to compromise on.
DEFAULT_MIN_DETECTION_CONFIDENCE = 0.5
DEFAULT_MIN_PRESENCE_CONFIDENCE = 0.5
DEFAULT_MIN_TRACKING_CONFIDENCE = 0.5

MAX_HOLD_FRAMES = 4

# --- Human-plausibility filter -------------------------------------------
# Runs on top of whatever MediaPipe returns, so it can reject a
# technically-above-threshold detection that doesn't actually look like a
# person's torso.
#
# 2-of-4 core landmarks lets a hard side-on angle (where the far
# shoulder/hip is genuinely self-occluded) still pass, while a spurious
# detection on background clutter almost never scores two stable,
# anatomically-placed points.
MIN_CORE_LANDMARKS_VISIBLE = 2
CORE_LANDMARK_VISIBILITY_THRESHOLD = 0.5
MIN_AVERAGE_VISIBILITY = 0.4

# A real torso can't collapse to a single point (a classic symptom of a
# low-confidence fit on non-human clutter) or plausibly fill the entire
# frame. These are deliberately loose -- a backstop against degenerate
# fits, not a precise body-size measurement (normalized x/y aren't on the
# same physical scale unless the frame is square).
MIN_TORSO_FRACTION_OF_FRAME = 0.03
MAX_TORSO_FRACTION_OF_FRAME = 0.9

# --- Temporal jump rejection (VIDEO mode only) ----------------------------
# A real hip-center can't teleport across most of the frame between two
# observations taken a few dozen milliseconds apart -- that's the
# signature of the tracker having latched onto a different object (someone
# walking through the background, a pet, a reflection), not the user
# moving. Expressed as a max normalized-distance fraction per 33ms
# (~30fps) and scaled by how much time has actually passed since the last
# *trusted* observation (which may be several frames back if some were
# held).
MAX_HIP_JUMP_FRACTION_PER_33MS = 0.22


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

_CORE_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)


class PoseEngine:
    def __init__(
        self,
        running_mode: Optional[vision.RunningMode] = None,
        min_detection_confidence: float = DEFAULT_MIN_DETECTION_CONFIDENCE,
        min_presence_confidence: float = DEFAULT_MIN_PRESENCE_CONFIDENCE,
        min_tracking_confidence: float = DEFAULT_MIN_TRACKING_CONFIDENCE,
        min_core_landmarks_visible: int = MIN_CORE_LANDMARKS_VISIBLE,
        core_landmark_visibility_threshold: float = CORE_LANDMARK_VISIBILITY_THRESHOLD,
        min_average_visibility: float = MIN_AVERAGE_VISIBILITY,
        enable_plausibility_filter: bool = True,
        enable_jump_rejection: bool = True,
    ):
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(f"{MODEL_PATH} not found.")

        if running_mode is None:
            running_mode = vision.RunningMode.VIDEO

        self.running_mode = running_mode
        self.min_core_landmarks_visible = min_core_landmarks_visible
        self.core_landmark_visibility_threshold = core_landmark_visibility_threshold
        self.min_average_visibility = min_average_visibility
        self.enable_plausibility_filter = enable_plausibility_filter
        self.enable_jump_rejection = enable_jump_rejection

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
        self._last_trusted_timestamp_ms: Optional[int] = None
        self._last_landmarks: Optional[list[NormalizedLandmark]] = None
        self._missed_frames = 0
        self._last_hip_center: Optional[tuple[float, float]] = None
        self._suspect_jump_streak = 0

        # True when the landmarks most recently returned by detect() were a
        # held/carried-over frame rather than a fresh detection. Rep-
        # counting logic upstream can check this and avoid scoring a rep
        # transition off a frame that wasn't actually freshly observed.
        self.last_frame_was_held = False

    # -- public API ---------------------------------------------------------

    def detect(
        self, frame, timestamp_ms: int = 0
    ) -> Optional[list[NormalizedLandmark]]:
        if frame is None or getattr(frame, "size", 0) == 0:
            return None

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        if self.running_mode == vision.RunningMode.IMAGE:
            return self._detect_image(mp_image)

        return self._detect_video(mp_image, timestamp_ms)

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

    # -- mode-specific detection ---------------------------------------------

    def _detect_image(self, mp_image) -> Optional[list[NormalizedLandmark]]:
        result = self.landmarker.detect(mp_image)
        candidate = result.pose_landmarks[0] if result.pose_landmarks else None

        if (
            candidate is not None
            and self.enable_plausibility_filter
            and not self._looks_human(candidate)
        ):
            logger.debug("Rejected image-mode detection: failed plausibility check.")
            candidate = None

        # IMAGE mode calls are treated as independent photos, not frames of
        # one continuous session, so -- same as the original code -- we
        # never hold a stale detection across calls here.
        self.last_frame_was_held = False
        if candidate is not None:
            self._last_landmarks = candidate
            self._missed_frames = 0
        return candidate

    def _detect_video(
        self, mp_image, timestamp_ms: int
    ) -> Optional[list[NormalizedLandmark]]:
        if (
            self._last_timestamp_ms is not None
            and timestamp_ms <= self._last_timestamp_ms
        ):
            timestamp_ms = self._last_timestamp_ms + 1
        self._last_timestamp_ms = timestamp_ms

        result = self.landmarker.detect_for_video(mp_image, timestamp_ms)
        candidate = result.pose_landmarks[0] if result.pose_landmarks else None

        if (
            candidate is not None
            and self.enable_plausibility_filter
            and not self._looks_human(candidate)
        ):
            logger.debug("Rejected video-frame detection: failed plausibility check.")
            candidate = None

        if candidate is None:
            # Nothing to compare for a jump either way -- don't let a
            # stale "suspect jump" streak carry over into an unrelated
            # rejection reason.
            self._suspect_jump_streak = 0
            return self._hold_or_expire()

        if self.enable_jump_rejection:
            elapsed_since_trusted_ms = (
                None
                if self._last_trusted_timestamp_ms is None
                else timestamp_ms - self._last_trusted_timestamp_ms
            )
            candidate = self._filter_jump(candidate, elapsed_since_trusted_ms)
            if candidate is None:
                return self._hold_or_expire()

        self._last_landmarks = candidate
        self._last_trusted_timestamp_ms = timestamp_ms
        self._missed_frames = 0
        self._last_hip_center = self._hip_center(candidate)
        self.last_frame_was_held = False
        return self._last_landmarks

    def _hold_or_expire(self) -> Optional[list[NormalizedLandmark]]:
        if self._last_landmarks is not None and self._missed_frames < MAX_HOLD_FRAMES:
            self._missed_frames += 1
            self.last_frame_was_held = True
            return self._last_landmarks
        self._last_landmarks = None
        self._missed_frames = 0
        self._last_hip_center = None
        self._last_trusted_timestamp_ms = None
        self.last_frame_was_held = False
        return None

    # -- plausibility & jump filtering ---------------------------------------

    def _looks_human(self, landmarks: list[NormalizedLandmark]) -> bool:
        visibilities = [getattr(lm, "visibility", 0.0) or 0.0 for lm in landmarks]

        core_visible = sum(
            1
            for idx in _CORE_LANDMARKS
            if visibilities[idx] >= self.core_landmark_visibility_threshold
        )
        if core_visible < self.min_core_landmarks_visible:
            return False

        if (sum(visibilities) / len(visibilities)) < self.min_average_visibility:
            return False

        shoulder_mid = _midpoint(landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER])
        hip_mid = _midpoint(landmarks[LEFT_HIP], landmarks[RIGHT_HIP])
        torso_span = _distance(shoulder_mid, hip_mid)

        return MIN_TORSO_FRACTION_OF_FRAME <= torso_span <= MAX_TORSO_FRACTION_OF_FRAME

    def _filter_jump(
        self,
        candidate: list[NormalizedLandmark],
        elapsed_ms: Optional[int],
    ) -> Optional[list[NormalizedLandmark]]:
        new_center = self._hip_center(candidate)

        if self._last_hip_center is None or new_center is None or not elapsed_ms:
            self._suspect_jump_streak = 0
            return candidate

        max_jump = MAX_HIP_JUMP_FRACTION_PER_33MS * max(elapsed_ms, 1) / 33.0
        if _distance(self._last_hip_center, new_center) <= max_jump:
            self._suspect_jump_streak = 0
            return candidate

        # Sudden large displacement: more likely the tracker latched onto a
        # different object than the user teleporting. Require it to
        # persist for one more frame before trusting it -- real fast
        # motion (a jumping jack, a burpee drop) still shows up a frame
        # later, while a one-off glitch usually doesn't.
        self._suspect_jump_streak += 1
        if self._suspect_jump_streak >= 2:
            self._suspect_jump_streak = 0
            return candidate

        logger.debug("Rejected video-frame detection: implausible hip-center jump.")
        return None

    @staticmethod
    def _hip_center(
        landmarks: list[NormalizedLandmark],
    ) -> Optional[tuple[float, float]]:
        return _midpoint(landmarks[LEFT_HIP], landmarks[RIGHT_HIP])


def _midpoint(a: NormalizedLandmark, b: NormalizedLandmark) -> tuple[float, float]:
    return ((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])
