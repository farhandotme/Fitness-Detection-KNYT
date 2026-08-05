from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import asyncio
import base64
import time

import cv2
import numpy as np

from src.detectors.upper_body.arnold_press import ArnoldPressSession

router = APIRouter()


def decode_frame(raw: str):
    if "," in raw:
        raw = raw.split(",")[1]

    image_bytes = base64.b64decode(raw)
    np_array = np.frombuffer(image_bytes, dtype=np.uint8)

    return cv2.imdecode(np_array, cv2.IMREAD_COLOR)


def _query_int(websocket: WebSocket, name: str, default: int, lo: int, hi: int) -> int:
    """Same convention as the other routes — the coach-assigned plan
    reaches the backend via query params, and only `ArnoldPressSession`
    decides whether it's been met."""
    raw = websocket.query_params.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


def _log_rep_progress(label: str, result: dict, exercise_already_logged: bool) -> bool:
    """Print exactly one line per completed rep, and one line when the
    exercise finishes — never per-frame. Same convention as the other
    routes."""
    if result.get("rep_completed"):
        rep_count = result.get("rep_count")
        target_reps = result.get("target_reps")
        set_number = result.get("set_number")
        target_sets = result.get("target_sets")
        quality = result.get("rep_form_quality") or "n/a"
        tempo = result.get("rep_classification") or "n/a"
        print(
            f"[{label}] Rep {rep_count}/{target_reps} "
            f"(set {set_number}/{target_sets}) — quality={quality} tempo={tempo}"
        )

    if result.get("exercise_complete") and not exercise_already_logged:
        print(
            f"[{label}] EXERCISE COMPLETE — "
            f"{result.get('target_sets')} sets x {result.get('target_reps')} reps done."
        )
        return True

    return exercise_already_logged


@router.websocket("/arnold_press")
async def arnold_press(websocket: WebSocket):
    await websocket.accept()

    print("Client connected: Arnold Press")

    target_reps = _query_int(websocket, "target_reps", default=10, lo=1, hi=100)
    target_sets = _query_int(websocket, "target_sets", default=1, lo=1, hi=20)
    set_number = _query_int(websocket, "set_number", default=1, lo=1, hi=target_sets)

    counter = ArnoldPressSession(
        target_reps=target_reps,
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

            exercise_logged = _log_rep_progress("ArnoldPress", result, exercise_logged)

            await websocket.send_json(result)

            await asyncio.sleep(0.001)

    except WebSocketDisconnect:
        print("Disconnected: Arnold Press")

    finally:
        counter.close()
