"""
Face analysis — the counterpart to PoseEngine/SegmentEngine for everything
that needs a real face model rather than the 33-point body pose.

Why this is a separate model
------------------------------
MediaPipe Pose gives 5 face-adjacent points (nose, eyes, ears, mouth
corners) — enough for head-tilt and a rough head-size guess, but nowhere
near enough for face shape, face symmetry, smile detection, eye openness,
or eye color. Those need MediaPipe's FaceLandmarker: a 478-point face mesh
(including iris landmarks) plus, optionally, 52 ARKit-style "blendshape"
scores (0-1 activation for things like `mouthSmileLeft`, `eyeBlinkRight`)
that are exactly the signal smile/blink detection actually needs — far
more reliable than trying to hand-roll "is the mouth curved" from raw
mesh points.

Model file — NOT bundled, and this environment has no network access to
fetch it for you. Grab it once and drop it next to the other
`.task`/`.tflite` files, same pattern as segmentEngine.py's selfie model:

    curl -L -o src/landmark-packages/face_landmarker.task \\
      https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task

If the file isn't present, `FaceEngine.available` is False and every
field in this module's output comes back None with a note — the rest of
the body scan still works, it just skips the face-specific fields (same
graceful-degradation contract as segmentation waist/hair readings).

What's genuinely measured vs. hand-tuned heuristic
-----------------------------------------------------
  * Face landmarks / mesh, blendshape scores (smile, eye-blink) — these
    come directly from Google's trained model output. As good as that
    model is.
  * Face shape, face symmetry, eye color, head size — these are OUR
    heuristics layered on top of the raw mesh points (width/height
    ratios, nearest-color-match, bounding box). Reasonable, but nowhere
    near a clinical or forensic-grade classification — labelled
    "heuristic" throughout.
"""

import os
from typing import Any, Optional

import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

MODEL_PATH = "./src/landmark-packages/face_landmarker.task"

# Stable MediaPipe FaceMesh topology indices (478-point model, unchanged
# across MediaPipe versions — these are the standard reference points
# used throughout MediaPipe's own face-geometry documentation/samples).
FOREHEAD_TOP = 10
CHIN = 152
LEFT_CHEEK = 234
RIGHT_CHEEK = 454
LEFT_TEMPLE = 127
RIGHT_TEMPLE = 356
NOSE_TIP = 1
LEFT_EYE_OUTER = 33
LEFT_EYE_INNER = 133
RIGHT_EYE_OUTER = 263
RIGHT_EYE_INNER = 362
LEFT_EYE_TOP = 159
LEFT_EYE_BOTTOM = 145
RIGHT_EYE_TOP = 386
RIGHT_EYE_BOTTOM = 374
MOUTH_LEFT = 61
MOUTH_RIGHT = 291
UPPER_LIP_TOP = 13
LOWER_LIP_BOTTOM = 14
LEFT_IRIS_CENTER = 468
RIGHT_IRIS_CENTER = 473

MIN_FACE_VISIBILITY_PX = 40  # minimum eye-span in pixels to trust any of this

# Eye-openness classification (eyeBlink blendshape: 0 = fully open, 1 =
# fully closed). Thresholds chosen conservatively — a relaxed/normal
# blink rate should read "open" more often than not.
EYE_CLOSED_THRESHOLD = 0.55
EYE_HALF_THRESHOLD = 0.25

SMILE_THRESHOLD = 0.35

EYE_COLOR_PALETTE = [
    ("Dark Brown", (40, 26, 16)),
    ("Brown", (78, 51, 27)),
    ("Amber", (150, 100, 40)),
    ("Hazel", (120, 105, 60)),
    ("Green", (75, 115, 70)),
    ("Gray", (140, 145, 150)),
    ("Blue", (90, 130, 170)),
    ("Light Blue", (150, 190, 210)),
]


def _nearest_label(rgb, palette) -> str:
    r, g, b = rgb
    best_name, best_dist = "Unknown", float("inf")
    for name, (pr, pg, pb) in palette:
        dist = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if dist < best_dist:
            best_dist, best_name = dist, name
    return best_name


def _hex(rgb) -> str:
    r, g, b = (max(0, min(255, int(c))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _px(lm, w, h) -> np.ndarray:
    return np.array([lm.x * w, lm.y * h], dtype=np.float64)


def _sample_patch(frame_rgb: np.ndarray, center: np.ndarray, radius: int = 3):
    h, w = frame_rgb.shape[:2]
    cx, cy = int(center[0]), int(center[1])
    x0, x1 = max(0, cx - radius), min(w, cx + radius)
    y0, y1 = max(0, cy - radius), min(h, cy + radius)
    patch = frame_rgb[y0:y1, x0:x1].reshape(-1, 3)
    if len(patch) == 0:
        return (128, 128, 128)
    m = np.median(patch, axis=0)
    return int(m[0]), int(m[1]), int(m[2])


class FaceEngine:
    """Owns one FaceLandmarker. Call `detect()` per still photo (IMAGE
    mode — this is only ever used for the single-shot body/face scan, not
    the streaming rep-counting sessions)."""

    def __init__(self):
        self.available = os.path.exists(MODEL_PATH)
        self.landmarker: Optional[vision.FaceLandmarker] = None

        if self.available:
            base_options = mp_python.BaseOptions(model_asset_path=MODEL_PATH)
            options = vision.FaceLandmarkerOptions(
                base_options=base_options,
                running_mode=vision.RunningMode.IMAGE,
                num_faces=1,
                output_face_blendshapes=True,
                output_facial_transformation_matrixes=False,
                min_face_detection_confidence=0.5,
                min_face_presence_confidence=0.5,
            )
            self.landmarker = vision.FaceLandmarker.create_from_options(options)

    def detect(self, frame_rgb: np.ndarray):
        """Returns (landmarks, blendshapes) — landmarks is a list of 478
        normalized points or None; blendshapes is a {name: score} dict or
        None (empty dict if the model ran but returned no scores)."""
        if not self.available or self.landmarker is None:
            return None, None

        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
        result = self.landmarker.detect(mp_image)

        if not result.face_landmarks:
            return None, None

        landmarks = result.face_landmarks[0]
        blendshapes = None
        if result.face_blendshapes:
            blendshapes = {c.category_name: c.score for c in result.face_blendshapes[0]}
        return landmarks, blendshapes

    def close(self):
        if self.landmarker is not None:
            self.landmarker.close()


# -------------------------------------------------------------------------
# Heuristics built on top of the raw mesh
# -------------------------------------------------------------------------


def _classify_face_shape(width_px: float, height_px: float, jaw_px: float, forehead_px: float) -> str:
    """Width/height + jaw-to-forehead ratio is the standard hand-rolled
    face-shape heuristic (the same one most "face shape" tutorials use) —
    fine as a descriptive label, not a rigorous classifier."""
    ratio = height_px / max(width_px, 1e-6)
    jaw_forehead_ratio = jaw_px / max(forehead_px, 1e-6)

    if ratio > 1.5:
        return "Long / Rectangular"
    if ratio < 1.15:
        return "Round" if jaw_forehead_ratio > 0.9 else "Square"
    if jaw_forehead_ratio < 0.85:
        return "Heart"
    if jaw_forehead_ratio > 1.05:
        return "Square / Diamond"
    return "Oval"


def analyze_face(
    frame_bgr: np.ndarray,
    engine: FaceEngine,
    px_per_cm: Optional[float] = None,
) -> Optional[dict[str, Any]]:
    """Returns None if the face model isn't installed or no face was
    found — callers should treat that as "skip the face fields", not an
    error, exactly like a missing segmentation mask."""

    if not engine.available:
        return None

    h, w = frame_bgr.shape[:2]
    frame_rgb = frame_bgr[:, :, ::-1]
    landmarks, blendshapes = engine.detect(np.ascontiguousarray(frame_rgb))

    if landmarks is None:
        return None

    eye_span_px = np.linalg.norm(
        _px(landmarks[LEFT_EYE_OUTER], w, h) - _px(landmarks[RIGHT_EYE_OUTER], w, h)
    )
    if eye_span_px < MIN_FACE_VISIBILITY_PX:
        return None

    forehead = _px(landmarks[FOREHEAD_TOP], w, h)
    chin = _px(landmarks[CHIN], w, h)
    l_cheek = _px(landmarks[LEFT_CHEEK], w, h)
    r_cheek = _px(landmarks[RIGHT_CHEEK], w, h)
    l_temple = _px(landmarks[LEFT_TEMPLE], w, h)
    r_temple = _px(landmarks[RIGHT_TEMPLE], w, h)
    nose_tip = _px(landmarks[NOSE_TIP], w, h)
    l_eye_o, r_eye_o = _px(landmarks[LEFT_EYE_OUTER], w, h), _px(landmarks[RIGHT_EYE_OUTER], w, h)
    l_eye_i, r_eye_i = _px(landmarks[LEFT_EYE_INNER], w, h), _px(landmarks[RIGHT_EYE_INNER], w, h)
    mouth_l, mouth_r = _px(landmarks[MOUTH_LEFT], w, h), _px(landmarks[MOUTH_RIGHT], w, h)

    face_width_px = np.linalg.norm(l_cheek - r_cheek)
    face_height_px = np.linalg.norm(forehead - chin)
    jaw_width_px = face_width_px
    forehead_width_px = np.linalg.norm(l_temple - r_temple)

    # --- Face shape (heuristic) ------------------------------------------
    face_shape = _classify_face_shape(face_width_px, face_height_px, jaw_width_px, forehead_width_px)

    # --- Face symmetry: compare left vs right distance from the
    # nose-tip/face-center-line to matched landmark pairs. Averaged across
    # a few pairs so one noisy point doesn't dominate. -------------------
    center_x = (l_cheek[0] + r_cheek[0]) / 2

    def side_pct(left_pt, right_pt) -> float:
        dl = abs(left_pt[0] - center_x)
        dr = abs(right_pt[0] - center_x)
        return 100.0 * (1 - abs(dl - dr) / max(dl, dr, 1e-6))

    symmetry_scores = [
        side_pct(l_eye_o, r_eye_o),
        side_pct(l_eye_i, r_eye_i),
        side_pct(mouth_l, mouth_r),
        side_pct(l_cheek, r_cheek),
    ]
    face_symmetry_pct = float(np.mean(symmetry_scores))

    # --- Smile / eye openness from blendshapes (falls back to None if the
    # model returned no blendshape scores for some reason). --------------
    smile_detected = None
    smile_intensity = None
    left_eye_openness = None
    right_eye_openness = None
    eye_openness_label = None

    if blendshapes:
        smile_l = blendshapes.get("mouthSmileLeft", 0.0)
        smile_r = blendshapes.get("mouthSmileRight", 0.0)
        smile_intensity = float((smile_l + smile_r) / 2)
        smile_detected = smile_intensity > SMILE_THRESHOLD

        blink_l = blendshapes.get("eyeBlinkLeft", 0.0)
        blink_r = blendshapes.get("eyeBlinkRight", 0.0)
        left_eye_openness = round(float(1.0 - blink_l), 2)
        right_eye_openness = round(float(1.0 - blink_r), 2)
        avg_open = (left_eye_openness + right_eye_openness) / 2
        if avg_open < (1 - EYE_CLOSED_THRESHOLD):
            eye_openness_label = "Closed / blinking"
        elif avg_open < (1 - EYE_HALF_THRESHOLD):
            eye_openness_label = "Half-open"
        else:
            eye_openness_label = "Open"

    # --- Eye color: sample iris landmark patches. Explicitly caveated —
    # this needs good, even lighting to mean anything (per the user's own
    # note that eye color needs good lighting). --------------------------
    l_iris = _px(landmarks[LEFT_IRIS_CENTER], w, h)
    r_iris = _px(landmarks[RIGHT_IRIS_CENTER], w, h)
    l_iris_rgb = _sample_patch(frame_rgb, l_iris)
    r_iris_rgb = _sample_patch(frame_rgb, r_iris)
    iris_rgb = tuple(int((a + b) / 2) for a, b in zip(l_iris_rgb, r_iris_rgb))
    eye_color_label = _nearest_label(iris_rgb, EYE_COLOR_PALETTE)

    # --- Head size (measured, once px_per_cm is available from the pose
    # calibration in the same photo). -------------------------------------
    head_size = None
    if px_per_cm:
        head_size = {
            "head_width_cm": round(float(face_width_px / px_per_cm) * 1.35, 1),  # cheek-to-cheek -> full head incl. ears, rough factor
            "head_height_cm": round(float(face_height_px / px_per_cm) * 1.25, 1),  # forehead-to-chin -> crown-to-chin, rough factor
            "confidence": "measured",
            "note": "Derived from the 478-point face mesh bounding box, adjusted by a fixed factor to approximate full cranium size beyond the visible face.",
        }

    return {
        "available": True,
        "face_shape": face_shape,
        "face_symmetry_pct": round(face_symmetry_pct, 1),
        "face_symmetry_label": (
            "Highly symmetric" if face_symmetry_pct >= 95
            else "Normal — minor left/right difference" if face_symmetry_pct >= 88
            else "Noticeable left/right difference"
        ),
        "smile_detected": smile_detected,
        "smile_intensity": round(smile_intensity, 2) if smile_intensity is not None else None,
        "left_eye_openness": left_eye_openness,
        "right_eye_openness": right_eye_openness,
        "eye_openness_label": eye_openness_label,
        "eye_color_hex": _hex(iris_rgb),
        "eye_color_label": eye_color_label,
        "landmark_count": len(landmarks),
        "head_size": head_size,
        "confidence": "heuristic — see module note",
        "note": (
            "Face shape, symmetry %, and eye color are geometric/color "
            "heuristics on top of the raw face mesh, not a clinical or "
            "forensic classification. Smile and eye-openness use the "
            "model's own trained blendshape scores and are more reliable. "
            "Eye color needs even, front-on lighting to be meaningful."
        ),
    }
