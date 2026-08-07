from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import asyncio
import base64
import time

import cv2
import numpy as np

from src.detectors.lower_body.bulgarian_split_squat import (
    BulgarianSplitSquatSession,
)

router = APIRouter()


def decode_frame(raw: str):
    if "," in raw:
        raw = raw.split(",", 1)[1]

    image_bytes = base64.b64decode(raw)
    np_array = np.frombuffer(image_bytes, dtype=np.uint8)

    return cv2.imdecode(np_array, cv2.IMREAD_COLOR)


def _query_int(
    websocket: WebSocket,
    name: str,
    default: int,
    lo: int,
    hi: int,
) -> int:
    """Read and clamp an integer query parameter."""

    raw = websocket.query_params.get(name)

    if raw is None:
        return default

    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default

    return max(lo, min(hi, value))


def _query_working_leg(websocket: WebSocket) -> str | None:
    """
    Read the optional caller-provided working-leg label.

    This label is only used for logging and mismatch feedback. The
    BulgarianSplitSquatAnalyzer still detects the actual working leg
    geometrically from the elevated rear ankle.
    """

    raw = websocket.query_params.get("working_leg")

    if raw is None:
        return None

    raw = raw.lower().strip()

    if raw in ("left", "right"):
        return raw

    return None


def _log_rep_progress(
    label: str,
    result: dict,
    exercise_already_logged: bool,
) -> bool:
    """
    Print exactly one line for each completed rep and one line when the
    exercise is complete.
    """

    if result.get("rep_completed"):
        rep_count = result.get("rep_count")
        target_reps = result.get("target_reps")
        set_number = result.get("set_number")
        target_sets = result.get("target_sets")
        front_leg = result.get("front_leg") or "unknown"
        quality = result.get("rep_form_quality") or "n/a"
        tempo = result.get("rep_classification") or "n/a"
        depth = result.get("depth_quality") or "n/a"
        flaws = result.get("rep_flaws") or []

        print(
            f"[{label}] Rep {rep_count}/{target_reps} "
            f"(set {set_number}/{target_sets}) — "
            f"front_leg={front_leg} "
            f"quality={quality} "
            f"depth={depth} "
            f"tempo={tempo} "
            f"flaws={flaws}"
        )

    if result.get("exercise_complete") and not exercise_already_logged:
        print(
            f"[{label}] EXERCISE COMPLETE — "
            f"{result.get('target_sets')} sets x "
            f"{result.get('target_reps')} reps done."
        )
        return True

    return exercise_already_logged


@router.websocket("/bulgarian_split_squat")
async def bulgarian_split_squat(websocket: WebSocket):
    await websocket.accept()

    print("Client connected: Bulgarian Split Squat")

    target_reps = _query_int(
        websocket,
        "target_reps",
        default=10,
        lo=1,
        hi=200,
    )

    target_sets = _query_int(
        websocket,
        "target_sets",
        default=1,
        lo=1,
        hi=20,
    )

    set_number = _query_int(
        websocket,
        "set_number",
        default=1,
        lo=1,
        hi=target_sets,
    )

    working_leg = _query_working_leg(websocket)

    counter = BulgarianSplitSquatSession(
        target_reps=target_reps,
        target_sets=target_sets,
        set_number=set_number,
        working_leg=working_leg,
    )

    try:
        exercise_logged = False

        while True:
            image = await websocket.receive_text()

            frame = decode_frame(image)

            if frame is None:
                await websocket.send_json(
                    {
                        "error": "Unable to decode the received image.",
                        "pose_detected": False,
                    }
                )
                continue

            timestamp = int(time.time() * 1000)

            result = counter.detect(frame, timestamp)

            exercise_logged = _log_rep_progress(
                "Bulgarian Split Squat",
                result,
                exercise_logged,
            )

            await websocket.send_json(result)

            await asyncio.sleep(0.001)

    except WebSocketDisconnect:
        print("Disconnected: Bulgarian Split Squat")

    finally:
        counter.close()
