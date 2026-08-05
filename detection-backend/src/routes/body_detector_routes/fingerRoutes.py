from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from src.detectors.body_detector.finger_detector import HandDetector
import asyncio
import base64
import time

import cv2
import numpy as np

router = APIRouter()


start_time = time.time()


def decode_frame(raw: str):

    if "," in raw:
        raw = raw.split(",")[1]

    image_bytes = base64.b64decode(raw)

    np_array = np.frombuffer(image_bytes, dtype=np.uint8)

    return cv2.imdecode(np_array, cv2.IMREAD_COLOR)


@router.websocket("/finger")
async def finger_endpoint(websocket: WebSocket):

    await websocket.accept()
    print("Client connected: /ws/finger")

    detector = HandDetector()
    try:

        while True:

            image = await websocket.receive_text()
            frame = decode_frame(image)

            timestamp = int((time.time() - start_time) * 1000)

            result = detector.detect(frame, timestamp)

            await websocket.send_json(result)

            await asyncio.sleep(0.001)

    except WebSocketDisconnect:
        print("Disconnected: /ws/finger")

    finally:
        detector.close()
