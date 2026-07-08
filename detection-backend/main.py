import asyncio
import base64
import time

import cv2
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from src.detector import HandDetector
from src.pose_detector import RepCounter

app = FastAPI()

start_time = time.time()


@app.get("/")
async def home():
    return {"status": "running"}


def decode_frame(raw: str):

    if "," in raw:
        raw = raw.split(",")[1]

    image_bytes = base64.b64decode(raw)

    np_array = np.frombuffer(image_bytes, dtype=np.uint8)

    return cv2.imdecode(np_array, cv2.IMREAD_COLOR)


@app.websocket("/ws/finger")
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


@app.websocket("/ws/rep")
async def rep_endpoint(websocket: WebSocket, exercise: str = "bicep_curl"):

    await websocket.accept()

    try:
        counter = RepCounter(exercise=exercise)
    except ValueError as e:
        await websocket.send_json({"error": str(e)})
        await websocket.close()
        return

    print(f"Client connected: /ws/rep ({exercise})")

    try:

        while True:

            image = await websocket.receive_text()
            frame = decode_frame(image)

            timestamp = int((time.time() - start_time) * 1000)

            result = counter.detect(frame, timestamp)

            await websocket.send_json(result)

            await asyncio.sleep(0.001)

    except WebSocketDisconnect:
        print(f"Disconnected: /ws/rep ({exercise})")

    finally:
        counter.close()
