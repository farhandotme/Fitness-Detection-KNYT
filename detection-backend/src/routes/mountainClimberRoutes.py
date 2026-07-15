from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import base64
import time

import cv2
import numpy as np

from src.detectors.mountain_climber import MountainClimberSession

router = APIRouter()


def decode_frame(raw: str):
    if "," in raw:
        raw = raw.split(",", 1)[1]
    image_bytes = base64.b64decode(raw)
    np_array = np.frombuffer(image_bytes, dtype=np.uint8)
    frame = cv2.imdecode(np_array, cv2.IMREAD_COLOR)
    return frame


def _query_int(websocket: WebSocket, name: str, default: int, lo: int, hi: int) -> int:
    raw = websocket.query_params.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


@router.websocket("/mountain_climber")
async def mountain_climber(websocket: WebSocket):
    await websocket.accept()
    print("Client connected: Mountain Climber")

    target_reps = _query_int(websocket, "target_reps", default=10, lo=1, hi=200)
    target_sets = _query_int(websocket, "target_sets", default=1, lo=1, hi=20)
    set_number = _query_int(websocket, "set_number", default=1, lo=1, hi=target_sets)

    counter = MountainClimberSession(
        target_reps=target_reps,
        target_sets=target_sets,
        set_number=set_number,
    )

    try:
        while True:
            image = await websocket.receive_text()
            frame = decode_frame(image)
            if frame is None:
                await websocket.send_json(
                    {"error": "Invalid frame", "pose_detected": False}
                )
                continue
            timestamp = int(time.time() * 1000)
            result = counter.detect(frame, timestamp)
            await websocket.send_json(result)
            await asyncio.sleep(0.001)
    except WebSocketDisconnect:
        print("Disconnected: Mountain Climber")
    finally:
        counter.close()
