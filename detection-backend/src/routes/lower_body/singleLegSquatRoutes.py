from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import base64

import cv2
import numpy as np

from src.detectors.single_leg_squat import (
    SingleLegSquatSession,
    VALID_MODES,
    VALID_SIDES,
)

router = APIRouter()


def decode_frame(raw: str):
    if "," in raw:
        raw = raw.split(",", 1)[1]

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


def _query_choice(websocket: WebSocket, name: str, default: str, choices) -> str:
    raw = (websocket.query_params.get(name) or "").strip().lower()
    return raw if raw in choices else default


def _log_rep_progress(label: str, result: dict, exercise_already_logged: bool) -> bool:
    if result.get("rep_completed"):
        rep_count = result.get("rep_count")
        target_reps = result.get("target_reps")
        set_number = result.get("set_number")
        target_sets = result.get("target_sets")
        side = result.get("current_side")
        quality = result.get("rep_form_quality") or "n/a"
        tempo = result.get("rep_classification") or "n/a"
        print(
            f"[{label}] {side} rep {rep_count}/{target_reps} "
            f"(set {set_number}/{target_sets}) — quality={quality} tempo={tempo}"
        )

    if result.get("exercise_complete") and not exercise_already_logged:
        print(
            f"[{label}] EXERCISE COMPLETE — "
            f"{result.get('target_sets')} sets x {result.get('target_reps')} reps done."
        )
        return True

    return exercise_already_logged


@router.websocket("/single_leg_squat")
async def single_leg_squat(websocket: WebSocket):
    await websocket.accept()

    print("Client connected: Single Leg Squat")

    target_reps = _query_int(websocket, "target_reps", default=8, lo=1, hi=100)
    target_sets = _query_int(websocket, "target_sets", default=1, lo=1, hi=20)
    set_number = _query_int(websocket, "set_number", default=1, lo=1, hi=target_sets)
    side = _query_choice(websocket, "side", default="left", choices=VALID_SIDES)
    mode = _query_choice(websocket, "mode", default="standard", choices=VALID_MODES)

    counter = SingleLegSquatSession(
        target_reps=target_reps,
        target_sets=target_sets,
        set_number=set_number,
        side=side,
        mode=mode,
    )

    frame_ts_ms = 0

    try:
        exercise_logged = False

        while True:
            raw = await websocket.receive_text()
            frame = decode_frame(raw)

            if frame is None:
                await websocket.send_json(
                    {
                        "pose_detected": False,
                        "feedback": "Invalid frame received.",
                    }
                )
                continue

            frame_ts_ms += 33

            result = counter.detect(frame, frame_ts_ms)
            exercise_logged = _log_rep_progress(
                "SingleLegSquat", result, exercise_logged
            )

            await websocket.send_json(result)

    except WebSocketDisconnect:
        print("Disconnected: Single Leg Squat")
    finally:
        counter.close()
