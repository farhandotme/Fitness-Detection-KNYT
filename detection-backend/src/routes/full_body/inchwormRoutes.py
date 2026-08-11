"""
WebSocket Router for Inchworm Exercise.

Endpoints supported:
  - ws://localhost:8000/ws/inchworm
  - ws://localhost:8000/ws/inchworm_exercise
"""

import base64
import json
import time
import cv2
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.detectors.full_body.inchworm import InchwormSession

router = APIRouter()


def _decode_frame(message: dict) -> np.ndarray | None:
    """Decodes binary frame bytes or base64 text payload into OpenCV matrix."""
    if "bytes" in message and message["bytes"]:
        np_arr = np.frombuffer(message["bytes"], np.uint8)
        return cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

    if "text" in message and message["text"]:
        text_data = message["text"].strip()
        base64_str = None

        if text_data.startswith("{"):
            try:
                data = json.loads(text_data)
                if data.get("action") == "stop":
                    return None
                base64_str = data.get("image") or data.get("frame") or data.get("data")
            except json.JSONDecodeError:
                return None
        else:
            base64_str = text_data

        if base64_str:
            if "," in base64_str:
                base64_str = base64_str.split(",")[1]
            try:
                img_bytes = base64.b64decode(base64_str)
                np_arr = np.frombuffer(img_bytes, np.uint8)
                return cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            except Exception:
                return None

    return None


@router.websocket("/inchworm")
@router.websocket("/inchworm_exercise")
async def inchworm_stream(websocket: WebSocket):
    """
    WebSocket stream handler for Inchworm exercise.
    Accepts incoming stream and parses query parameters.
    """
    # 1. IMMEDIATELY accept connection to avoid 403 / 422 handshake errors
    await websocket.accept()

    params = websocket.query_params

    try:
        target_reps = int(params.get("target_reps", 10))
    except (ValueError, TypeError):
        target_reps = 10

    try:
        target_sets = int(params.get("target_sets", 1))
    except (ValueError, TypeError):
        target_sets = 1

    try:
        set_number = int(params.get("set_number", 1))
    except (ValueError, TypeError):
        set_number = 1

    session = InchwormSession(
        target_reps=target_reps,
        target_sets=target_sets,
        set_number=set_number,
    )

    try:
        while True:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                break

            frame = _decode_frame(message)
            if frame is None:
                continue

            timestamp_ms = int(time.time() * 1000)
            analysis = session.detect(frame, timestamp_ms)

            # Send telemetry payload back to client
            await websocket.send_json(analysis)

            # Check if total assigned set is complete
            if analysis.get("exercise_complete"):
                await websocket.send_json(
                    {
                        "type": "SESSION_COMPLETE",
                        "message": "Inchworm set completed successfully!",
                    }
                )
                break

    except WebSocketDisconnect:
        print("[Inchworm Router] Client disconnected cleanly.")
    except Exception as e:
        print(f"[Inchworm Router] Streaming error: {e}")
    finally:
        session.close()
