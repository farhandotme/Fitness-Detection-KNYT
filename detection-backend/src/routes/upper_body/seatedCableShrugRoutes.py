import base64
import json
import time
from typing import Optional

import cv2
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import numpy as np

from src.detectors.upper_body.seated_cable_shrug import SeatedCableRowSession

router = APIRouter()


def decode_frame(raw: str) -> Optional[np.ndarray]:
    """Safely decode raw base64 frame without crashing on corrupt payloads."""
    try:
        if "," in raw:
            raw = raw.split(",")[1]

        image_bytes = base64.b64decode(raw)
        np_array = np.frombuffer(image_bytes, dtype=np.uint8)
        return cv2.imdecode(np_array, cv2.IMREAD_COLOR)
    except Exception:
        return None


def _query_int(
    websocket: WebSocket, name: str, default: Optional[int]
) -> Optional[int]:
    raw = websocket.query_params.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


@router.websocket("/seated_cable_shrug")
@router.websocket("/seated-cable-shrug")
async def seated_cable_row_websocket(websocket: WebSocket):
    await websocket.accept()

    target_reps = _query_int(websocket, "target_reps", default=None)
    target_sets = _query_int(websocket, "target_sets", default=1) or 1
    set_number = _query_int(websocket, "set_number", default=1) or 1

    session: Optional[SeatedCableRowSession] = None

    try:
        session = SeatedCableRowSession(
            target_reps=target_reps, target_sets=target_sets, set_number=set_number
        )

        while True:
            raw = await websocket.receive_text()

            # Handle optional JSON control/reconfiguration frames gracefully
            if raw.startswith("{") and "config" in raw:
                try:
                    payload = json.loads(raw)
                    config = payload.get("config", {})
                    target_reps = config.get("target_reps", target_reps)
                    target_sets = config.get("target_sets", target_sets)
                    set_number = config.get("set_number", set_number)

                    if session:
                        session.close()
                    session = SeatedCableRowSession(
                        target_reps=target_reps,
                        target_sets=target_sets,
                        set_number=set_number,
                    )
                    continue
                except Exception:
                    pass

            frame = decode_frame(raw)
            if frame is None:
                continue

            timestamp_ms = int(time.time() * 1000)

            result = session.detect(frame, timestamp_ms)
            await websocket.send_json(result)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass
    finally:
        if session is not None:
            session.close()
