from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import asyncio
import base64
import time
import traceback

import cv2
import numpy as np

from src.detectors.upper_body.lateral_raise import LateralRaiseSession

router = APIRouter()


def decode_frame(raw: str):
    if "," in raw:
        raw = raw.split(",")[1]

    image_bytes = base64.b64decode(raw)
    np_array = np.frombuffer(image_bytes, dtype=np.uint8)

    return cv2.imdecode(np_array, cv2.IMREAD_COLOR)


def _query_int(websocket: WebSocket, name: str, default: int, lo: int, hi: int) -> int:
    """Read an integer query param off the websocket URL, clamped to [lo, hi].

    This is how the coach-assigned plan (reps per set / number of sets /
    which set this connection is for) reaches the backend. The frontend
    sends these when it opens the socket; it does NOT get to decide on its
    own whether that plan has been completed — LateralRaiseSession is the
    only thing that sets `session_complete` / `exercise_complete` in the
    response.
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
    """Print exactly one line per completed rep, and one line when the
    exercise finishes — never per-frame. `rep_completed` coming out of
    LateralRaiseAnalyzer is already an edge-triggered flag (True only on
    the one frame a rep lands), so we don't need to track our own counter
    for reps.

    Returns the (possibly updated) `exercise_already_logged` flag — pass it
    back in on the next call so the "exercise complete" line only prints
    once even though `exercise_complete` stays True on subsequent frames
    until the socket closes.
    """
    if result.get("rep_completed"):
        rep_count = result.get("rep_count")
        target_reps = result.get("target_reps")
        set_number = result.get("set_number")
        target_sets = result.get("target_sets")
        quality = result.get("rep_form_quality") or "n/a"
        tempo = result.get("rep_classification") or "n/a"
        issues = ",".join(result.get("posture_issues") or []) or "none"
        print(
            f"[{label}] Rep {rep_count}/{target_reps} "
            f"(set {set_number}/{target_sets}) — quality={quality} tempo={tempo} issues={issues}"
        )

    if result.get("exercise_complete") and not exercise_already_logged:
        print(
            f"[{label}] EXERCISE COMPLETE — "
            f"{result.get('target_sets')} sets x {result.get('target_reps')} reps done. "
            f"(good={result.get('good_reps')} / flawed={result.get('flawed_reps')})"
        )
        return True

    return exercise_already_logged


@router.websocket("/lateral_raise")
async def lateral_raise(websocket: WebSocket):
    await websocket.accept()

    # DEBUG MARKER — if you don't see this exact string in your container logs on connect,
    # the running container is not using this file. Remove once counting is confirmed working.
    print("Client connected: LateralRaise [build: smoothed-lift-fix-v2]")

    target_reps = _query_int(websocket, "target_reps", default=10, lo=1, hi=100)
    target_sets = _query_int(websocket, "target_sets", default=1, lo=1, hi=20)
    set_number = _query_int(websocket, "set_number", default=1, lo=1, hi=target_sets)

    counter = LateralRaiseSession(
        target_reps=target_reps,
        target_sets=target_sets,
        set_number=set_number,
    )

    try:
        exercise_logged = False

        # PoseEngine (MediaPipe) requires each frame's timestamp to be strictly greater than
        # the last one it saw. Two frames processed close enough together can round to the same
        # millisecond under time.time(), which MediaPipe treats as invalid and raises on — and
        # since nothing below was catching that, it silently killed the whole session mid-set
        # (the frontend just froze on the last good frame, with no visible error). This forces
        # every timestamp we hand to the engine to be at least 1ms after the last one, no matter
        # how fast frames arrive.
        last_ts = 0

        # DEBUG — logs only when stage or smoothed_lift changes meaningfully, so you can watch
        # the container logs while doing a rep and see exactly where it stalls (or confirm it's
        # tracking fine and the freeze is elsewhere). Remove once counting is confirmed working.
        last_logged_stage = None
        last_logged_lift_bucket = None

        while True:
            image = await websocket.receive_text()

            try:
                frame = decode_frame(image)
            except Exception:
                # A corrupted/partial frame over the wire shouldn't end the session.
                traceback.print_exc()
                continue

            if frame is None:
                continue

            timestamp = max(int(time.time() * 1000), last_ts + 1)
            last_ts = timestamp

            try:
                result = counter.detect(frame, timestamp)
            except Exception:
                # One bad frame (a MediaPipe hiccup, a landmark edge case, etc.) should never
                # take down the whole session — log it and keep going so tracking and rep
                # counting can pick right back up on the next frame.
                traceback.print_exc()
                continue

            # DEBUG — remove once counting is confirmed working.
            stage = result.get("stage")
            lift = result.get("smoothed_lift")
            lift_bucket = round(lift / 10) if lift is not None else None
            if stage != last_logged_stage or lift_bucket != last_logged_lift_bucket:
                print(
                    f"[LateralRaise][DEBUG] stage={stage} smoothed_lift={lift} "
                    f"raw_lift={result.get('lift')} pose_detected={result.get('pose_detected')} "
                    f"low_visibility={result.get('low_visibility')}"
                )
                last_logged_stage = stage
                last_logged_lift_bucket = lift_bucket

            exercise_logged = _log_rep_progress("LateralRaise", result, exercise_logged)

            await websocket.send_json(result)

            await asyncio.sleep(0.001)

    except WebSocketDisconnect:
        print("Disconnected: LateralRaise")

    finally:
        counter.close()
