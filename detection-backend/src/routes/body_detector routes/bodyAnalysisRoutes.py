import base64

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from mediapipe.tasks.python import vision

from src.detectors.body_analysis import BodyScanError, _compute_px_per_cm
from src.detectors.body_analysis_multiview import ViewInput, analyze_body_multiview
from src.engines.face_analysis import FaceEngine, analyze_face
from src.engines.poseEngine import PoseEngine
from src.engines.segmentEngine import SegmentEngine

router = APIRouter()
_pose_engine = PoseEngine(
    running_mode=vision.RunningMode.IMAGE,
    min_detection_confidence=0.4,
    min_presence_confidence=0.4,
)
_segment_engine = SegmentEngine()
_face_engine = FaceEngine()  # gracefully no-ops if face_landmarker.task isn't installed


class BodyAnalysisRequest(BaseModel):
    front: str = Field(..., description="Base64 data URL or raw base64 JPEG/PNG — required")
    left: str | None = Field(None, description="Left-profile photo — optional but recommended")
    right: str | None = Field(None, description="Right-profile photo — optional but recommended")
    back: str | None = Field(None, description="Back photo — optional")
    height_cm: float = Field(
        ...,
        ge=100,
        le=250,
        description="The ONLY number you need to type — everything else is measured from the photos.",
    )


def _decode_frame(raw: str):
    if "," in raw:
        raw = raw.split(",")[1]

    image_bytes = base64.b64decode(raw)
    np_array = np.frombuffer(image_bytes, dtype=np.uint8)
    frame = cv2.imdecode(np_array, cv2.IMREAD_COLOR)

    if frame is None:
        raise HTTPException(400, "Couldn't decode an image — try capturing again.")

    return frame


def _build_view(raw: str | None, required: bool, label: str) -> ViewInput | None:
    if raw is None:
        if required:
            raise HTTPException(400, f"Missing required {label} photo.")
        return None

    frame = _decode_frame(raw)
    landmarks = _pose_engine.detect(frame)

    if landmarks is None:
        if required:
            raise HTTPException(
                400,
                f"No person detected in the {label} photo — make sure you're "
                "clearly visible and well-lit.",
            )
        # Optional view with no detection — silently dropped, the analysis
        # function degrades gracefully without it.
        return None

    frame_rgb = frame[:, :, ::-1]
    mask = _segment_engine.segment(np.ascontiguousarray(frame_rgb))
    return ViewInput(landmarks=landmarks, frame_bgr=frame, mask=mask)


@router.post("/body-analysis")
async def body_analysis(payload: BodyAnalysisRequest):
    front = _build_view(payload.front, required=True, label="front")
    left = _build_view(payload.left, required=False, label="left")
    right = _build_view(payload.right, required=False, label="right")
    back = _build_view(payload.back, required=False, label="back")

    # Face analysis rides on the SAME front photo + the SAME pixel scale
    # factor the body measurements use (same image = same px_per_cm), so
    # head size comes out in real cm instead of a second independent guess.
    face_result = None
    if _face_engine.available:
        front_frame = _decode_frame(payload.front)
        h, w = front_frame.shape[:2]
        try:
            px_per_cm = _compute_px_per_cm(front.landmarks, w, h, payload.height_cm)
        except BodyScanError:
            px_per_cm = None
        face_result = analyze_face(front_frame, _face_engine, px_per_cm)

    try:
        result = analyze_body_multiview(
            height_cm=payload.height_cm,
            front=front,
            left=left,
            right=right,
            back=back,
            face_result=face_result,
        )
    except BodyScanError as e:
        raise HTTPException(400, str(e))

    result["segmentation_available"] = _segment_engine.available
    result["face_analysis_available"] = _face_engine.available
    return result
