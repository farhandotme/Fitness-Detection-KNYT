from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import asyncio
import base64
import time

import cv2
import numpy as np

from src.detectors.plank_hold import PlankHoldSession

router = APIRouter()


def decode_frame(raw: str):
    if "," in raw:
        raw = raw.split(",")[1]

    image_bytes = base64.b64decode(raw)
    np_array = np.frombuffer(image_bytes, dtype=np.uint8)

    return cv2.imdecode(np_array, cv2.IMREAD_COLOR)


def _query_int(websocket: WebSocket, name: str, default: int, lo: int, hi: int) -> int:
    """Read an integer query param off the websocket URL, clamped to [lo, hi].

    This is how the coach-assigned plan (hold seconds per set / number of
    sets / which set this connection is for) reaches the backend. The
    frontend sends these when it opens the socket; it does NOT get to
    decide on its own whether that plan has been completed —
    PlankHoldSession is the only thing that sets `session_complete` /
    `exercise_complete` in the response.
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
    """Print exactly one line whenever the hold state flips (started
    holding / broke form / resumed / target reached), and one line when
    the exercise finishes — never per-frame, which would be dozens of
    lines a second at 30fps.

    Returns the (possibly updated) `exercise_already_logged` flag — pass
    it back in on the next call so the "exercise complete" line only
    prints once even though `exercise_complete` stays True on subsequent
    frames until the socket closes.
    """
    if result.get("target_reached"):
        print(
            f"[{label}] Target reached — set {result.get('set_number')}/"
            f"{result.get('target_sets')}: "
            f"{result.get('hold_seconds')}s / {result.get('target_seconds')}s "
            f"(best streak {result.get('best_streak_seconds')}s, "
            f"breaks={result.get('break_count')})"
        )

    if result.get("exercise_complete") and not exercise_already_logged:
        print(
            f"[{label}] EXERCISE COMPLETE — "
            f"{result.get('target_sets')} sets x {result.get('target_seconds')}s held. "
            f"(total breaks={result.get('break_count')})"
        )
        return True

    return exercise_already_logged


@router.websocket("/plank_hold")
async def plank_hold(websocket: WebSocket):
    await websocket.accept()

    print("Client connected: Plank Hold")

    target_seconds = _query_int(websocket, "target_seconds", default=30, lo=5, hi=1800)
    target_sets = _query_int(websocket, "target_sets", default=1, lo=1, hi=20)
    set_number = _query_int(websocket, "set_number", default=1, lo=1, hi=target_sets)

    counter = PlankHoldSession(
        target_seconds=target_seconds,
        target_sets=target_sets,
        set_number=set_number,
    )

    try:
        exercise_logged = False
        last_hold_state = None
        while True:
            image = await websocket.receive_text()

            frame = decode_frame(image)

            timestamp = int(time.time() * 1000)

            result = counter.detect(frame, timestamp)

            if result.get("hold_state") != last_hold_state:
                print(
                    f"[Plank Hold] state -> {result.get('hold_state')} "
                    f"(held {result.get('hold_seconds')}s / {result.get('target_seconds')}s, "
                    f"set {result.get('set_number')}/{result.get('target_sets')})"
                )
                last_hold_state = result.get("hold_state")

            exercise_logged = _log_hold_progress("Plank Hold", result, exercise_logged)

            await websocket.send_json(result)

            await asyncio.sleep(0.001)

    except WebSocketDisconnect:
        print("Disconnected: Plank Hold")

    finally:
        counter.close()
