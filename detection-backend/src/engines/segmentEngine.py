import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

# Resolved relative to THIS FILE, not the process's working directory.
# The old "./src/landmark-packages/..." path only worked if the server
# happened to be launched from exactly the detection-backend/ folder --
# any other launch cwd (a different terminal dir, a process manager, a
# different WORKDIR) made os.path.exists() silently return False with no
# error, so segmentation quietly degraded with zero indication why.
MODEL_PATH = str(
    Path(__file__).resolve().parent.parent
    / "landmark-packages"
    / "selfie_multiclass.tflite"
)

BACKGROUND = 0
HAIR = 1
BODY_SKIN = 2
FACE_SKIN = 3
CLOTHES = 4
OTHER = 5

log = logging.getLogger(__name__)


class SegmentEngine:
    """Owns one ImageSegmenter. Call `segment()` per still frame."""

    def __init__(self):
        self.available = os.path.exists(MODEL_PATH)
        log.warning(
            "SegmentEngine: model %s at %s",
            "FOUND" if self.available else "NOT FOUND",
            MODEL_PATH,
        )
        self.segmenter = None

        if self.available:
            base_options = mp_python.BaseOptions(model_asset_path=MODEL_PATH)
            options = vision.ImageSegmenterOptions(
                base_options=base_options,
                output_category_mask=True,
            )
            self.segmenter = vision.ImageSegmenter.create_from_options(options)

    def segment(self, frame_rgb: np.ndarray) -> Optional[np.ndarray]:
        """Returns a HxW uint8 category mask, or None if the model isn't
        installed / segmentation failed."""
        if not self.available or self.segmenter is None:
            return None

        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
        result = self.segmenter.segment(mp_image)

        if result.category_mask is None:
            return None

        return result.category_mask.numpy_view()

    def close(self):
        if self.segmenter is not None:
            self.segmenter.close()
