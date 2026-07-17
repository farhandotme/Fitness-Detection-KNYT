from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import base64
import time
import cv2
import numpy as np

from src.detectors.jumping_jack import JumpingJackSession

router = APIRouter()


def decode_frame(raw: str):
    if "," in raw:
        raw = raw.split(",", 1)[1]

    try:
        image_bytes = base64.b64decode(raw)
    except Exception:
        return None

    np_array = np.frombuffer(image_bytes, dtype=np.uint8)
    frame = cv2.imdecode(np_array, cv2.IMREAD_COLOR)
    return frame


@router.websocket("/jumping-jack")
async def jumping_jack(websocket: WebSocket):
    await websocket.accept()
    print("Client connected: Jumping Jack")

    counter = JumpingJackSession(target_reps=15)

    try:
        while True:
            image = await websocket.receive_text()
            frame = decode_frame(image)

            if frame is None:
                await websocket.send_json(
                    {
                        "pose_detected": False,
                        "rep_count": counter.analyzer.rep_count,
                        "feedback": "That frame didn't come through — keep going",
                        "stage": counter.analyzer.stage,
                        "session_complete": counter.analyzer._is_complete(),
                    }
                )
                continue

            timestamp = int(time.time() * 1000)

            # If anything inside the detector throws (a bug, an unexpected pose, a bad
            # frame), we don't want that to silently kill the whole websocket connection —
            # the user would just see their session drop with no explanation. Instead we
            # log it, send a friendly message, and keep the session alive so one bad frame
            # can't end the whole workout.
            try:
                result = counter.detect(frame, timestamp)
            except Exception as exc:
                print("Jumping Jack detector error:", repr(exc))
                await websocket.send_json(
                    {
                        "pose_detected": False,
                        "rep_count": counter.analyzer.rep_count,
                        "feedback": "Had trouble reading that frame — keep going",
                        "stage": counter.analyzer.stage,
                        "session_complete": counter.analyzer._is_complete(),
                    }
                )
                continue

            print(
                "pose=",
                result.get("pose_detected"),
                "stage=",
                result.get("stage"),
                "rep=",
                result.get("rep_count"),
                "open=",
                result.get("smoothed_openness"),
                "fb=",
                result.get("feedback"),
            )

            await websocket.send_json(result)
            await asyncio.sleep(0.001)

    except WebSocketDisconnect:
        print("Disconnected: Jumping Jack")
    finally:
        counter.close()
