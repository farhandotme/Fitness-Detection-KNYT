from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import asyncio
import base64
import time

import cv2
import numpy as np

from src.detectors.full_body.shoulder_stand_pose import ShoulderStandSession

router = APIRouter()


def decode_frame(raw: str):
    if "," in raw:
        raw = raw.split(",")[1]

    image_bytes = base64.b64decode(raw)
    np_array = np.frombuffer(image_bytes, dtype=np.uint8)

    return cv2.imdecode(np_array, cv2.IMREAD_COLOR)


def _query_float(
    websocket: WebSocket, name: str, default: float, lo: float, hi: float
) -> float:
    """Same convention as the other routes' `_query_int` — the
    coach-assigned plan reaches the backend via query params, and only
    `ShoulderStandSession` decides whether it's been met."""
    raw = websocket.query_params.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


def _query_int(websocket: WebSocket, name: str, default: int, lo: int, hi: int) -> int:
    raw = websocket.query_params.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


def _log_hold_progress(label: str, result: dict, exercise_already_logged: bool) -> bool:
    """Print once when the target hold time is reached, and once when
    the exercise finishes — never per-frame. Same one-line-per-event
    convention as the other routes, adapted for a timer instead of
    discrete reps."""
    is_holding = result.get("stage") == "holding"

    if result.get("session_complete") and is_holding:
        set_number = result.get("set_number")
        target_sets = result.get("target_sets")
        hold_time = result.get("hold_time")
        target = result.get("target_hold_seconds")
        print(
            f"[{label}] Hold target reached — {hold_time}/{target}s "
            f"(set {set_number}/{target_sets})"
        )

    if result.get("exercise_complete") and not exercise_already_logged:
        print(
            f"[{label}] EXERCISE COMPLETE — "
            f"{result.get('target_sets')} sets x {result.get('target_hold_seconds')}s done."
        )
        return True

    return exercise_already_logged


@router.websocket("/shoulder_stand")
async def shoulder_stand(websocket: WebSocket):
    await websocket.accept()

    print("Client connected: Shoulder Stand")

    target_hold_seconds = _query_float(
        websocket, "target_hold_seconds", default=30.0, lo=5.0, hi=600.0
    )
    target_sets = _query_int(websocket, "target_sets", default=1, lo=1, hi=20)
    set_number = _query_int(websocket, "set_number", default=1, lo=1, hi=target_sets)

    counter = ShoulderStandSession(
        target_hold_seconds=target_hold_seconds,
        target_sets=target_sets,
        set_number=set_number,
    )

    try:
        exercise_logged = False
        while True:
            image = await websocket.receive_text()

            frame = decode_frame(image)

            timestamp = int(time.time() * 1000)

            result = counter.detect(frame, timestamp)

            exercise_logged = _log_hold_progress(
                "ShoulderStand", result, exercise_logged
            )

            await websocket.send_json(result)

            await asyncio.sleep(0.001)

    except WebSocketDisconnect:
        print("Disconnected: Shoulder Stand")

    finally:
        counter.close()
