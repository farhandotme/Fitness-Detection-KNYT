from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import base64
import time

import cv2
import numpy as np

from src.detectors.lower_body.culf_raise import CalfRaiseSession

router = APIRouter()


def decode_frame(raw: str):
    if "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        image_bytes = base64.b64decode(raw)
    except Exception:
        return None
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


@router.websocket("/calf_raise")
async def calf_raise(websocket: WebSocket):
    await websocket.accept()
    print("Client connected: Calf Raise")

    target_reps = _query_int(websocket, "target_reps", default=15, lo=1, hi=200)
    target_sets = _query_int(websocket, "target_sets", default=1, lo=1, hi=20)
    set_number = _query_int(websocket, "set_number", default=1, lo=1, hi=target_sets)

    counter = CalfRaiseSession(
        target_reps=target_reps,
        target_sets=target_sets,
        set_number=set_number,
    )

    exercise_logged = False

    try:
        while True:
            image = await websocket.receive_text()
            frame = decode_frame(image)

            if frame is None:
                await websocket.send_json(
                    {
                        "pose_detected": False,
                        "feedback": "Invalid image frame received.",
                        "rep_completed": False,
                    }
                )
                continue

            timestamp = int(time.time() * 1000)
            result = counter.detect(frame, timestamp)
            exercise_logged = _log_rep_progress("Calf Raise", result, exercise_logged)
            await websocket.send_json(result)

    except WebSocketDisconnect:
        print("Disconnected: Calf Raise")
    finally:
        counter.close()
