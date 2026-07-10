from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

import asyncio
import base64
import time

import cv2
import numpy as np

from src.detectors.bicep_curl import bicep_curl_both, bicep_curl_left, bicep_curl_right

start_time = time.time()


def decode_frame(raw: str):

    if "," in raw:
        raw = raw.split(",")[1]

    image_bytes = base64.b64decode(raw)

    np_array = np.frombuffer(image_bytes, dtype=np.uint8)

    return cv2.imdecode(np_array, cv2.IMREAD_COLOR)


@router.websocket("/bicep_curl_left_arm")
async def left_arm(websocket: WebSocket):
    print(websocket.headers)
    await websocket.accept()

    try:
        counter = bicep_curl_left()
    except ValueError as e:
        await websocket.send_json({"error": str(e)})
        await websocket.close()
        return

    print(f"Client connected: /bicep_curl_left_arm")

    try:

        while True:

            image = await websocket.receive_text()
            frame = decode_frame(image)

            timestamp = int((time.time() - start_time) * 1000)

            result = counter.detect(frame, timestamp)

            await websocket.send_json(result)

            await asyncio.sleep(0.001)

    except WebSocketDisconnect:
        print(f"Disconnected: /bicep_curl_left_arm")

    finally:
        counter.close()


@router.websocket("/bicep_curl_right_arm")
async def right_arm(websocket: WebSocket):
    print(websocket.headers)
    await websocket.accept()

    try:
        counter = bicep_curl_right()
    except ValueError as e:
        await websocket.send_json({"error": str(e)})
        await websocket.close()
        return

    print(f"Client connected: /bicep_curl_right_arm")

    try:

        while True:

            image = await websocket.receive_text()
            frame = decode_frame(image)

            timestamp = int((time.time() - start_time) * 1000)

            result = counter.detect(frame, timestamp)

            await websocket.send_json(result)

            await asyncio.sleep(0.001)

    except WebSocketDisconnect:
        print(f"Disconnected: /bicep_curl_right_arm")

    finally:
        counter.close()


@router.websocket("/bicep_curl_both_arm")
async def both_arm(websocket: WebSocket):
    await websocket.accept()
    counter = bicep_curl_both()
    try:
        while True:
            image = await websocket.receive_text()
            frame = decode_frame(image)
            timestamp = int((time.time() - start_time) * 1000)
            result = counter.detect(frame, timestamp)
            await websocket.send_json(result)
    except WebSocketDisconnect:
        print("Disconnected: /bicep_curl_both_arm")
    finally:
        counter.close()
