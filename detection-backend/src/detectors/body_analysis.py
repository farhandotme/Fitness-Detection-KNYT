"""
Single-shot full-body scan — height-only calibration.

Unlike the rep-counting detectors (bicep/squat/pushup), this is not a
per-frame streaming session — it analyzes exactly ONE well-framed photo and
returns a full result. No websocket, no rep state, no tempo tracking.

Why height (and ONLY height) has to come from the user
---------------------------------------------------------
A single 2D camera has no depth information. There is no way to derive an
absolute size (or weight, or anything absolute) from pixels alone — a
person standing close to the camera and a taller person standing further
away can produce an identical skeleton in the image. Every camera-based
body-scan product solves this the same way: the user provides ONE
ground-truth number, and everything else is derived as a ratio of that
number.

  1. User types their height in cm. That's it — nothing else is required.
  2. We measure the person's pixel-height in the photo (eye-line to ankle,
     corrected by a standard anthropometric ratio — see EYE_HEIGHT_RATIO).
  3. That gives us `px_per_cm`, a personal scale factor for this photo.
  4. Every other measurement below is a landmark-to-landmark pixel
     distance divided by `px_per_cm`.

Weight is deliberately NOT part of this pipeline. A camera cannot measure
mass, so asking for it here would just be a manual data-entry field
dressed up as a "scan" — if the user has to type it anyway, a body-scan
feature isn't adding anything for that number. (BMI needs weight; if you
want it back later, it's a two-line addition — weight in, `weight_kg /
(height_m ** 2)` out — but it lives outside this camera-measurement
pipeline, not mixed into it.)

Confidence labelling — the honesty contract this file follows throughout
--------------------------------------------------------------------------
Every derived figure below is one of:
  "measured"    — read directly from the actual pixel silhouette
                  (segmentation mask) or, for head/face metrics, from the
                  478-point Face Landmarker mesh when that model is
                  installed (see face_analysis.py).
  "estimated"   — interpolated/approximated from skeleton joints alone,
                  because the stronger signal (segmentation model / face
                  model) isn't installed or didn't return a usable read.
  "approximate" — a small extra notch below "estimated": derived from an
                  average anthropometric ratio rather than anything
                  photo-specific (e.g. neck length, sleeve length — there
                  is no dedicated "neck" or "collar" landmark in the pose
                  model, so these lean on standard body-proportion
                  constants). Treat these as rough.

Nothing here is a medical or tailoring-grade measurement. See the
`disclaimer` field in the returned payload.
"""

import math
from typing import Any, NamedTuple, Optional

import numpy as np

from src.engines.poseEngine import (  # type: ignore
    LEFT_ANKLE,
    LEFT_EAR,
    LEFT_ELBOW,
    LEFT_EYE,
    LEFT_EYE_OUTER,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    LEFT_WRIST,
    MOUTH_LEFT,
    MOUTH_RIGHT,
    NOSE,
    RIGHT_ANKLE,
    RIGHT_EAR,
    RIGHT_ELBOW,
    RIGHT_EYE,
    RIGHT_EYE_OUTER,
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
# the hip line (upper-mid torso, above the hip bones).
WAIST_FRACTION = 0.45

# Rough anthropometric constants for the pose-only ("approximate") head
# size fallback, used only when the Face Landmarker model isn't installed.
# Bizygomatic (head) width runs roughly 2x the outer-eye-corner span;
# crown-to-chin head height runs roughly 3.6x the eye-to-mouth span (the
# classic "face divided into thirds" proportion, extended up past the
# eyebrow line to the hairline/crown).
HEAD_WIDTH_TO_EYE_SPAN_RATIO = 2.0
HEAD_HEIGHT_TO_EYE_MOUTH_RATIO = 3.6

# Tolerance bands for posture screening — small angles are normal
# photo/stance noise, not a real postural finding.
POSTURE_NOISE_DEG = 2.5
POSTURE_NOTABLE_DEG = 6.0

# Symmetry bands (percent match between left/right limb lengths).
SYMMETRY_HIGH_PCT = 97.0
SYMMETRY_NORMAL_PCT = 92.0

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


def check_full_body_visible(landmarks, is_side_view: bool = False) -> None:
    """Raises BodyScanError with a user-facing message if the frame doesn't
    show a clean head-to-ankle view. Call this before doing anything else.

    `is_side_view=True` is for left/right photos in a multi-view scan,
    where the person is turned ~90 degrees on purpose. Two things follow
    from that on purpose:
      1. Shoulder width naturally collapses -- that's the whole point of
         a side photo, so we skip the "shoulders look too narrow" check.
      2. The FAR leg is genuinely, physically occluded by the near leg in
         a true profile shot. MediaPipe correctly reports low visibility
         for it -- that's the model being honest about not being able to
         see something, not a bad photo. Requiring BOTH legs' landmarks
         (like the front-facing check does) rejects every correctly-taken
         side photo. We only require ONE full leg chain (whichever side
         is actually facing the camera) plus the head.
    """

    head_ok = getattr(landmarks[NOSE], "visibility", 1.0) >= MIN_VISIBILITY

    if is_side_view:

        def chain_visibility(idxs) -> float:
            return min(getattr(landmarks[i], "visibility", 1.0) for i in idxs)

        left_chain = chain_visibility((LEFT_SHOULDER, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE))
        right_chain = chain_visibility(
            (RIGHT_SHOULDER, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE)
        )

        if not head_ok or max(left_chain, right_chain) < MIN_VISIBILITY:
            raise BodyScanError(
                "Full body isn't visible — step back so your head and both "
                "feet are inside the frame."
            )
        return

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
# Scale + linear measurements
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


def _segment_lengths(landmarks, w, h, px_per_cm) -> dict[str, float]:
    """Every individual limb segment, per side, plus the bilateral average
    used in the main measurements block. Kept as its own function so both
    the tailoring measurements AND the symmetry check below can share one
    source of truth instead of re-deriving these numbers twice."""

    def d(a_idx, b_idx):
        return _landmark_width_cm(landmarks[a_idx], landmarks[b_idx], w, h, px_per_cm)

    return {
        "upper_arm_l": d(LEFT_SHOULDER, LEFT_ELBOW),
        "upper_arm_r": d(RIGHT_SHOULDER, RIGHT_ELBOW),
        "forearm_l": d(LEFT_ELBOW, LEFT_WRIST),
        "forearm_r": d(RIGHT_ELBOW, RIGHT_WRIST),
        "thigh_l": d(LEFT_HIP, LEFT_KNEE),
        "thigh_r": d(RIGHT_HIP, RIGHT_KNEE),
        "lower_leg_l": d(LEFT_KNEE, LEFT_ANKLE),
        "lower_leg_r": d(RIGHT_KNEE, RIGHT_ANKLE),
    }


def _arm_clamp_px(
    landmarks, w: int, h: int, row_y_px: float, center_x_px: float
) -> tuple[float, float]:
    """Returns (left_bound_px, right_bound_px) the silhouette scan must not
    cross, derived from where THIS person's elbow/wrist actually are in
    THIS photo.

    Why this exists
    ----------------
    In a natural standing pose, arms hang at the sides and their silhouette
    touches (or overlaps) the torso silhouette at exactly chest/waist/hip
    height — the segmentation mask has no "arm" category distinct from
    "torso" (both are BODY_SKIN/CLOTHES), so a plain contiguous-region scan
    from the torso center doesn't stop at the true torso edge, it keeps
    going straight out through the arm. That silently inflates waist/chest
    readings by several centimeters for anyone photographed with relaxed
    arms — which is most people, since "hold your arms slightly out" is
    not something anyone thinks to do unprompted.

    Real body-scanning apps solve this by instructing an A-pose. We can't
    force that, so instead we clamp the scan to the nearer of (elbow,
    wrist) on each side whenever that landmark sits close to this row's
    height — the true torso edge is always strictly between the body
    center and the arm attachment point, so this bound can only ever
    correct the reading toward truth, never away from it.
    """
    left_bound, right_bound = 0.0, float("inf")

    for elbow_idx, wrist_idx in ((LEFT_ELBOW, LEFT_WRIST), (RIGHT_ELBOW, RIGHT_WRIST)):
        elbow_px = _px(landmarks[elbow_idx], w, h)
        wrist_px = _px(landmarks[wrist_idx], w, h)
        # Whichever of elbow/wrist is vertically closer to this row is the
        # more relevant bound for it (e.g. waist height is usually nearer
        # the wrist, chest height nearer the elbow).
        candidate = (
            elbow_px
            if abs(elbow_px[1] - row_y_px) <= abs(wrist_px[1] - row_y_px)
            else wrist_px
        )
        if candidate[0] < center_x_px:
            left_bound = max(left_bound, candidate[0])
        else:
            right_bound = min(right_bound, candidate[0])

    return left_bound, right_bound


class SilhouetteReading(NamedTuple):
    width_cm: Optional[float]
    arm_contact: bool  # True if the arm clamp actually had to cut the scan short


def _silhouette_width_cm(
    mask: np.ndarray,
    center_x_px: float,
    row_y_px: float,
    px_per_cm: float,
    left_bound_px: float = 0.0,
    right_bound_px: Optional[float] = None,
    band_px: int = 0,
) -> SilhouetteReading:
    """Scans one or more rows of the segmentation mask outward from
    center_x_px and returns the median width (in cm) of the contiguous
    "person" region there.

    `left_bound_px`/`right_bound_px` hard-stop the outward scan (see
    `_arm_clamp_px`) so it can't bleed past a nearby arm into an inflated
    reading. `band_px` averages over `2*band_px + 1` adjacent rows
    (median, not mean, so a single noisy row — a clothing fold, a hair
    strand crossing the silhouette edge — can't skew the result the way
    reading exactly one row can).

    `arm_contact` comes back True if the scan actually hit one of those
    bounds instead of reaching real background on its own — meaning the
    arm's silhouette was touching the torso at this row, and the reading,
    while clamped, still can't fully isolate the true torso edge (the
    landmark sits inside the arm's own width, not exactly at its inner
    edge). Treat width_cm as lower-confidence when this is True.
    """

    def _is_person(v):
        return v != BACKGROUND

    def _row_width(row: int) -> Optional[tuple[float, bool]]:
        row = int(np.clip(row, 0, mask.shape[0] - 1))
        cx = int(np.clip(center_x_px, 0, mask.shape[1] - 1))
        lo = int(np.clip(left_bound_px, 0, mask.shape[1] - 1))
        hi = int(
            np.clip(
                right_bound_px if right_bound_px is not None else mask.shape[1] - 1,
                0,
                mask.shape[1] - 1,
            )
        )
        line = mask[row]

        if not _is_person(line[cx]):
            return None

        left = cx
        while left > lo and _is_person(line[left - 1]):
            left -= 1
        hit_left_bound = left == lo and _is_person(line[max(left - 1, 0)])

        right = cx
        while right < hi and _is_person(line[right + 1]):
            right += 1
        hit_right_bound = right == hi and _is_person(
            line[min(right + 1, len(line) - 1)]
        )

        width_px = right - left
        if width_px <= 0:
            return None
        return float(width_px), (hit_left_bound or hit_right_bound)

    row0 = int(np.clip(row_y_px, 0, mask.shape[0] - 1))
    raw = [_row_width(row0 + dy) for dy in range(-band_px, band_px + 1)]
    readings = [r for r in raw if r is not None]
    if not readings:
        return SilhouetteReading(None, False)

    widths = [r[0] for r in readings]
    any_contact = any(r[1] for r in readings)
    return SilhouetteReading(float(np.median(widths) / px_per_cm), any_contact)


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


def _region_hair_fraction(
    mask: Optional[np.ndarray],
    center_px: np.ndarray,
    half_w: float,
    half_h: float,
) -> Optional[float]:
    """Fraction of pixels classified HAIR inside a rectangular region — the
    building block for hair-density, baldness, beard, and mustache checks.
    Returns None if segmentation isn't installed or the region is empty."""
    if mask is None:
        return None
    h, w = mask.shape[:2]
    x0 = int(np.clip(center_px[0] - half_w, 0, w - 1))
    x1 = int(np.clip(center_px[0] + half_w, 0, w - 1))
    y0 = int(np.clip(center_px[1] - half_h, 0, h - 1))
    y1 = int(np.clip(center_px[1] + half_h, 0, h - 1))
    if x1 <= x0 or y1 <= y0:
        return None
    region = mask[y0:y1, x0:x1]
    if region.size == 0:
        return None
    return float(np.mean(region == HAIR))


# -------------------------------------------------------------------------
# Build / proportion classification
# -------------------------------------------------------------------------


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


def _classify_leg_torso_ratio(ratio: float) -> str:
    # Typical adult leg-length : torso-length sits close to 1.0-1.1.
    # Descriptive only — plenty of healthy variation exists outside these
    # bands, this just narrates where the photo landed.
    if ratio < 0.90:
        return "Torso-dominant proportions (longer torso relative to legs)"
    if ratio > 1.20:
        return "Leg-dominant proportions (longer legs relative to torso)"
    return "Balanced torso-to-leg proportions"


def _symmetry_label(pct: float) -> str:
    if pct >= SYMMETRY_HIGH_PCT:
        return "Highly symmetric"
    if pct >= SYMMETRY_NORMAL_PCT:
        return "Normal — minor left/right difference"
    return (
        "Noticeable left/right difference — could be capture angle/pose, "
        "not necessarily a real anatomical asymmetry"
    )


def _pct_match(a: float, b: float) -> float:
    if max(a, b) <= 0:
        return 100.0
    return 100.0 * (1.0 - abs(a - b) / max(a, b))


# -------------------------------------------------------------------------
# Posture screening (single static photo — front-on view)
# -------------------------------------------------------------------------
# Everything here is a coarse SCREENING signal, not a clinical postural
# assessment. A single front-on photo can only see left-right (coronal
# plane) misalignment — it is blind to forward/backward (sagittal plane)
# issues like rounded shoulders or a forward head, which genuinely need a
# side photo to see at all. That limitation is stated up front in the
# payload rather than silently guessed at.


def _signed_angle_deg(a: np.ndarray, b: np.ndarray) -> float:
    """Signed angle (degrees) of the line a->b off horizontal. Positive =
    b is lower than a (tilted down to the right, in image coordinates)."""
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


def _posture_flag(angle_deg: float, high_label: str, low_label: str) -> Optional[str]:
    if abs(angle_deg) < POSTURE_NOISE_DEG:
        return None
    side = high_label if angle_deg > 0 else low_label
    severity = "notable" if abs(angle_deg) >= POSTURE_NOTABLE_DEG else "slight"
    return f"{severity.capitalize()} {side} ({abs(angle_deg):.1f}°)"


def _assess_posture(landmarks, w: int, h: int) -> dict[str, Any]:
    l_eye, r_eye = _px(landmarks[LEFT_EYE], w, h), _px(landmarks[RIGHT_EYE], w, h)
    l_ear, r_ear = _px(landmarks[LEFT_EAR], w, h), _px(landmarks[RIGHT_EAR], w, h)
    l_sh, r_sh = _px(landmarks[LEFT_SHOULDER], w, h), _px(
        landmarks[RIGHT_SHOULDER], w, h
    )
    l_hip, r_hip = _px(landmarks[LEFT_HIP], w, h), _px(landmarks[RIGHT_HIP], w, h)
    l_knee, r_knee = _px(landmarks[LEFT_KNEE], w, h), _px(landmarks[RIGHT_KNEE], w, h)
    l_ank, r_ank = _px(landmarks[LEFT_ANKLE], w, h), _px(landmarks[RIGHT_ANKLE], w, h)

    shoulder_mid = (l_sh + r_sh) / 2
    hip_mid = (l_hip + r_hip) / 2
    ear_mid = (l_ear + r_ear) / 2
    ankle_mid = (l_ank + r_ank) / 2
    shoulder_width = np.linalg.norm(l_sh - r_sh) or 1.0

    # Head tilt: eye line off horizontal (image is mirrored for display,
    # but landmark left/right is anatomical, so the sign here is stable).
    head_tilt_deg = _signed_angle_deg(l_eye, r_eye)
    # Shoulder / hip tilt: same idea, one line each.
    shoulder_tilt_deg = _signed_angle_deg(l_sh, r_sh)
    hip_tilt_deg = _signed_angle_deg(l_hip, r_hip)

    # Neck alignment: horizontal offset of the ear midpoint from the
    # shoulder midpoint, normalized by shoulder width. Only a rough proxy
    # for forward-head posture from a front photo — flagged as such.
    neck_offset_ratio = (ear_mid[0] - shoulder_mid[0]) / shoulder_width

    # Spine lateral lean: horizontal offset between shoulder and hip
    # midpoints, normalized by shoulder width.
    spine_lean_ratio = (shoulder_mid[0] - hip_mid[0]) / shoulder_width

    # Body balance: where the ankle midpoint sits relative to the
    # shoulder midline — a rough static weight-distribution proxy.
    balance_ratio = (ankle_mid[0] - shoulder_mid[0]) / shoulder_width

    # Limb alignment (static knee valgus/varus screen): perpendicular
    # deviation of the knee from the hip->ankle line, normalized by thigh
    # length — same interpolation-deviation technique used for hip-sag/
    # pike detection in the push-up analyzer, applied per leg here.
    def knee_deviation(hip, knee, ankle) -> Optional[float]:
        dx = ankle[0] - hip[0]
        if abs(dx) < 1e-6:
            return None
        t = (knee[0] - hip[0]) / dx
        expected_x = hip[0] + t * dx
        leg_len = np.linalg.norm(ankle - hip) or 1.0
        return float((knee[0] - expected_x) / leg_len)

    left_knee_dev = knee_deviation(l_hip, l_knee, l_ank)
    right_knee_dev = knee_deviation(r_hip, r_knee, r_ank)

    flags = []
    f = _posture_flag(head_tilt_deg, "head tilted right", "head tilted left")
    if f:
        flags.append(f)
    f = _posture_flag(shoulder_tilt_deg, "right shoulder lower", "left shoulder lower")
    if f:
        flags.append(f)
    f = _posture_flag(hip_tilt_deg, "right hip lower", "left hip lower")
    if f:
        flags.append(f)
    if abs(spine_lean_ratio) > 0.06:
        side = "left" if spine_lean_ratio > 0 else "right"
        flags.append(f"Slight lateral lean toward the {side}")
    if abs(balance_ratio) > 0.08:
        side = "right" if balance_ratio > 0 else "left"
        flags.append(f"Weight appears shifted toward the {side}")

    limb_alignment_notes = []
    KNEE_DEV_THRESHOLD = 0.06
    if left_knee_dev is not None and abs(left_knee_dev) > KNEE_DEV_THRESHOLD:
        limb_alignment_notes.append(
            "Left knee tracks inward"
            if left_knee_dev > 0
            else "Left knee tracks outward"
        )
    if right_knee_dev is not None and abs(right_knee_dev) > KNEE_DEV_THRESHOLD:
        limb_alignment_notes.append(
            "Right knee tracks inward"
            if right_knee_dev > 0
            else "Right knee tracks outward"
        )

    return {
        "head_tilt_deg": round(head_tilt_deg, 1),
        "shoulder_tilt_deg": round(shoulder_tilt_deg, 1),
        "hip_tilt_deg": round(hip_tilt_deg, 1),
        "neck_alignment_offset": round(neck_offset_ratio, 3),
        "spine_lean_offset": round(spine_lean_ratio, 3),
        "body_balance_offset": round(balance_ratio, 3),
        "limb_alignment_notes": limb_alignment_notes,
        "flags": flags,
        "standing_posture_summary": (
            "No notable posture deviations detected" if not flags else "; ".join(flags)
        ),
        "note": (
            "Screening only, from ONE front-on photo — this can only see "
            "left/right (coronal) misalignment. Forward-head posture and "
            "rounded shoulders need a side photo to assess and aren't "
            "covered here."
        ),
    }


# -------------------------------------------------------------------------
# Appearance: hair length / density / baldness / beard / mustache
# -------------------------------------------------------------------------
# All of this rides on the segmentation model's HAIR category — there is
# no dedicated "facial hair" class, so beard/mustache are inferred as HAIR
# pixels appearing in the lower-face region instead of the scalp region.
# This is a genuinely weak signal (a shadow, dark collar, or hair strand
# crossing the jaw can all trip it) — every field here is explicitly
# "estimated" or lower, never "measured", and confidence is always
# surfaced to the caller.


def _assess_appearance_extra(
    landmarks, frame_rgb: np.ndarray, mask: Optional[np.ndarray], w: int, h: int
) -> dict[str, Any]:
    l_eye, r_eye = _px(landmarks[LEFT_EYE], w, h), _px(landmarks[RIGHT_EYE], w, h)
    nose = _px(landmarks[NOSE], w, h)
    mouth_mid = _mid(landmarks[MOUTH_LEFT], landmarks[MOUTH_RIGHT], w, h)
    l_sh, r_sh = _px(landmarks[LEFT_SHOULDER], w, h), _px(
        landmarks[RIGHT_SHOULDER], w, h
    )
    shoulder_mid = (l_sh + r_sh) / 2
    eye_mid = (l_eye + r_eye) / 2
    eye_span = np.linalg.norm(l_eye - r_eye) or 1.0
    face_scale = (
        np.linalg.norm(shoulder_mid - eye_mid) or 1.0
    )  # eye-line to shoulder-line

    if mask is None:
        return {
            "hair_length_label": None,
            "hair_density_label": None,
            "baldness_detected": None,
            "beard_detected": None,
            "beard_style": None,
            "mustache_detected": None,
            "confidence": "unavailable",
            "note": "Segmentation model not installed — see engines/segmentEngine.py.",
        }

    # --- Crown / scalp region: a band above the eye-line, roughly where a
    # visible hairline or crown baldness would show up.
    crown_center = np.array([eye_mid[0], max(0.0, eye_mid[1] - face_scale * 0.55)])
    crown_hair_frac = _region_hair_fraction(
        mask, crown_center, eye_span * 0.9, face_scale * 0.35
    )

    # --- "Does hair extend past the shoulder line" — a coarse hair-length
    # proxy: sample a band at shoulder height, just outside each shoulder,
    # and check for hair pixels there.
    past_shoulder_l = _region_hair_fraction(
        mask,
        np.array([l_sh[0] - eye_span * 0.3, l_sh[1]]),
        eye_span * 0.35,
        face_scale * 0.15,
    )
    past_shoulder_r = _region_hair_fraction(
        mask,
        np.array([r_sh[0] + eye_span * 0.3, r_sh[1]]),
        eye_span * 0.35,
        face_scale * 0.15,
    )
    past_shoulder = max(
        [v for v in (past_shoulder_l, past_shoulder_r) if v is not None], default=None
    )

    # --- Jaw/chin band (beard) and philtrum strip (mustache).
    jaw_center = np.array([mouth_mid[0], mouth_mid[1] + face_scale * 0.35])
    beard_frac = _region_hair_fraction(
        mask, jaw_center, eye_span * 0.8, face_scale * 0.3
    )
    mustache_center = np.array([mouth_mid[0], mouth_mid[1] - face_scale * 0.12])
    mustache_frac = _region_hair_fraction(
        mask, mustache_center, eye_span * 0.45, face_scale * 0.12
    )

    hair_density_label = None
    baldness_detected = None
    if crown_hair_frac is not None:
        if crown_hair_frac < 0.15:
            hair_density_label, baldness_detected = "Very thin / balding crown", True
        elif crown_hair_frac < 0.40:
            hair_density_label, baldness_detected = "Thinning", False
        elif crown_hair_frac < 0.75:
            hair_density_label, baldness_detected = "Medium density", False
        else:
            hair_density_label, baldness_detected = "Dense / full", False

    hair_length_label = None
    if past_shoulder is not None:
        hair_length_label = "Long (past shoulders)" if past_shoulder > 0.35 else None
    if (
        hair_length_label is None
        and crown_hair_frac is not None
        and crown_hair_frac > 0.15
    ):
        # Has visible hair but it didn't clear the shoulder-line check —
        # can't tell short vs medium apart without a jaw-line hair-edge
        # detector, so this stays a coarser two-way call.
        hair_length_label = "Short-to-medium (at or above shoulders)"
    elif hair_length_label is None:
        hair_length_label = "Very short / not detected"

    BEARD_THRESHOLD = 0.30
    MUSTACHE_THRESHOLD = 0.30
    beard_detected = beard_frac is not None and beard_frac > BEARD_THRESHOLD
    mustache_detected = mustache_frac is not None and mustache_frac > MUSTACHE_THRESHOLD

    beard_style = None
    if beard_detected:
        beard_style = (
            "Full beard" if (mustache_detected) else "Chin beard / goatee-leaning"
        )
        if beard_frac is not None and beard_frac > 0.6:
            beard_style = "Full, dense beard"

    return {
        "hair_length_label": hair_length_label,
        "hair_density_label": hair_density_label,
        "baldness_detected": baldness_detected,
        "beard_detected": beard_detected,
        "beard_style": beard_style,
        "mustache_detected": mustache_detected,
        "confidence": "estimated",
        "note": (
            "Inferred from the segmentation model's HAIR pixel class in "
            "the scalp/jaw/lip regions — there's no dedicated facial-hair "
            "model, so this is a coarse visual estimate, not a precise read."
        ),
    }


# -------------------------------------------------------------------------
# Head size (pose-only rough estimate — see face_analysis.py for the
# precise version once the Face Landmarker model is installed)
# -------------------------------------------------------------------------


def _estimate_head_size_cm(
    landmarks, w: int, h: int, px_per_cm: float
) -> dict[str, Any]:
    l_eye_o = _px(landmarks[LEFT_EYE_OUTER], w, h)
    r_eye_o = _px(landmarks[RIGHT_EYE_OUTER], w, h)
    mouth_mid = _mid(landmarks[MOUTH_LEFT], landmarks[MOUTH_RIGHT], w, h)
    eye_mid = (l_eye_o + r_eye_o) / 2

    eye_span_px = np.linalg.norm(l_eye_o - r_eye_o)
    eye_to_mouth_px = np.linalg.norm(mouth_mid - eye_mid)

    width_cm = (eye_span_px * HEAD_WIDTH_TO_EYE_SPAN_RATIO) / px_per_cm
    height_cm = (eye_to_mouth_px * HEAD_HEIGHT_TO_EYE_MOUTH_RATIO) / px_per_cm

    return {
        "head_width_cm": round(float(width_cm), 1),
        "head_height_cm": round(float(height_cm), 1),
        "confidence": "approximate",
        "note": (
            "Rough — derived from average facial proportions, not a "
            "dedicated head model. Install the Face Landmarker model "
            "(see face_analysis.py) for a measured head/face bounding box."
        ),
    }


# -------------------------------------------------------------------------
# Public entry point
# -------------------------------------------------------------------------


def analyze_body(
    landmarks,
    frame_bgr: np.ndarray,
    height_cm: float,
    mask: Optional[np.ndarray],
    face_result: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    landmarks   : 33-point list from PoseEngine.detect()
    frame_bgr   : the captured frame, as read by cv2 (BGR order)
    height_cm   : user-entered height — the ONLY calibration input
    mask        : category mask from SegmentEngine.segment(), or None if
                  the segmentation model isn't installed
    face_result : optional dict from face_analysis.analyze_face() — when
                  provided, its face-oval bounding box replaces the rough
                  pose-only head-size estimate with a measured one, and
                  its fields are merged into `face` in the response.
    """
    if not (100 <= height_cm <= 250):
        raise BodyScanError("Height looks out of range — expected 100-250 cm.")

    check_full_body_visible(landmarks)

    h, w = frame_bgr.shape[:2]
    frame_rgb = frame_bgr[:, :, ::-1]

    px_per_cm = _compute_px_per_cm(landmarks, w, h, height_cm)

    shoulder_mid = _mid(landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER], w, h)
    hip_mid = _mid(landmarks[LEFT_HIP], landmarks[RIGHT_HIP], w, h)
    ankle_mid = _mid(landmarks[LEFT_ANKLE], landmarks[RIGHT_ANKLE], w, h)
    ear_mid = _mid(landmarks[LEFT_EAR], landmarks[RIGHT_EAR], w, h)

    shoulder_width_cm = _landmark_width_cm(
        landmarks[LEFT_SHOULDER], landmarks[RIGHT_SHOULDER], w, h, px_per_cm
    )
    hip_width_cm = _landmark_width_cm(
        landmarks[LEFT_HIP], landmarks[RIGHT_HIP], w, h, px_per_cm
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

    torso_length_cm = float(np.linalg.norm(hip_mid - shoulder_mid) / px_per_cm)
    neck_length_cm = float(np.linalg.norm(ear_mid - shoulder_mid) / px_per_cm)

    # Inseam: straight hip-midpoint-to-ankle-midpoint distance (the direct
    # "crotch to floor" line), distinct from `leg_length_cm` which follows
    # the bent hip->knee->ankle chain — a real inseam is usually a touch
    # shorter than the chain length for this reason.
    inseam_cm = float(np.linalg.norm(ankle_mid - hip_mid) / px_per_cm)

    # Sleeve length: garment measurement runs collar -> shoulder seam ->
    # elbow -> wrist. We approximate "collar to shoulder seam" as half the
    # neck length, since there's no dedicated collar landmark.
    sleeve_length_cm = neck_length_cm * 0.5 + arm_length_cm

    waist_row_y = shoulder_mid[1] + WAIST_FRACTION * (hip_mid[1] - shoulder_mid[1])
    waist_center_x = shoulder_mid[0] + WAIST_FRACTION * (hip_mid[0] - shoulder_mid[0])

    waist_width_cm: Optional[float] = None
    waist_confidence = "estimated"
    warnings: list[str] = []

    if mask is not None:
        left_bound, right_bound = _arm_clamp_px(
            landmarks, w, h, waist_row_y, waist_center_x
        )
        reading = _silhouette_width_cm(
            mask,
            waist_center_x,
            waist_row_y,
            px_per_cm,
            left_bound_px=left_bound,
            right_bound_px=right_bound,
            band_px=3,
        )
        waist_width_cm = reading.width_cm
        if waist_width_cm is not None:
            waist_confidence = (
                "measured_low_confidence" if reading.arm_contact else "measured"
            )
            if reading.arm_contact:
                warnings.append(
                    "Arms appear to be resting against your torso in this photo — "
                    "waist/chest width may still run a bit wide. For the most "
                    "accurate reading, retake with arms held slightly away from "
                    "your sides."
                )

    if waist_width_cm is None:
        waist_width_cm = shoulder_width_cm + WAIST_FRACTION * (
            hip_width_cm - shoulder_width_cm
        )
        waist_confidence = "estimated"

    waist_to_height = waist_width_cm / height_cm
    shoulder_to_waist = shoulder_width_cm / waist_width_cm if waist_width_cm else 0.0
    waist_to_hip = waist_width_cm / hip_width_cm if hip_width_cm else 0.0
    leg_to_torso = leg_length_cm / torso_length_cm if torso_length_cm else 0.0
    arm_to_height = arm_length_cm / height_cm
    build_estimate = _classify_build(waist_to_height, shoulder_to_waist)
    proportion_summary = _classify_leg_torso_ratio(leg_to_torso)

    # --- Limb symmetry (left vs right) --------------------------------
    arm_l = seg["upper_arm_l"] + seg["forearm_l"]
    arm_r = seg["upper_arm_r"] + seg["forearm_r"]
    leg_l = seg["thigh_l"] + seg["lower_leg_l"]
    leg_r = seg["thigh_r"] + seg["lower_leg_r"]
    arm_symmetry_pct = _pct_match(arm_l, arm_r)
    leg_symmetry_pct = _pct_match(leg_l, leg_r)
    overall_symmetry_pct = (arm_symmetry_pct + leg_symmetry_pct) / 2

    # --- Posture screening ---------------------------------------------
    posture = _assess_posture(landmarks, w, h)

    # --- Head size: prefer the Face Landmarker's measured bounding box
    # when available, otherwise fall back to the pose-only approximation.
    if face_result is not None and face_result.get("head_size") is not None:
        head_size = face_result["head_size"]
    else:
        head_size = _estimate_head_size_cm(landmarks, w, h, px_per_cm)

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
        eye_mid = _mid(landmarks[LEFT_EYE], landmarks[RIGHT_EYE], w, h)
        head_span = np.linalg.norm(shoulder_mid - eye_mid) * 0.6
        hair_point = np.array([eye_mid[0], max(0.0, eye_mid[1] - head_span)])
        hair_rgb = _sample_patch_color(frame_rgb, hair_point)

    appearance_extra = _assess_appearance_extra(landmarks, frame_rgb, mask, w, h)

    result: dict[str, Any] = {
        "height_cm": round(height_cm, 1),
        "warnings": warnings,
        "measurements": {
            "shoulder_width_cm": round(shoulder_width_cm, 1),
            "hip_width_cm": round(hip_width_cm, 1),
            "waist_width_cm": round(waist_width_cm, 1),
            "waist_confidence": waist_confidence,
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
                "Compares left vs right limb length in THIS photo — pose, "
                "camera angle, and clothing all affect this reading as "
                "much as real anatomy does."
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
            "Estimated from a single photo — approximate, not a medical, "
            "clinical, or tailoring-grade measurement. Posture and "
            "symmetry readings are screening signals only. None of this "
            "replaces an actual health checkup or professional fitting. "
            "You can edit any field manually."
        ),
    }

    if face_result is not None:
        result["face"] = {k: v for k, v in face_result.items() if k != "head_size"}

    return result
