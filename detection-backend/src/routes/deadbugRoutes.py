from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import base64
import time
import cv2
import numpy as np

from src.detectors.dead_bug import DeadBugSession

router = APIRouter()
start_time = time.time()


def decode_frame(raw: str):
    if "," in raw:
        raw = raw.split(",")[1]
    image_bytes = base64.b64decode(raw)
    np_array = np.frombuffer(image_bytes, dtype=np.uint8)
    return cv2.imdecode(np_array, cv2.IMREAD_COLOR)


@router.websocket("/deadbug")
async def deadbug_route(websocket: WebSocket):
    await websocket.accept()

    # Optional: parse query params for target_reps, target_sets, set_number
    session = DeadBugSession(
        target_reps=None,  # or parse from query params
        target_sets=1,
        set_number=1,
    )

    try:
        print("Client connected: /deadbug")
        while True:
            image = await websocket.receive_text()
            frame = decode_frame(image)
            timestamp = int((time.time() - start_time) * 1000)

            result = session.detect(frame, timestamp)
            await websocket.send_json(result)

            await asyncio.sleep(0.001)

    except WebSocketDisconnect:
        print("Disconnected: /deadbug")
    finally:
        session.close()
