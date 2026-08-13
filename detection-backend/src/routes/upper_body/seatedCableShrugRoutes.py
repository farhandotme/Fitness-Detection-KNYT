from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import cv2
import numpy as np
import base64
import json
from typing import Optional

from src.detectors.upper_body.seated_cable_shrug import SeatedCableRowSession

router = APIRouter()


@router.websocket("/ws/seated_cable_shrug")
@router.websocket("/seated_cable_shrug")
async def seated_cable_row_websocket(websocket: WebSocket):
    await websocket.accept()

    # Extract query parameters sent by the frontend connection URL
    query_params = websocket.query_params
    target_reps_param = query_params.get("target_reps")
    target_sets_param = query_params.get("target_sets")
    set_number_param = query_params.get("set_number")

    target_reps: Optional[int] = int(target_reps_param) if target_reps_param else None
    target_sets: int = int(target_sets_param) if target_sets_param else 1
    set_number: int = int(set_number_param) if set_number_param else 1

    session = SeatedCableRowSession(
        target_reps=target_reps, target_sets=target_sets, set_number=set_number
    )

    try:
        while True:
            raw_data = await websocket.receive_text()
            payload = json.loads(raw_data)

            if "config" in payload:
                config = payload["config"]
                target_reps = config.get("target_reps", target_reps)
                target_sets = config.get("target_sets", target_sets)
                set_number = config.get("set_number", set_number)
                session = SeatedCableRowSession(
                    target_reps=target_reps,
                    target_sets=target_sets,
                    set_number=set_number,
                )

            frame_data = payload.get("frame") or payload.get("image")
            if not frame_data:
                continue

            if "," in frame_data:
                frame_data = frame_data.split(",")[1]

            img_bytes = base64.b64decode(frame_data)
            np_arr = np.frombuffer(img_bytes, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

            if frame is None:
                continue

            timestamp_ms = payload.get(
                "timestamp_ms", int(cv2.getTickCount() / cv2.getTickFrequency() * 1000)
            )

            result = session.detect(frame, timestamp_ms)
            await websocket.send_text(json.dumps(result))

    except WebSocketDisconnect:
        if session:
            session.close()
    except Exception as e:
        if session:
            session.close()
        try:
            await websocket.send_text(json.dumps({"error": str(e)}))
        except:
            pass
