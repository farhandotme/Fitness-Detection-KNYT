"""
Shared MediaPipe Image Segmenter wrapper — the body-scan counterpart to
PoseEngine.

Why this exists
----------------
Pose landmarks alone (joint positions) cannot tell you anything about a
person's actual body outline — two people with identical skeletons can have
very different amounts of soft tissue between those joints. To make any
honest claim about torso/waist width or to sample "where the hair is" vs
"where the skin is", we need the actual pixel silhouette, not just 33 dots.

`SegmentEngine` wraps MediaPipe's selfie multiclass segmenter, which
outputs a per-pixel category mask:

    0 = background
    1 = hair
    2 = body-skin
    3 = face-skin
    4 = clothes
    5 = other (accessories, etc.)

Model file
----------
This model is NOT bundled in this repo (it's a separate download from the
one used for pose_landmarker.task). Grab it once and drop it next to the
other `.task`/`.tflite` files:

    curl -L -o src/landmark-packages/selfie_multiclass.tflite \\
      https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite

If the file isn't present, `SegmentEngine.available` is False and callers
should fall back gracefully (see body_analysis.py) instead of crashing —
the scan still works, just with lower-fidelity waist/hair/skin estimates.
"""

import os
from typing import Optional

import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

MODEL_PATH = "./src/landmark-packages/selfie_multiclass.tflite"

BACKGROUND = 0
HAIR = 1
BODY_SKIN = 2
FACE_SKIN = 3
CLOTHES = 4
OTHER = 5


class SegmentEngine:
    """Owns one ImageSegmenter. Call `segment()` per still frame."""

    def __init__(self):
        self.available = os.path.exists(MODEL_PATH)
        self.segmenter: Optional[vision.ImageSegmenter] = None

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
