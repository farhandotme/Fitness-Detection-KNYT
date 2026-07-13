import base64
import time

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from mediapipe.tasks.python import vision

from src.detectors.body_analysis import BodyScanError, analyze_body
from src.engines.poseEngine import PoseEngine
from src.engines.segmentEngine import SegmentEngine

router = APIRouter()

# Both models are expensive to load — create once at import time and reuse
# across requests, same as the pattern used for the websocket sessions.
#
# IMAGE mode + lower confidence thresholds: a full-body-distance photo has
# much lower per-landmark confidence than the close-up rep-counting frames
# the default thresholds were tuned for (the person occupies far less of
# the frame), so the default 0.75 thresholds were rejecting valid detections.
_pose_engine = PoseEngine(
    running_mode=vision.RunningMode.IMAGE,
    min_detection_confidence=0.4,
    min_presence_confidence=0.4,
)
_segment_engine = SegmentEngine()


class BodyAnalysisRequest(BaseModel):
    image: str = Field(..., description="Base64 data URL or raw base64 JPEG/PNG")
    height_cm: float = Field(..., ge=100, le=250)
    weight_kg: float | None = Field(None, ge=20, le=300)


def _decode_frame(raw: str):
    if "," in raw:
        raw = raw.split(",")[1]

    image_bytes = base64.b64decode(raw)
    np_array = np.frombuffer(image_bytes, dtype=np.uint8)
    frame = cv2.imdecode(np_array, cv2.IMREAD_COLOR)

    if frame is None:
        raise HTTPException(400, "Couldn't decode the image — try capturing again.")

    return frame


@router.post("/body-analysis")
async def body_analysis(payload: BodyAnalysisRequest):
    frame = _decode_frame(payload.image)

    timestamp = int(time.time() * 1000)
    landmarks = _pose_engine.detect(frame, timestamp)

    if landmarks is None:
        raise HTTPException(
            400,
            "No person detected — make sure you're clearly visible and well-lit.",
        )

    frame_rgb = frame[:, :, ::-1]
    mask = _segment_engine.segment(np.ascontiguousarray(frame_rgb))

    try:
        result = analyze_body(landmarks, frame, payload.height_cm, mask, payload.weight_kg)
    except BodyScanError as e:
        raise HTTPException(400, str(e))

    result["segmentation_available"] = _segment_engine.available
    return result
