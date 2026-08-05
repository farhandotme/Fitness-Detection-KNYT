from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import asyncio
import base64
import time

import cv2
import numpy as np

from src.detectors.skandha_chakra import SkandhaChakraSession, VALID_DIRECTIONS

router = APIRouter()


def decode_frame(raw: str):
    if "," in raw:
        raw = raw.split(",")[1]

    image_bytes = base64.b64decode(raw)
    np_array = np.frombuffer(image_bytes, dtype=np.uint8)

    return cv2.imdecode(np_array, cv2.IMREAD_COLOR)


def _query_int(websocket: WebSocket, name: str, default: int, lo: int, hi: int) -> int:
    """Same convention as the other routes — the coach-assigned plan
    reaches the backend via query params, and only
    `SkandhaChakraSession` decides whether it's been met."""
    raw = websocket.query_params.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


def _query_choice(websocket: WebSocket, name: str, default: str, choices) -> str:
    raw = (websocket.query_params.get(name) or "").strip().lower()
    return raw if raw in choices else default


def _log_rep_progress(label: str, result: dict, exercise_already_logged: bool) -> bool:
    """Print exactly one line per completed rep, and one line when the
    exercise finishes — never per-frame. Same convention as the other
    routes."""
    if result.get("rep_completed"):
        rep_count = result.get("rep_count")
        target_reps = result.get("target_reps")
        set_number = result.get("set_number")
        target_sets = result.get("target_sets")
        direction = result.get("rotation_direction") or "n/a"
        quality = result.get("rep_form_quality") or "n/a"
        print(
            f"[{label}] Rep {rep_count}/{target_reps} "
            f"(set {set_number}/{target_sets}) — direction={direction} quality={quality}"
        )

    if result.get("exercise_complete") and not exercise_already_logged:
        print(
            f"[{label}] EXERCISE COMPLETE — "
            f"{result.get('target_sets')} sets x {result.get('target_reps')} reps done."
        )
        return True

    return exercise_already_logged


@router.websocket("/skandha_chakra")
async def skandha_chakra(websocket: WebSocket):
    await websocket.accept()

    print("Client connected: Skandha Chakra")

    target_reps = _query_int(websocket, "target_reps", default=10, lo=1, hi=100)
    target_sets = _query_int(websocket, "target_sets", default=1, lo=1, hi=20)
    set_number = _query_int(websocket, "set_number", default=1, lo=1, hi=target_sets)
    direction = _query_choice(
        websocket, "direction", default="either", choices=VALID_DIRECTIONS
    )

    counter = SkandhaChakraSession(
        target_reps=target_reps,
        target_sets=target_sets,
        set_number=set_number,
        direction=direction,
    )

    try:
        exercise_logged = False
        while True:
            image = await websocket.receive_text()

            frame = decode_frame(image)

            timestamp = int(time.time() * 1000)

            result = counter.detect(frame, timestamp)

            exercise_logged = _log_rep_progress(
                "SkandhaChakra", result, exercise_logged
            )

            await websocket.send_json(result)

            await asyncio.sleep(0.001)

    except WebSocketDisconnect:
        print("Disconnected: Skandha Chakra")

    finally:
        counter.close()
