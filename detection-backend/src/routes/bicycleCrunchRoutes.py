from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import asyncio
import base64
import time
import traceback

import cv2
import numpy as np

from src.detectors.bicycle_crunch import BicycleCrunchSession

router = APIRouter()


def decode_frame(raw: str):
    if "," in raw:
        raw = raw.split(",")[1]

    image_bytes = base64.b64decode(raw)
    np_array = np.frombuffer(image_bytes, dtype=np.uint8)

    return cv2.imdecode(np_array, cv2.IMREAD_COLOR)


def _query_int(websocket: WebSocket, name: str, default: int, lo: int, hi: int) -> int:
    """Read an integer query param off the websocket URL, clamped to [lo, hi].

    Same convention as `russianTwistRoutes.py` / `pushupRoutes.py` — the
    coach-assigned plan reaches the backend this way, and the backend
    (via `BicycleCrunchSession`) is the only thing that decides when a
    set / the whole exercise is complete.
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
    if result.get("side_completed"):
        which = result.get("side_completed_which")
        print(
            f"[{label}] {which} touch — L{result.get('left_count')}/"
            f"R{result.get('right_count')} (rep {result.get('rep_count')}/"
            f"{result.get('target_reps')})"
        )

    if result.get("exercise_complete") and not exercise_already_logged:
        print(
            f"[{label}] EXERCISE COMPLETE — "
            f"{result.get('target_sets')} sets x {result.get('target_reps')} reps done."
        )
        return True

    return exercise_already_logged


@router.websocket("/bicycle_crunch")
async def bicycle_crunch(websocket: WebSocket):
    await websocket.accept()

    print("Client connected: Bicycle Crunch")

    target_reps = _query_int(websocket, "target_reps", default=20, lo=1, hi=200)
    target_sets = _query_int(websocket, "target_sets", default=1, lo=1, hi=20)
    set_number = _query_int(websocket, "set_number", default=1, lo=1, hi=target_sets)

    # ---- session construction (this is where PoseEngine.__init__ runs) ----
    # This used to happen with no error handling at all — if the installed
    # `mediapipe` version doesn't support the legacy `mp.solutions.pose.Pose`
    # API that `poseEngine.py` uses (recent mediapipe releases removed
    # `mp.solutions` entirely in favor of the newer Tasks API), this throws
    # immediately, before a single frame is ever processed. From the
    # frontend that's indistinguishable from "not detecting/counting at
    # all" — nothing ever starts. Catching it here at least turns that into
    # a clear, actionable message instead of a silent dead connection.
    try:
        counter = BicycleCrunchSession(
            target_reps=target_reps,
            target_sets=target_sets,
            set_number=set_number,
        )
    except Exception as exc:  # noqa: BLE001 — deliberately broad, see comment above
        tb = traceback.format_exc()
        print(f"[BicycleCrunch] FAILED TO START SESSION: {exc}\n{tb}")
        await websocket.send_json(
            {
                "pose_detected": False,
                "error": f"{type(exc).__name__}: {exc}",
                "feedback": (
                    "Couldn't start pose tracking — check the backend terminal. "
                    "If the error mentions 'mediapipe' and 'solutions', your "
                    "installed mediapipe version doesn't support the API "
                    'poseEngine.py uses (run: python3 -c "import mediapipe as '
                    "mp; print(dir(mp))\" and check whether 'solutions' is in "
                    "the list)."
                ),
            }
        )
        await websocket.close()
        return

    try:
        exercise_logged = False
        while True:
            image = await websocket.receive_text()

            # ---- decode + detect are wrapped per-frame on purpose ----
            # If anything throws here — a malformed frame, or a mismatch
            # between what this file expects from PoseEngine.detect() and
            # what your actual poseEngine.py returns — the old behavior
            # was to let the exception propagate and kill the socket
            # silently. From the frontend that looks exactly like "not
            # counting at all," with no indication anything went wrong.
            # Catching it here means the REAL error (with a full
            # traceback, printed server-side) is what surfaces, instead
            # of a generic disconnect.
            try:
                frame = decode_frame(image)
                if frame is None:
                    await websocket.send_json(
                        {
                            "pose_detected": False,
                            "error": (
                                "Received frame couldn't be decoded as an image "
                                "(decode_frame returned None) — check the "
                                "frontend is sending valid JPEG data URLs."
                            ),
                            "feedback": "Camera frame error — check server logs.",
                        }
                    )
                    continue

                timestamp = int(time.time() * 1000)
                result = counter.detect(frame, timestamp)

            except (
                Exception
            ) as exc:  # noqa: BLE001 — deliberately broad, see comment above
                tb = traceback.format_exc()
                print(f"[BicycleCrunch] ERROR processing frame: {exc}\n{tb}")
                await websocket.send_json(
                    {
                        "pose_detected": False,
                        "error": f"{type(exc).__name__}: {exc}",
                        "feedback": (
                            "Server error while processing this frame — check "
                            "the backend terminal for the full traceback."
                        ),
                    }
                )
                continue

            exercise_logged = _log_rep_progress(
                "BicycleCrunch", result, exercise_logged
            )

            await websocket.send_json(result)

            await asyncio.sleep(0.001)

    except WebSocketDisconnect:
        print("Disconnected: Bicycle Crunch")

    finally:
        counter.close()
