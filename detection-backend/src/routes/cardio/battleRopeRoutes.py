"""
WebSocket Router for Battle Rope Cardio Exercise.

Supported Endpoints:
  - ws://localhost:8000/ws/battle_rope
  - ws://localhost:8000/ws/battle_rope_cardio
"""

import base64
import json
import time
import cv2
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.detectors.cardio.battle_rope import BattleRopeCardioSession

router = APIRouter()


def _decode_frame(message: dict) -> np.ndarray | None:
    """Decodes raw binary bytes or base64 text into an OpenCV BGR image."""
    # Case 1: Raw binary frame bytes
    if "bytes" in message and message["bytes"]:
        np_arr = np.frombuffer(message["bytes"], np.uint8)
        return cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

    # Case 2: Text payload (JSON or raw Base64 string)
    if "text" in message and message["text"]:
        text_data = message["text"].strip()
        base64_str = None

        if text_data.startswith("{"):
            try:
                data = json.loads(text_data)
                if data.get("action") == "stop":
                    return None
                base64_str = data.get("image") or data.get("frame") or data.get("data")
            except json.JSONDecodeError:
                return None
        else:
            base64_str = text_data

        if base64_str:
            if "," in base64_str:
                base64_str = base64_str.split(",")[1]
            try:
                img_bytes = base64.b64decode(base64_str)
                np_arr = np.frombuffer(img_bytes, np.uint8)
                return cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            except Exception:
                return None

    return None


@router.websocket("/battle_rope")
@router.websocket("/battle_rope_cardio")
async def battle_rope_stream(websocket: WebSocket):
    """
    WebSocket handler for Battle Rope live stream.
    Accepts connections to both /ws/battle_rope and /ws/battle_rope_cardio.
    """
    # 1. Complete handshake immediately
    await websocket.accept()

    # 2. Extract query parameters safely
    params = websocket.query_params

    try:
        target_reps = int(params.get("target_reps", 30))
    except (ValueError, TypeError):
        target_reps = 30

    try:
        target_sets = int(params.get("target_sets", 1))
    except (ValueError, TypeError):
        target_sets = 1

    try:
        set_number = int(params.get("set_number", 1))
    except (ValueError, TypeError):
        set_number = 1

    # 3. Initialize engine session
    session = BattleRopeCardioSession(
        target_reps=target_reps,
        target_sets=target_sets,
        set_number=set_number,
    )

    try:
        while True:
            message = await websocket.receive()

            # Check for disconnect signals or control frames
            if message.get("type") == "websocket.disconnect":
                break

            # Decode frame
            frame = _decode_frame(message)

            if frame is None:
                # Skip invalid frames or non-image control frames
                continue

            # Process detection
            timestamp_ms = int(time.time() * 1000)
            analysis = session.detect(frame, timestamp_ms)

            # Push telemetry back to frontend
            await websocket.send_json(analysis)

            # End exercise session if overall target is met
            if analysis.get("exercise_complete"):
                await websocket.send_json(
                    {
                        "type": "SESSION_COMPLETE",
                        "message": "Exercise set completed successfully!",
                    }
                )
                break

    except WebSocketDisconnect:
        print("[BattleRope Router] Client disconnected cleanly.")
    except Exception as e:
        print(f"[BattleRope Router] Stream error: {e}")
    finally:
        session.close()
