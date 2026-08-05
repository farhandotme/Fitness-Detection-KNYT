from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import asyncio
import base64
import time

import cv2
import numpy as np

from src.detectors.bird_dog import BirdDogSession

router = APIRouter()


def decode_frame(raw: str):
    if "," in raw:
        raw = raw.split(",")[1]

    image_bytes = base64.b64decode(raw)
    np_array = np.frombuffer(image_bytes, dtype=np.uint8)

    return cv2.imdecode(np_array, cv2.IMREAD_COLOR)


def _query_int(websocket: WebSocket, name: str, default: int, lo: int, hi: int) -> int:
    """Read an integer query param off the websocket URL, clamped to [lo, hi].

    Same convention as `pushupRoutes.py` / `sidePlankRoutes.py` — the
    coach-assigned plan (reps per set / number of sets / which set)
    reaches the backend this way; the frontend does NOT get to decide on
    its own whether that plan has been completed — `BirdDogSession` is
    the only thing that sets `session_complete` / `exercise_complete` in
    the response.
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
    """Print exactly one line per completed rep, one line per rejected
    (anti-cheat / partial) attempt, and one line when the exercise
    finishes — never per-frame.

    Returns the (possibly updated) `exercise_already_logged` flag — pass
    it back in on the next call so the "exercise complete" line only
    prints once even though `exercise_complete` stays True on subsequent
    frames until the socket closes.
    """
    if result.get("rep_completed"):
        rep_count = result.get("rep_count")
        target_reps = result.get("target_reps")
        set_number = result.get("set_number")
        target_sets = result.get("target_sets")
        quality = result.get("rep_form_quality") or "n/a"
        print(
            f"[{label}] Rep {rep_count}/{target_reps} "
            f"(set {set_number}/{target_sets}) — quality={quality} "
            f"arm={result.get('reach_arm_side')} leg={result.get('reach_leg_side')}"
        )

    if result.get("exercise_complete") and not exercise_already_logged:
        print(
            f"[{label}] EXERCISE COMPLETE — "
            f"{result.get('target_sets')} sets x {result.get('target_reps')} reps done. "
            f"(rejected attempts={result.get('rejected_reps')})"
        )
        return True

    return exercise_already_logged


@router.websocket("/bird_dog")
async def bird_dog(websocket: WebSocket):
    await websocket.accept()

    print("Client connected: Bird Dog")

    target_reps = _query_int(websocket, "target_reps", default=10, lo=1, hi=100)
    target_sets = _query_int(websocket, "target_sets", default=1, lo=1, hi=20)
    set_number = _query_int(websocket, "set_number", default=1, lo=1, hi=target_sets)

    counter = BirdDogSession(
        target_reps=target_reps,
        target_sets=target_sets,
        set_number=set_number,
    )

    try:
        exercise_logged = False
        last_stage = None
        while True:
            image = await websocket.receive_text()

            frame = decode_frame(image)

            timestamp = int(time.time() * 1000)

            result = counter.detect(frame, timestamp)

            if result.get("stage") != last_stage:
                last_stage = result.get("stage")

            exercise_logged = _log_rep_progress("Bird Dog", result, exercise_logged)

            await websocket.send_json(result)

            await asyncio.sleep(0.001)

    except WebSocketDisconnect:
        print("Disconnected: Bird Dog")

    finally:
        counter.close()
