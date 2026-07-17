from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import base64
import time
import cv2
import numpy as np

from src.detectors.side_plank import SidePlankHoldSession

router = APIRouter()
start_time = time.time()


def decode_frame(raw: str):
    if "," in raw:
        raw = raw.split(",")[1]
    image_bytes = base64.b64decode(raw)
    np_array = np.frombuffer(image_bytes, dtype=np.uint8)
    return cv2.imdecode(np_array, cv2.IMREAD_COLOR)


@router.websocket("/side_plank")
async def side_plank_route(websocket: WebSocket):
    await websocket.accept()

    # Optional: parse query params for target_seconds, target_sets, set_number
    session = SidePlankHoldSession(
        target_seconds=None,  # or parse from query params
        target_sets=1,
        set_number=1,
    )

    try:
        print("Client connected: /side_plank")
        while True:
            image = await websocket.receive_text()
            frame = decode_frame(image)
            timestamp = int((time.time() - start_time) * 1000)

            result = session.detect(frame, timestamp)
            await websocket.send_json(result)

            await asyncio.sleep(0.001)

    except WebSocketDisconnect:
        print("Disconnected: /side_plank")
    finally:
        session.close()
