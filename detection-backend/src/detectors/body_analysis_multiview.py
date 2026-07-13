"""
Multi-view body scan — front + left + right + back.

Why this exists
----------------
`analyze_body()` (single front photo) can only measure *width* — the
left-right extent of the body. It has zero information about *depth*
(front-to-back extent), so "waist width" from one photo is fundamentally
incomplete: two people with the same shoulder-to-shoulder width can have
very different waist circumferences depending on how deep their torso is.

A side photo fixes exactly this gap. Rotate the camera 90° around the
person and what used to be "depth" (invisible from the front) is now the
horizontal axis of the *side* photo — so the exact same silhouette-width
technique used for the front photo, applied to a side photo, measures
depth instead of width.

Width (front/back) + depth (left/right) at the same body height lets us
approximate the actual cross-section as an ellipse and compute real
circumference (Ramanujan's ellipse-perimeter formula) — this is a
genuinely more accurate number than a flat width, and it's how DIY
anthropometry projects typically bridge the gap without a full 3D model.

Still approximate
------------------
This is NOT a 3D body scan. The torso cross-section isn't a perfect
ellipse, camera alignment/distance varies photo to photo, and clothing
adds noise. Treat it as "meaningfully better than one photo," not
"clinically accurate" — see the disclaimer in the returned payload.

Front and back photos are averaged for width (reduces single-photo pose
noise); left and right are averaged for depth the same way. Only the
front photo is required — everything else degrades gracefully and is
flagged in `warnings` / the relevant `confidence` field instead of
failing the whole scan.

Height-only calibration — no weight input anywhere in this file. See the
module docstring in body_analysis.py for why.
"""

import math
from typing import Any, NamedTuple, Optional

import numpy as np

from src.detectors.body_analysis import (
    HAIR_COLOR_PALETTE,
    SKIN_TONE_PALETTE,
    WAIST_FRACTION,
    BodyScanError,
    _arm_clamp_px,
    _assess_appearance_extra,
    _assess_posture,
    _chain_length_cm,
    _classify_build,
    _classify_leg_torso_ratio,
    _compute_px_per_cm,
    _estimate_head_size_cm,
    _hex,
    _landmark_width_cm,
    _mid,
    _nearest_label,
    _pct_match,
    _sample_mask_color,
    _sample_patch_color,
    _segment_lengths,
    _silhouette_width_cm,
    _symmetry_label,
    check_full_body_visible,
)
from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_EAR,
    LEFT_ELBOW,
    LEFT_EYE,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    LEFT_WRIST,
    MOUTH_LEFT,
    RIGHT_ANKLE,
    RIGHT_EAR,
    RIGHT_ELBOW,
    RIGHT_EYE,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
)
from src.engines.segmentEngine import BODY_SKIN, FACE_SKIN, HAIR

# Bust/chest line sits roughly 15% of the way down from the shoulder line
# to the hip line.
CHEST_FRACTION = 0.15

# Fallback depth-to-width ratios, used ONLY if no usable side photo was
# provided — average adult torso proportions. Clearly weaker than a real
# side-photo measurement, always flagged "estimated" when used.
DEPTH_RATIO_FALLBACK = {"chest": 0.62, "waist": 0.78, "hip": 0.70}


class ViewInput(NamedTuple):
    landmarks: list
    frame_bgr: np.ndarray
    mask: Optional[np.ndarray]


def _ellipse_circumference_cm(width_cm: float, depth_cm: float) -> float:
    a, b = width_cm / 2, depth_cm / 2
    return float(math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b))))


def _view_metrics(
    view: ViewInput, height_cm: float, is_side_view: bool = False
) -> dict[str, Any]:
    landmarks, frame_bgr, mask = view
    check_full_body_visible(landmarks, is_side_view=is_side_view)

    h, w = frame_bgr.shape[:2]
    px_per_cm = _compute_px_per_cm(landmarks, w, h, height_cm)

    shoulder_mid = _mid(landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER], w, h)
    hip_mid = _mid(landmarks[LEFT_HIP], landmarks[RIGHT_HIP], w, h)

    shoulder_width_cm = _landmark_width_cm(
        landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER], w, h, px_per_cm
    )
    hip_width_cm = _landmark_width_cm(
        landmarks[LEFT_HIP], landmarks[RIGHT_HIP], w, h, px_per_cm
    )

    def row_width_cm(fraction: float):
        if mask is None:
            return None
        row_y = shoulder_mid[1] + fraction * (hip_mid[1] - shoulder_mid[1])
        row_x = shoulder_mid[0] + fraction * (hip_mid[0] - shoulder_mid[0])
        left_bound, right_bound = _arm_clamp_px(landmarks, w, h, row_y, row_x)
        return _silhouette_width_cm(
            mask,
            row_x,
            row_y,
            px_per_cm,
            left_bound_px=left_bound,
            right_bound_px=right_bound,
            band_px=3,
        )

    return {
        "px_per_cm": px_per_cm,
        "shoulder_width_cm": shoulder_width_cm,
        "hip_width_cm": hip_width_cm,
        "chest_row_cm": row_width_cm(CHEST_FRACTION),
        "waist_row_cm": row_width_cm(WAIST_FRACTION),
        "hip_row_cm": row_width_cm(1.0),
        "shoulder_mid": shoulder_mid,
        "hip_mid": hip_mid,
        "landmarks": landmarks,
        "frame_bgr": frame_bgr,
        "mask": mask,
        "w": w,
        "h": h,
    }


def _avg(values: list[Optional[float]]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _avg_readings(readings: list) -> tuple[Optional[float], bool]:
    """Averages a list of Optional[SilhouetteReading] (e.g. chest_row_cm
    from front + back) into (width_cm, any_arm_contact)."""
    usable = [r for r in readings if r is not None and r.width_cm is not None]
    if not usable:
        return None, False
    width = sum(r.width_cm for r in usable) / len(usable)
    arm_contact = any(r.arm_contact for r in usable)
    return width, arm_contact


def analyze_body_multiview(
    height_cm: float,
    front: ViewInput,
    left: Optional[ViewInput] = None,
    right: Optional[ViewInput] = None,
    back: Optional[ViewInput] = None,
    face_result: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if not (100 <= height_cm <= 250):
        raise BodyScanError("Height looks out of range — expected 100-250 cm.")

    # Front is the only strictly required photo — it alone is enough for
    # a degraded-but-usable result (same as the single-view scan).
    front_m = _view_metrics(front, height_cm)

    warnings: list[str] = []
    views_used = ["front"]

    back_m = None
    if back is not None:
        try:
            back_m = _view_metrics(back, height_cm)
            views_used.append("back")
        except BodyScanError as e:
            warnings.append(f"Back photo skipped: {e}")

    side_metrics = []
    for label, view in (("left", left), ("right", right)):
        if view is None:
            continue
        try:
            side_metrics.append(_view_metrics(view, height_cm, is_side_view=True))
            views_used.append(label)
        except BodyScanError as e:
            warnings.append(f"{label.capitalize()} photo skipped: {e}")

    if not side_metrics:
        warnings.append(
            "No usable side photo — chest/waist/hip circumference is a "
            "rough estimate based on typical body proportions, not a real "
            "depth measurement."
        )

    # --- Width: average front + back --------------------------------------
    front_back = [front_m] + ([back_m] if back_m else [])
    shoulder_width_cm = _avg([m["shoulder_width_cm"] for m in front_back])
    hip_width_landmark_cm = _avg([m["hip_width_cm"] for m in front_back])
    chest_width_cm, chest_arm_contact = _avg_readings(
        [m["chest_row_cm"] for m in front_back]
    )
    waist_width_cm, waist_arm_contact = _avg_readings(
        [m["waist_row_cm"] for m in front_back]
    )
    hip_width_cm, hip_arm_contact = _avg_readings([m["hip_row_cm"] for m in front_back])
    hip_width_cm = hip_width_cm or hip_width_landmark_cm

    if chest_arm_contact or waist_arm_contact or hip_arm_contact:
        warnings.append(
            "Arms appear to be resting against your torso in the front/back "
            "photo — chest/waist/hip width may still run a bit wide even "
            "after correction. For the most accurate reading, retake with "
            "arms held slightly away from your sides."
        )

    # Fallbacks when the segmentation mask wasn't available at all.
    if waist_width_cm is None:
        waist_width_cm = shoulder_width_cm + WAIST_FRACTION * (
            hip_width_landmark_cm - shoulder_width_cm
        )
    if chest_width_cm is None:
        chest_width_cm = shoulder_width_cm + CHEST_FRACTION * (
            hip_width_landmark_cm - shoulder_width_cm
        )

    # --- Depth: average left + right ---------------------------------------
    chest_depth_cm, _ = _avg_readings([m["chest_row_cm"] for m in side_metrics])
    waist_depth_cm, _ = _avg_readings([m["waist_row_cm"] for m in side_metrics])
    hip_depth_cm, _ = _avg_readings([m["hip_row_cm"] for m in side_metrics])

    depth_confidence = (
        "measured"
        if any(v is not None for v in (chest_depth_cm, waist_depth_cm, hip_depth_cm))
        else "estimated"
    )

    if chest_depth_cm is None:
        chest_depth_cm = chest_width_cm * DEPTH_RATIO_FALLBACK["chest"]
    if waist_depth_cm is None:
        waist_depth_cm = waist_width_cm * DEPTH_RATIO_FALLBACK["waist"]
    if hip_depth_cm is None:
        hip_depth_cm = hip_width_cm * DEPTH_RATIO_FALLBACK["hip"]

    # --- Circumference (real depth means this is a real ellipse, not a
    # guess dressed up as one) ----------------------------------------------
    chest_circumference_cm = _ellipse_circumference_cm(chest_width_cm, chest_depth_cm)
    waist_circumference_cm = _ellipse_circumference_cm(waist_width_cm, waist_depth_cm)
    hip_circumference_cm = _ellipse_circumference_cm(hip_width_cm, hip_depth_cm)

    # Real WHtR uses waist *circumference* — with a side photo, this is
    # now the metric as it's actually defined in the literature, not the
    # width-only proxy the single-photo version had to use.
    waist_to_height = waist_circumference_cm / height_cm
    shoulder_to_waist = shoulder_width_cm / waist_width_cm if waist_width_cm else 0.0
    waist_to_hip = (
        waist_circumference_cm / hip_circumference_cm if hip_circumference_cm else 0.0
    )
    build_estimate = _classify_build(waist_to_height, shoulder_to_waist)

    # --- Limb lengths + everything else geometric, from the front photo ---
    landmarks, w, h, px_per_cm = (
        front_m["landmarks"],
        front_m["w"],
        front_m["h"],
        front_m["px_per_cm"],
    )

    seg = _segment_lengths(landmarks, w, h, px_per_cm)
    upper_arm_cm = (seg["upper_arm_l"] + seg["upper_arm_r"]) / 2
    forearm_cm = (seg["forearm_l"] + seg["forearm_r"]) / 2
    thigh_cm = (seg["thigh_l"] + seg["thigh_r"]) / 2
    lower_leg_cm = (seg["lower_leg_l"] + seg["lower_leg_r"]) / 2

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
    torso_length_cm = float(
        np.linalg.norm(front_m["hip_mid"] - front_m["shoulder_mid"]) / px_per_cm
    )
    ear_mid = _mid(landmarks[LEFT_EAR], landmarks[RIGHT_EAR], w, h)
    neck_length_cm = float(
        np.linalg.norm(ear_mid - front_m["shoulder_mid"]) / px_per_cm
    )
    ankle_mid = _mid(landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE], w, h)
    inseam_cm = float(np.linalg.norm(ankle_mid - front_m["hip_mid"]) / px_per_cm)
    sleeve_length_cm = neck_length_cm * 0.5 + arm_length_cm

    leg_to_torso = leg_length_cm / torso_length_cm if torso_length_cm else 0.0
    arm_to_height = arm_length_cm / height_cm
    proportion_summary = _classify_leg_torso_ratio(leg_to_torso)

    arm_l = seg["upper_arm_l"] + seg["forearm_l"]
    arm_r = seg["upper_arm_r"] + seg["forearm_r"]
    leg_l = seg["thigh_l"] + seg["lower_leg_l"]
    leg_r = seg["thigh_r"] + seg["lower_leg_r"]
    arm_symmetry_pct = _pct_match(arm_l, arm_r)
    leg_symmetry_pct = _pct_match(leg_l, leg_r)
    overall_symmetry_pct = (arm_symmetry_pct + leg_symmetry_pct) / 2

    posture = _assess_posture(landmarks, w, h)

    if face_result is not None and face_result.get("head_size") is not None:
        head_size = face_result["head_size"]
    else:
        head_size = _estimate_head_size_cm(landmarks, w, h, px_per_cm)

    # --- Skin tone / hair color, front blended with back where available ---
    frame_rgb = front_m["frame_bgr"][:, :, ::-1]

    skin_confidence = "estimated"
    skin_rgb = None
    if front_m["mask"] is not None:
        skin_rgb = _sample_mask_color(
            frame_rgb, front_m["mask"], {BODY_SKIN, FACE_SKIN}
        )
        if skin_rgb is not None:
            skin_confidence = "measured"
    if skin_rgb is None:
        cheek_point = _mid(landmarks[LEFT_EYE], landmarks[MOUTH_LEFT], w, h)
        skin_rgb = _sample_patch_color(frame_rgb, cheek_point)

    hair_confidence = "estimated"
    hair_samples = []
    if front_m["mask"] is not None:
        s = _sample_mask_color(frame_rgb, front_m["mask"], {HAIR})
        if s is not None:
            hair_samples.append(s)
    if back_m is not None and back_m["mask"] is not None:
        back_rgb = back_m["frame_bgr"][:, :, ::-1]
        s = _sample_mask_color(back_rgb, back_m["mask"], {HAIR})
        if s is not None:
            hair_samples.append(s)

    if hair_samples:
        hair_rgb = tuple(int(np.mean([s[i] for s in hair_samples])) for i in range(3))
        hair_confidence = "measured"
    else:
        eye_mid = _mid(landmarks[LEFT_EYE], landmarks[RIGHT_EYE], w, h)
        head_span = np.linalg.norm(front_m["shoulder_mid"] - eye_mid) * 0.6
        hair_point = np.array([eye_mid[0], max(0.0, eye_mid[1] - head_span)])
        hair_rgb = _sample_patch_color(frame_rgb, hair_point)

    appearance_extra = _assess_appearance_extra(
        landmarks, frame_rgb, front_m["mask"], w, h
    )

    result: dict[str, Any] = {
        "height_cm": round(height_cm, 1),
        "views_used": views_used,
        "warnings": warnings,
        "measurements": {
            "shoulder_width_cm": round(shoulder_width_cm, 1),
            "hip_width_cm": round(hip_width_cm, 1),
            "neck_length_cm": round(neck_length_cm, 1),
            "torso_length_cm": round(torso_length_cm, 1),
            "upper_arm_length_cm": round(upper_arm_cm, 1),
            "forearm_length_cm": round(forearm_cm, 1),
            "arm_length_cm": round(arm_length_cm, 1),
            "sleeve_length_cm": round(sleeve_length_cm, 1),
            "thigh_length_cm": round(thigh_cm, 1),
            "lower_leg_length_cm": round(lower_leg_cm, 1),
            "leg_length_cm": round(leg_length_cm, 1),
            "inseam_cm": round(inseam_cm, 1),
            "head_width_cm": head_size["head_width_cm"],
            "head_height_cm": head_size["head_height_cm"],
            "head_size_confidence": head_size["confidence"],
        },
        "circumference": {
            "chest_cm": round(chest_circumference_cm, 1),
            "waist_cm": round(waist_circumference_cm, 1),
            "hip_cm": round(hip_circumference_cm, 1),
            "confidence": depth_confidence,
        },
        "body_proportions": {
            "shoulder_to_waist_ratio": round(shoulder_to_waist, 3),
            "waist_to_hip_ratio": round(waist_to_hip, 3),
            "waist_to_height_ratio": round(waist_to_height, 3),
            "leg_to_torso_ratio": round(leg_to_torso, 3),
            "arm_to_height_ratio": round(arm_to_height, 3),
            "build_estimate": build_estimate,
            "proportion_summary": proportion_summary,
        },
        "symmetry": {
            "arm_symmetry_pct": round(arm_symmetry_pct, 1),
            "leg_symmetry_pct": round(leg_symmetry_pct, 1),
            "overall_symmetry_pct": round(overall_symmetry_pct, 1),
            "label": _symmetry_label(overall_symmetry_pct),
            "note": (
                "Compares left vs right limb length in the front photo — "
                "pose, camera angle, and clothing all affect this reading "
                "as much as real anatomy does."
            ),
        },
        "posture": posture,
        "appearance": {
            "skin_tone_hex": _hex(skin_rgb),
            "skin_tone_label": _nearest_label(skin_rgb, SKIN_TONE_PALETTE),
            "skin_tone_confidence": skin_confidence,
            "hair_color_hex": _hex(hair_rgb),
            "hair_color_label": _nearest_label(hair_rgb, HAIR_COLOR_PALETTE),
            "hair_color_confidence": hair_confidence,
            **appearance_extra,
        },
        "disclaimer": (
            "Estimated from photos — approximate, not a medical, clinical, "
            "or tailoring-grade measurement. Circumference uses an ellipse "
            "approximation from width + depth, not a direct tape "
            "measurement. Posture and symmetry readings are screening "
            "signals only. None of this replaces an actual health checkup "
            "or professional fitting. You can edit any field manually."
        ),
    }

    if face_result is not None:
        result["face"] = {k: v for k, v in face_result.items() if k != "head_size"}

    return result
