from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import asyncio
import base64
import time

import cv2
import numpy as np

from src.detectors.upper_body.standing_trunk_rotation import (
    StandingTrunkRotationSession,
)

router = APIRouter()


def decode_frame(raw: str):
    if "," in raw:
        raw = raw.split(",", 1)[1]
    image_bytes = base64.b64decode(raw)
    np_array = np.frombuffer(image_bytes, dtype=np.uint8)
    return cv2.imdecode(np_array, cv2.IMREAD_COLOR)


def _query_int(
    websocket: WebSocket,
    name: str,
    default: int,
    lo: int,
    hi: int,
) -> int:
    raw = websocket.query_params.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


def _log_rep_progress(result: dict, exercise_already_logged: bool) -> bool:
    if result.get("rep_completed"):
        print(
            f"[StandingTrunkRotation] {result.get('rep_side', 'n/a').capitalize()} "
            f"rep {result.get('rep_count')}/{result.get('target_reps')} "
            f"(set {result.get('set_number')}/{result.get('target_sets')}) — "
            f"quality={result.get('rep_form_quality') or 'n/a'} "
            f"tempo={result.get('rep_classification') or 'n/a'}"
        )

    if result.get("exercise_complete") and not exercise_already_logged:
        print(
            "[StandingTrunkRotation] EXERCISE COMPLETE — "
            f"{result.get('target_sets')} sets x {result.get('target_reps')} reps done."
        )
        return True

    return exercise_already_logged


@router.websocket("/standing_trunk_rotation")
async def standing_trunk_rotation(websocket: WebSocket):
    """Analyze base64 frames for standing trunk rotation."""
    await websocket.accept()
    print("Client connected: StandingTrunkRotation")

    target_reps = _query_int(websocket, "target_reps", default=10, lo=1, hi=100)
    target_sets = _query_int(websocket, "target_sets", default=1, lo=1, hi=20)
    set_number = _query_int(
        websocket,
        "set_number",
        default=1,
        lo=1,
        hi=target_sets,
    )

    counter = StandingTrunkRotationSession(
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
            exercise_logged = _log_rep_progress(result, exercise_logged)
            await websocket.send_json(result)
            await asyncio.sleep(0.001)
    except WebSocketDisconnect:
        print("Disconnected: StandingTrunkRotation")
    finally:
        counter.close()
