from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import asyncio
import base64
import time

import cv2
import numpy as np

from src.detectors.upper_body.overhead_triceps_extensions import (
    OverheadTricepsExtensionSession,
)

router = APIRouter()


def decode_frame(raw: str):
    if "," in raw:
        raw = raw.split(",")[1]

    image_bytes = base64.b64decode(raw)
    np_array = np.frombuffer(image_bytes, dtype=np.uint8)

    return cv2.imdecode(np_array, cv2.IMREAD_COLOR)


def _query_int(websocket: WebSocket, name: str, default: int, lo: int, hi: int) -> int:
    raw = websocket.query_params.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


def _log_rep_progress(label: str, result: dict, exercise_already_logged: bool) -> bool:
    if result.get("rep_completed"):
        quality = result.get("rep_form_quality") or "n/a"
        print(
            f"[{label}] Rep {result.get('rep_count')}/{result.get('target_reps')} "
            f"(set {result.get('set_number')}/{result.get('target_sets')}) — "
            f"quality={quality}"
        )

    if result.get("exercise_complete") and not exercise_already_logged:
        print(
            f"[{label}] EXERCISE COMPLETE — "
            f"{result.get('target_sets')} sets x {result.get('target_reps')} reps done."
        )
        return True

    return exercise_already_logged


async def _run_triceps_session(websocket: WebSocket, arm_mode: str, label: str):
    await websocket.accept()
    print(f"Client connected: {label}")

    target_reps = _query_int(websocket, "target_reps", default=10, lo=1, hi=200)
    target_sets = _query_int(websocket, "target_sets", default=1, lo=1, hi=20)
    set_number = _query_int(websocket, "set_number", default=1, lo=1, hi=target_sets)

    counter = OverheadTricepsExtensionSession(
        arm_mode=arm_mode,
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
            exercise_logged = _log_rep_progress(label, result, exercise_logged)

            await websocket.send_json(result)
            await asyncio.sleep(0.001)

    except WebSocketDisconnect:
        print(f"Disconnected: {label}")

    finally:
        counter.close()


@router.websocket("/overhead_triceps_extension/left")
async def overhead_triceps_extension_left(websocket: WebSocket):
    await _run_triceps_session(
        websocket, arm_mode="left", label="Triceps Extension (Left Arm)"
    )


@router.websocket("/overhead_triceps_extension/right")
async def overhead_triceps_extension_right(websocket: WebSocket):
    await _run_triceps_session(
        websocket, arm_mode="right", label="Triceps Extension (Right Arm)"
    )


@router.websocket("/overhead_triceps_extension/both")
async def overhead_triceps_extension_both(websocket: WebSocket):
    await _run_triceps_session(
        websocket, arm_mode="both", label="Triceps Extension (Both Arms)"
    )
