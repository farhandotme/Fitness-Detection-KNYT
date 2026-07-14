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


def _query_int(websocket: WebSocket, name: str, default: int, lo: int, hi: int) -> int:
    """Read an integer query param off the websocket URL, clamped to [lo, hi].

    This is how the coach-assigned plan (reps per set / number of sets /
    which set this connection is for) reaches the backend. The frontend
    sends these when it opens the socket; it does NOT get to decide on its
    own whether that plan has been completed — this module (via
    SingleArmCurlSession / BothArmCurlSession) is the only thing that sets
    `session_complete` / `exercise_complete` in the response.
    """
    raw = websocket.query_params.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


@router.websocket("/bicep_curl_left_arm")
async def left_arm(websocket: WebSocket):
    await websocket.accept()

    print("Client connected: Left Arm")

    target_reps = _query_int(websocket, "target_reps", default=10, lo=1, hi=100)
    target_sets = _query_int(websocket, "target_sets", default=1, lo=1, hi=20)
    set_number = _query_int(websocket, "set_number", default=1, lo=1, hi=target_sets)

    counter = SingleArmCurlSession(
        side="left",
        target_reps=target_reps,
        target_sets=target_sets,
        set_number=set_number,
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

    target_reps = _query_int(websocket, "target_reps", default=10, lo=1, hi=100)
    target_sets = _query_int(websocket, "target_sets", default=1, lo=1, hi=20)
    set_number = _query_int(websocket, "set_number", default=1, lo=1, hi=target_sets)

    counter = SingleArmCurlSession(
        side="right",
        target_reps=target_reps,
        target_sets=target_sets,
        set_number=set_number,
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

    target_reps = _query_int(websocket, "target_reps", default=10, lo=1, hi=100)
    target_sets = _query_int(websocket, "target_sets", default=1, lo=1, hi=20)
    set_number = _query_int(websocket, "set_number", default=1, lo=1, hi=target_sets)

    counter = BothArmCurlSession(
        target_reps=target_reps,
        target_sets=target_sets,
        set_number=set_number,
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
