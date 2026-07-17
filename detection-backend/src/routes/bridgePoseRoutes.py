from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import base64
import time

import cv2
import numpy as np

from src.detectors.bridge_pose import BridgeHoldSession

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


@router.websocket("/bridge_hold")
async def bridge_hold(websocket: WebSocket):
    await websocket.accept()
    print("Client connected: Bridge Hold")

    target_seconds = _query_int(websocket, "target_seconds", default=30, lo=5, hi=1800)
    target_sets = _query_int(websocket, "target_sets", default=1, lo=1, hi=20)
    set_number = _query_int(websocket, "set_number", default=1, lo=1, hi=target_sets)

    counter = BridgeHoldSession(
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

            if frame is None:
                await websocket.send_json(
                    {
                        "hold_state": "invalid_frame",
                        "hold_seconds": 0,
                        "target_seconds": target_seconds,
                        "set_number": set_number,
                        "target_sets": target_sets,
                        "best_streak_seconds": 0,
                        "break_count": 0,
                        "target_reached": False,
                        "exercise_complete": False,
                        "session_complete": False,
                        "debug": {"reason": "decode_failed"},
                    }
                )
                continue

            timestamp = int(time.time() * 1000)
            result = counter.detect(frame, timestamp)

            if result.get("hold_state") != last_hold_state:
                print(
                    f"[Bridge Hold] state -> {result.get('hold_state')} "
                    f"(held {result.get('hold_seconds')}s / {result.get('target_seconds')}s, "
                    f"set {result.get('set_number')}/{result.get('target_sets')})"
                )
                last_hold_state = result.get("hold_state")

            if result.get("target_reached"):
                print(
                    f"[Bridge Hold] Target reached — set {result.get('set_number')}/"
                    f"{result.get('target_sets')}: "
                    f"{result.get('hold_seconds')}s / {result.get('target_seconds')}s "
                    f"(best streak {result.get('best_streak_seconds')}s, "
                    f"breaks={result.get('break_count')})"
                )

            if result.get("exercise_complete") and not exercise_logged:
                print(
                    f"[Bridge Hold] EXERCISE COMPLETE — "
                    f"{result.get('target_sets')} sets x {result.get('target_seconds')}s held. "
                    f"(total breaks={result.get('break_count')})"
                )
                exercise_logged = True

            await websocket.send_json(result)
            await asyncio.sleep(0.001)

    except WebSocketDisconnect:
        print("Disconnected: Bridge Hold")
    finally:
        counter.close()
