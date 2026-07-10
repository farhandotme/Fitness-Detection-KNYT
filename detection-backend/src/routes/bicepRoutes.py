from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import asyncio
import base64
import time

import cv2
import numpy as np

from src.detectors.bicep_curl import (
    SingleArmCurlSession,
    BothArmCurlSession,
)

router = APIRouter()


def decode_frame(raw: str):
    if "," in raw:
        raw = raw.split(",")[1]

    image_bytes = base64.b64decode(raw)
    np_array = np.frombuffer(image_bytes, dtype=np.uint8)

    return cv2.imdecode(np_array, cv2.IMREAD_COLOR)


@router.websocket("/bicep_curl_left_arm")
async def left_arm(websocket: WebSocket):
    await websocket.accept()

    print("Client connected: Left Arm")

    counter = SingleArmCurlSession(
        side="left",
        target_reps=10,  # Optional
    )

    try:
        while True:
            image = await websocket.receive_text()

            frame = decode_frame(image)

            timestamp = int(time.time() * 1000)

            result = counter.detect(frame, timestamp)

            await websocket.send_json(result)

            await asyncio.sleep(0.001)

    except WebSocketDisconnect:
        print("Disconnected: Left Arm")

    finally:
        counter.close()


@router.websocket("/bicep_curl_right_arm")
async def right_arm(websocket: WebSocket):
    await websocket.accept()

    print("Client connected: Right Arm")

    counter = SingleArmCurlSession(
        side="right",
        target_reps=10,
    )

    try:
        while True:
            image = await websocket.receive_text()

            frame = decode_frame(image)

            timestamp = int(time.time() * 1000)

            result = counter.detect(frame, timestamp)

            await websocket.send_json(result)

            await asyncio.sleep(0.001)

    except WebSocketDisconnect:
        print("Disconnected: Right Arm")

    finally:
        counter.close()


@router.websocket("/bicep_curl_both_arm")
async def both_arm(websocket: WebSocket):
    await websocket.accept()

    print("Client connected: Both Arms")

    counter = BothArmCurlSession(
        target_reps=10,
    )

    try:
        while True:
            image = await websocket.receive_text()

            frame = decode_frame(image)

            timestamp = int(time.time() * 1000)

            result = counter.detect(frame, timestamp)

            await websocket.send_json(result)

            await asyncio.sleep(0.001)

    except WebSocketDisconnect:
        print("Disconnected: Both Arms")

    finally:
        counter.close()
