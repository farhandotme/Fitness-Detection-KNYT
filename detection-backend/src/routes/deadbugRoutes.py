from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import asyncio
import base64
import time

import cv2
import numpy as np

from src.detectors.dead_bug import DeadBugSession

router = APIRouter()


def decode_frame(raw: str):
    if "," in raw:
        raw = raw.split(",")[1]

    image_bytes = base64.b64decode(raw)
    np_array = np.frombuffer(image_bytes, dtype=np.uint8)

    return cv2.imdecode(np_array, cv2.IMREAD_COLOR)


def _query_int(websocket: WebSocket, name: str, default: int, lo: int, hi: int) -> int:
    """Read an integer query param off the websocket URL, clamped to [lo, hi].

    Same convention as the other routes — the frontend sends the
    coach-assigned plan (reps per set / sets / which set) as query
    params when it opens the socket; the backend `DeadBugSession` is the
    only thing that decides whether that plan has been met.
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
    """Print one line per completed rep, one line per rejected attempt
    (so cheat detection is visible in the server log too), and one line
    when the exercise finishes — never per-frame."""
    if result.get("rep_completed"):
        diagonal = result.get("rep_diagonal")
        rep_count = result.get("rep_count")
        target_reps = result.get("target_reps")
        set_number = result.get("set_number")
        target_sets = result.get("target_sets")
        print(
            f"[{label}] {diagonal} rep {rep_count}/{target_reps} "
            f"(set {set_number}/{target_sets})"
        )
    elif result.get("invalid_attempt"):
        print(f"[{label}] attempt rejected — reason={result.get('invalid_reason')}")

    if result.get("exercise_complete") and not exercise_already_logged:
        print(
            f"[{label}] EXERCISE COMPLETE — "
            f"{result.get('target_sets')} sets x {result.get('target_reps')} reps done."
        )
        return True

    return exercise_already_logged


@router.websocket("/dead_bug")
async def dead_bug(websocket: WebSocket):
    await websocket.accept()

    print("Client connected: Dead Bug")

    target_reps = _query_int(websocket, "target_reps", default=10, lo=1, hi=200)
    target_sets = _query_int(websocket, "target_sets", default=1, lo=1, hi=20)
    set_number = _query_int(websocket, "set_number", default=1, lo=1, hi=target_sets)

    counter = DeadBugSession(
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

            exercise_logged = _log_rep_progress("Dead Bug", result, exercise_logged)

            await websocket.send_json(result)

            await asyncio.sleep(0.001)

    except WebSocketDisconnect:
        print("Disconnected: Dead Bug")

    finally:
        counter.close()
