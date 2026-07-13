"""
Single-shot full-body scan.

Unlike the rep-counting detectors (bicep/squat/pushup), this is not a
per-frame streaming session — it analyzes exactly ONE well-framed photo and
returns a full result. No websocket, no rep state, no tempo tracking.

Why height has to come from the user
-------------------------------------
A single 2D camera has no depth information. There is no way to derive an
absolute height (or any other absolute measurement) from pixels alone — a
person standing close to the camera and a taller person standing further
away can produce an identical skeleton in the image. Every camera-based
body-scan product (Bodygram, MeThreeSixty, etc.) solves this the same way:
the user provides ONE ground-truth number, and everything else is derived
as a ratio of that number.

  1. User types their height in cm.
  2. We measure the person's pixel-height in the photo (eye-line to ankle,
     corrected by a standard anthropometric ratio — see EYE_HEIGHT_RATIO).
  3. That gives us `px_per_cm`, a personal scale factor for this photo.
  4. Every other measurement (shoulder width, waist width, etc.) is a
     landmark-to-landmark pixel distance divided by `px_per_cm`.

What's "measured" vs "estimated"
---------------------------------
Pose landmarks alone only give joint positions — they cannot tell you how
much soft tissue/fat sits on the body, because joints don't move based on
that. So anything about body *composition* (waist width, build) is only as
good as the silhouette we can see. If the segmentation model is installed
(see engines/segmentEngine.py), waist width comes from the actual pixel
silhouette and is labelled "measured". If it isn't installed, we fall back
to interpolating between shoulder/hip width, which is a much weaker
approximation, and it's labelled "estimated" so the frontend/product team
can be honest about the confidence level with the user.
"""

from typing import Any, Optional

import numpy as np

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_ELBOW,
    LEFT_EYE,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    LEFT_WRIST,
    MOUTH_LEFT,
    NOSE,
    RIGHT_ANKLE,
    RIGHT_ELBOW,
    RIGHT_EYE,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)
from src.engines.segmentEngine import BACKGROUND, BODY_SKIN, FACE_SKIN, HAIR

# -------------------------------------------------------------------------
# Tunables
# -------------------------------------------------------------------------

MIN_VISIBILITY = 0.3

# Standing anthropometric constant: average eye height is ~93.6% of total
# stature (ergonomics anthropometry tables). Used to convert "eye-line to
# ankle" pixel distance into an estimate of total standing height in
# pixels, since MediaPipe Pose has no literal "top of head" landmark.
EYE_HEIGHT_RATIO = 0.936

# Natural waist sits roughly 45% of the way down from the shoulder line to
# the hip line (upper-mid torso, above the hip bones) — used both to pick
# the row to scan in the segmentation mask, and as the fallback
# interpolation point when segmentation isn't available.
WAIST_FRACTION = 0.45

# Reference palettes for human-readable labels. Not clinical, just
# descriptive — nearest-neighbour match in RGB space.
SKIN_TONE_PALETTE = [
    ("Very Light", (255, 224, 196)),
    ("Light", (241, 194, 162)),
    ("Light Medium", (224, 172, 132)),
    ("Medium", (198, 134, 92)),
    ("Medium Tan", (161, 102, 66)),
    ("Tan", (130, 82, 54)),
    ("Deep", (92, 58, 40)),
    ("Very Deep", (58, 36, 26)),
]

HAIR_COLOR_PALETTE = [
    ("Black", (20, 18, 18)),
    ("Dark Brown", (59, 39, 30)),
    ("Brown", (95, 62, 40)),
    ("Light Brown", (140, 100, 65)),
    ("Blonde", (200, 170, 110)),
    ("Light Blonde", (230, 210, 165)),
    ("Red / Auburn", (130, 60, 40)),
    ("Gray", (150, 150, 150)),
    ("White / Silver", (220, 220, 220)),
]


class BodyScanError(Exception):
    """Raised for user-fixable problems (framing, missing landmarks)."""


# -------------------------------------------------------------------------
# Landmark / geometry helpers
# -------------------------------------------------------------------------


def _px(landmark, w: int, h: int) -> np.ndarray:
    return np.array([landmark.x * w, landmark.y * h], dtype=np.float64)


def _mid(a, b, w: int, h: int) -> np.ndarray:
    return (_px(a, w, h) + _px(b, w, h)) / 2.0


def check_full_body_visible(landmarks) -> None:
    """Raises BodyScanError with a user-facing message if the frame doesn't
    show a clean head-to-ankle view. Call this before doing anything else."""

    required = {
        "head": NOSE,
        "left shoulder": LEFT_SHOULDER,
        "right shoulder": RIGHT_SHOULDER,
        "left hip": LEFT_HIP,
        "right hip": RIGHT_HIP,
        "left knee": LEFT_KNEE,
        "right knee": RIGHT_KNEE,
        "left ankle": LEFT_ANKLE,
        "right ankle": RIGHT_ANKLE,
    }

    missing = [
        name
        for name, idx in required.items()
        if getattr(landmarks[idx], "visibility", 1.0) < MIN_VISIBILITY
    ]

    if missing:
        raise BodyScanError(
            "Full body isn't visible — step back so your head and both "
            "feet are inside the frame (missing: " + ", ".join(missing) + ")."
        )

    shoulder_w = np.linalg.norm(
        _px(landmarks[LEFT_SHOULDER], 1, 1) - _px(landmarks[RIGHT_SHOULDER], 1, 1)
    )
    if shoulder_w < 0.05:
        raise BodyScanError(
            "Face the camera directly — shoulders look too narrow, which "
            "usually means you're turned sideways."
        )


# -------------------------------------------------------------------------
# Scale + measurements
# -------------------------------------------------------------------------


def _compute_px_per_cm(landmarks, w: int, h: int, height_cm: float) -> float:
    eye_mid = _mid(landmarks[LEFT_EYE], landmarks[RIGHT_EYE], w, h)
    ankle_mid = _mid(landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE], w, h)

    eye_to_ankle_px = abs(ankle_mid[1] - eye_mid[1])
    total_height_px = eye_to_ankle_px / EYE_HEIGHT_RATIO

    if total_height_px <= 0:
        raise BodyScanError(
            "Couldn't get a clean height reading — try again with better lighting."
        )

    return total_height_px / height_cm


def _landmark_width_cm(a, b, w: int, h: int, px_per_cm: float) -> float:
    return float(np.linalg.norm(_px(a, w, h) - _px(b, w, h)) / px_per_cm)


def _chain_length_cm(points, w: int, h: int, px_per_cm: float) -> float:
    """Sums pixel distance across a chain of landmarks (e.g. shoulder ->
    elbow -> wrist), which tracks a bent limb far better than a single
    straight-line distance between the two endpoints would."""
    total_px = 0.0
    for a, b in zip(points, points[1:]):
        total_px += float(np.linalg.norm(_px(a, w, h) - _px(b, w, h)))
    return total_px / px_per_cm


def _silhouette_width_cm(
    mask: np.ndarray, center_x_px: float, row_y_px: float, px_per_cm: float
) -> Optional[float]:
    """Scans one row of the segmentation mask outward from center_x_px and
    returns the width (in cm) of the contiguous "person" region there."""

    row = int(np.clip(row_y_px, 0, mask.shape[0] - 1))
    cx = int(np.clip(center_x_px, 0, mask.shape[1] - 1))
    line = mask[row]

    def _is_person(v):
        return v != BACKGROUND

    if not _is_person(line[cx]):
        # Center pixel missed the body (mask noise) — no reliable reading.
        return None

    left = cx
    while left > 0 and _is_person(line[left - 1]):
        left -= 1
    right = cx
    while right < len(line) - 1 and _is_person(line[right + 1]):
        right += 1

    width_px = right - left
    if width_px <= 0:
        return None

    return float(width_px / px_per_cm)


def _nearest_label(
    rgb: tuple[int, int, int], palette: list[tuple[str, tuple[int, int, int]]]
) -> str:
    r, g, b = rgb
    best_name, best_dist = "Unknown", float("inf")
    for name, (pr, pg, pb) in palette:
        dist = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if dist < best_dist:
            best_dist, best_name = dist, name
    return best_name


def _hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = (max(0, min(255, int(c))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _sample_mask_color(
    frame_rgb: np.ndarray, mask: np.ndarray, categories: set[int]
) -> Optional[tuple[int, int, int]]:
    ys, xs = np.where(np.isin(mask, list(categories)))
    if len(ys) < 40:  # not enough pixels for a reliable read
        return None
    pixels = frame_rgb[ys, xs]
    median = np.median(pixels, axis=0)
    return int(median[0]), int(median[1]), int(median[2])


def _sample_patch_color(
    frame_rgb: np.ndarray, center_px: np.ndarray, radius: int = 6
) -> tuple[int, int, int]:
    h, w = frame_rgb.shape[:2]
    cx, cy = int(center_px[0]), int(center_px[1])
    x0, x1 = max(0, cx - radius), min(w, cx + radius)
    y0, y1 = max(0, cy - radius), min(h, cy + radius)
    patch = frame_rgb[y0:y1, x0:x1].reshape(-1, 3)
    if len(patch) == 0:
        return (128, 128, 128)
    median = np.median(patch, axis=0)
    return int(median[0]), int(median[1]), int(median[2])


# -------------------------------------------------------------------------
# Body-composition classification
# -------------------------------------------------------------------------


def _classify_bmi(bmi: float) -> str:
    # Standard WHO adult BMI bands. A general population-level screening
    # indicator, not a diagnosis — doesn't account for muscle mass, frame
    # size, age, or individual variation.
    if bmi < 18.5:
        return "Underweight"
    if bmi < 25:
        return "Normal range"
    if bmi < 30:
        return "Overweight"
    return "Obese range"


def _classify_build(waist_to_height: float, shoulder_to_waist: float) -> str:
    # Waist-to-height ratio (WHtR) is a well-established simple screening
    # metric (target < 0.5 is the commonly cited healthy-range guideline).
    # We're borrowing its bands as a rough visual build classification —
    # NOT a health/medical assessment.
    if waist_to_height < 0.40:
        base = "Lean"
    elif waist_to_height < 0.50:
        base = "Athletic / Fit"
    elif waist_to_height < 0.58:
        base = "Average"
    else:
        base = "Broader build"

    if shoulder_to_waist > 1.35 and base in ("Athletic / Fit", "Average"):
        base += " (broad-shouldered / V-taper)"

    return base


# -------------------------------------------------------------------------
# Public entry point
# -------------------------------------------------------------------------


def analyze_body(
    landmarks,
    frame_bgr: np.ndarray,
    height_cm: float,
    mask: Optional[np.ndarray],
    weight_kg: Optional[float] = None,
) -> dict[str, Any]:
    """
    landmarks : 33-point list from PoseEngine.detect()
    frame_bgr : the captured frame, as read by cv2 (BGR order)
    height_cm : user-entered height, the calibration anchor
    mask      : category mask from SegmentEngine.segment(), or None if the
                segmentation model isn't installed
    weight_kg : optional user-entered weight — enables a BMI figure, which
                is the one number in this whole feature that doesn't
                depend on the camera or any estimation at all.
    """
    if not (100 <= height_cm <= 250):
        raise BodyScanError("Height looks out of range — expected 100-250 cm.")

    check_full_body_visible(landmarks)

    h, w = frame_bgr.shape[:2]
    frame_rgb = frame_bgr[:, :, ::-1]

    px_per_cm = _compute_px_per_cm(landmarks, w, h, height_cm)

    shoulder_mid = _mid(landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER], w, h)
    hip_mid = _mid(landmarks[LEFT_HIP], landmarks[RIGHT_HIP], w, h)

    shoulder_width_cm = _landmark_width_cm(
        landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER], w, h, px_per_cm
    )
    hip_width_cm = _landmark_width_cm(
        landmarks[LEFT_HIP], landmarks[RIGHT_HIP], w, h, px_per_cm
    )

    arm_length_cm = (
        _chain_length_cm(
            [landmarks[LEFT_SHOULDER], landmarks[LEFT_ELBOW], landmarks[LEFT_WRIST]],
            w,
            h,
            px_per_cm,
        )
        + _chain_length_cm(
            [landmarks[RIGHT_SHOULDER], landmarks[RIGHT_ELBOW], landmarks[RIGHT_WRIST]],
            w,
            h,
            px_per_cm,
        )
    ) / 2

    leg_length_cm = (
        _chain_length_cm(
            [landmarks[LEFT_HIP], landmarks[LEFT_KNEE], landmarks[LEFT_ANKLE]],
            w,
            h,
            px_per_cm,
        )
        + _chain_length_cm(
            [landmarks[RIGHT_HIP], landmarks[RIGHT_KNEE], landmarks[RIGHT_ANKLE]],
            w,
            h,
            px_per_cm,
        )
    ) / 2

    torso_length_cm = float(np.linalg.norm(hip_mid - shoulder_mid) / px_per_cm)

    waist_row_y = shoulder_mid[1] + WAIST_FRACTION * (hip_mid[1] - shoulder_mid[1])
    waist_center_x = shoulder_mid[0] + WAIST_FRACTION * (hip_mid[0] - shoulder_mid[0])

    waist_width_cm: Optional[float] = None
    waist_confidence = "estimated"

    if mask is not None:
        waist_width_cm = _silhouette_width_cm(
            mask, waist_center_x, waist_row_y, px_per_cm
        )
        if waist_width_cm is not None:
            waist_confidence = "measured"

    if waist_width_cm is None:
        # Fallback: interpolate between shoulder and hip width. Weaker
        # signal (skeleton doesn't capture soft tissue) but keeps the
        # feature usable without the segmentation model installed.
        waist_width_cm = shoulder_width_cm + WAIST_FRACTION * (
            hip_width_cm - shoulder_width_cm
        )
        waist_confidence = "estimated"

    waist_to_height = waist_width_cm / height_cm
    shoulder_to_waist = shoulder_width_cm / waist_width_cm if waist_width_cm else 0.0
    build_estimate = _classify_build(waist_to_height, shoulder_to_waist)

    # --- Skin tone -------------------------------------------------------
    skin_confidence = "estimated"
    skin_rgb = None
    if mask is not None:
        skin_rgb = _sample_mask_color(frame_rgb, mask, {BODY_SKIN, FACE_SKIN})
        if skin_rgb is not None:
            skin_confidence = "measured"
    if skin_rgb is None:
        cheek_point = _mid(landmarks[LEFT_EYE], landmarks[MOUTH_LEFT], w, h)
        skin_rgb = _sample_patch_color(frame_rgb, cheek_point)

    # --- Hair color --------------------------------------------------------
    hair_confidence = "estimated"
    hair_rgb = None
    if mask is not None:
        hair_rgb = _sample_mask_color(frame_rgb, mask, {HAIR})
        if hair_rgb is not None:
            hair_confidence = "measured"
    if hair_rgb is None:
        # Fallback: small patch above the eye-line, extrapolated using the
        # eye-to-shoulder distance as a proxy for scale. Low confidence —
        # easy to miss if hair colour is close to the background.
        eye_mid = _mid(landmarks[LEFT_EYE], landmarks[RIGHT_EYE], w, h)
        head_span = np.linalg.norm(shoulder_mid - eye_mid) * 0.6
        hair_point = np.array([eye_mid[0], max(0.0, eye_mid[1] - head_span)])
        hair_rgb = _sample_patch_color(frame_rgb, hair_point)

    bmi = None
    bmi_category = None
    if weight_kg is not None and weight_kg > 0:
        bmi = weight_kg / ((height_cm / 100) ** 2)
        bmi_category = _classify_bmi(bmi)

    return {
        "height_cm": round(height_cm, 1),
        "weight_kg": round(weight_kg, 1) if weight_kg else None,
        "bmi": round(bmi, 1) if bmi is not None else None,
        "bmi_category": bmi_category,
        "measurements": {
            "shoulder_width_cm": round(shoulder_width_cm, 1),
            "hip_width_cm": round(hip_width_cm, 1),
            "waist_width_cm": round(waist_width_cm, 1),
            "waist_confidence": waist_confidence,
            "arm_length_cm": round(arm_length_cm, 1),
            "leg_length_cm": round(leg_length_cm, 1),
            "torso_length_cm": round(torso_length_cm, 1),
        },
        "body_composition": {
            "waist_to_height_ratio": round(waist_to_height, 3),
            "shoulder_to_waist_ratio": round(shoulder_to_waist, 3),
            "build_estimate": build_estimate,
        },
        "appearance": {
            "skin_tone_hex": _hex(skin_rgb),
            "skin_tone_label": _nearest_label(skin_rgb, SKIN_TONE_PALETTE),
            "skin_tone_confidence": skin_confidence,
            "hair_color_hex": _hex(hair_rgb),
            "hair_color_label": _nearest_label(hair_rgb, HAIR_COLOR_PALETTE),
            "hair_color_confidence": hair_confidence,
        },
        "disclaimer": (
            "Estimated from a single photo — approximate, not a medical or "
            "clinical measurement. BMI (if shown) is a general population "
            "screening indicator only — it doesn't account for muscle mass "
            "or frame size. None of this replaces an actual health "
            "checkup. You can edit any field manually."
        ),
    }
