from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import asyncio
import base64
import time

import cv2
import numpy as np

from src.detectors.cardio.battle_rope import BattleRopeCardioSession

router = APIRouter()


def decode_frame(raw: str):
    if "," in raw:
        raw = raw.split(",")[1]

    image_bytes = base64.b64decode(raw)
    np_array = np.frombuffer(image_bytes, dtype=np.uint8)

    return cv2.imdecode(np_array, cv2.IMREAD_COLOR)


def _query_int(websocket: WebSocket, name: str, default: int, lo: int, hi: int) -> int:
    """Read an integer query param off the websocket URL, clamped to [lo, hi].

    Same convention as `pushupRoutes.py` / `seatedCableShrugRoutes.py` /
    `plankHoldRoutes.py` — the coach-assigned plan (hold seconds per set /
    number of sets / which set this connection is for) reaches the
    backend this way; the frontend does NOT get to decide on its own
    whether that plan has been completed — `BattleRopeCardioSession` is
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


def _log_hold_progress(label: str, result: dict, exercise_already_logged: bool) -> bool:
    """Print one line whenever the hold state transitions (started
    holding / broke), one line per completed wave (for pace/cadence
    visibility), and one line when the exercise finishes — never
    per-frame. Mirrors the edge-triggered logging convention used by the
    rep-based routes, adapted to a hold timer: there's no single
    `rep_completed` flag here, so state-transition edges are tracked
    locally instead.

    Returns the (possibly updated) `exercise_already_logged` flag — pass
    it back in on the next call so the "exercise complete" line only
    prints once even though `exercise_complete` stays True on subsequent
    frames until the socket closes.
    """
    if result.get("exercise_complete") and not exercise_already_logged:
        print(
            f"[{label}] EXERCISE COMPLETE — "
            f"{result.get('target_sets')} sets x {result.get('target_seconds')}s held, done."
        )
        return True

    return exercise_already_logged


@router.websocket("/battle_rope_cardio")
async def battle_rope_cardio(websocket: WebSocket):
    await websocket.accept()

    print("Client connected: Battle Rope Cardio")

    target_seconds = _query_int(websocket, "target_seconds", default=30, lo=5, hi=600)
    target_sets = _query_int(websocket, "target_sets", default=1, lo=1, hi=20)
    set_number = _query_int(websocket, "set_number", default=1, lo=1, hi=target_sets)

    counter = BattleRopeCardioSession(
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
                    f"[Battle Rope Cardio] hold_state -> {result.get('hold_state')} "
                    f"(hold_seconds={result.get('hold_seconds')}, "
                    f"wave_count={result.get('wave_count')})"
                )
                last_hold_state = result.get("hold_state")

            exercise_logged = _log_hold_progress(
                "Battle Rope Cardio", result, exercise_logged
            )

            await websocket.send_json(result)

            await asyncio.sleep(0.001)

    except WebSocketDisconnect:
        print("Disconnected: Battle Rope Cardio")

    finally:
        counter.close()
