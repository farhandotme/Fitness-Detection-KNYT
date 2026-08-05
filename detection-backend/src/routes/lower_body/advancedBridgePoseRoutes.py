from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import asyncio
import base64
import time

import cv2
import numpy as np

from src.detectors.lower_body.advanced_bridge_pose import AdvancedBridgePoseSession

router = APIRouter()


def decode_frame(raw: str):
    if "," in raw:
        raw = raw.split(",")[1]

    image_bytes = base64.b64decode(raw)
    np_array = np.frombuffer(image_bytes, dtype=np.uint8)

    return cv2.imdecode(np_array, cv2.IMREAD_COLOR)


def _query_int(websocket: WebSocket, name: str, default: int, lo: int, hi: int) -> int:
    """Read an integer query param off the websocket URL, clamped to [lo, hi].

    Same convention as `hollowHoldRoutes.py` — the coach-assigned plan
    (hold seconds per set / number of sets / which set this connection is
    for) reaches the backend this way. The frontend does NOT get to
    decide on its own whether that plan has been completed —
    `AdvancedBridgePoseSession` is the only thing that sets
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


def _log_hold_progress(label: str, result: dict, exercise_already_logged: bool) -> bool:
    """Print one line when the target is reached, and one line when the
    exercise finishes — never per-frame."""
    if result.get("target_reached"):
        print(
            f"[{label}] Target reached — "
            f"{result.get('hold_seconds')}s / {result.get('target_seconds')}s "
            f"(set {result.get('set_number')}/{result.get('target_sets')})"
        )

    if result.get("exercise_complete") and not exercise_already_logged:
        print(
            f"[{label}] EXERCISE COMPLETE — "
            f"{result.get('target_sets')} sets x {result.get('target_seconds')}s done."
        )
        return True

    return exercise_already_logged


@router.websocket("/advanced_bridge_pose")
async def advanced_bridge_pose(websocket: WebSocket):
    await websocket.accept()

    print("Client connected: AdvancedBridgePose")

    target_seconds = _query_int(websocket, "target_seconds", default=20, lo=5, hi=600)
    target_sets = _query_int(websocket, "target_sets", default=1, lo=1, hi=20)
    set_number = _query_int(websocket, "set_number", default=1, lo=1, hi=target_sets)

    session = AdvancedBridgePoseSession(
        target_seconds=target_seconds,
        target_sets=target_sets,
        set_number=set_number,
    )

    try:
        exercise_logged = False
        while True:
            image = await websocket.receive_text()

            frame = decode_frame(image)

            timestamp = int(time.time() * 1000)

            result = session.detect(frame, timestamp)

            exercise_logged = _log_hold_progress(
                "AdvancedBridgePose", result, exercise_logged
            )

            await websocket.send_json(result)

            await asyncio.sleep(0.001)

    except WebSocketDisconnect:
        print("Disconnected: AdvancedBridgePose")

    finally:
        session.close()
