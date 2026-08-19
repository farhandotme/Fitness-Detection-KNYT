from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import asyncio
import base64
import time

import cv2
import numpy as np

from src.detectors.lower_body.lunge_to_knee_drive import LungeToKneeDriveSession

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
    own whether that plan has been completed — `LungeToKneeDriveSession`
    is the only thing that sets `session_complete` / `exercise_complete`
    in the response.
    """
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
    exercise finishes — never per-frame. `rep_completed` is already an
    edge-triggered flag from `LungeToKneeDriveAnalyzer`.
    """
    if result.get("rep_completed"):
        print(
            f"[{label}] Rep {result.get('rep_count')}/{result.get('target_reps')} "
            f"(set {result.get('set_number')}/{result.get('target_sets')}) — "
            f"L={result.get('left_leg_reps')} R={result.get('right_leg_reps')} "
            f"quality={result.get('rep_form_quality') or 'n/a'}"
        )

    if result.get("exercise_complete") and not exercise_already_logged:
        print(
            f"[{label}] EXERCISE COMPLETE — "
            f"{result.get('target_sets')} sets x {result.get('target_reps')} reps done."
        )
        return True

    return exercise_already_logged


@router.websocket("/lunge_to_knee_drive")
async def lunge_to_knee_drive(websocket: WebSocket):
    await websocket.accept()

    print("Client connected: Lunge to Knee Drive")

    target_reps = _query_int(websocket, "target_reps", default=16, lo=1, hi=200)
    target_sets = _query_int(websocket, "target_sets", default=1, lo=1, hi=20)
    set_number = _query_int(websocket, "set_number", default=1, lo=1, hi=target_sets)

    counter = LungeToKneeDriveSession(
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

            exercise_logged = _log_rep_progress(
                "Lunge to Knee Drive", result, exercise_logged
            )

            await websocket.send_json(result)

            await asyncio.sleep(0.001)

    except WebSocketDisconnect:
        print("Disconnected: Lunge to Knee Drive")

    finally:
        counter.close()
