import type { BodyAnalysisResult } from "../pages/BodyAnalysisPage";

interface Props {
  result: BodyAnalysisResult;
  onRescan: () => void;
}

function ConfidenceTag({ level }: { level: string }) {
  return <span className={`confidence-tag confidence-${level}`}>{level}</span>;
}

function BoolTag({ value }: { value: boolean | null }) {
  if (value === null) return <span className="scan-result-sub">—</span>;
  return (
    <span
      className={`confidence-tag ${value ? "confidence-measured" : "confidence-estimated"}`}
    >
      {value ? "Yes" : "No"}
    </span>
  );
}

export default function BodyResultsPanel({ result, onRescan }: Props) {
  const {
    measurements,
    circumference,
    body_proportions,
    symmetry,
    posture,
    appearance,
    face,
  } = result;

  return (
    <div className="scan-results">
      <div className="scan-results-header">
        <h3>Your Body Scan</h3>
        <button className="btn-ghost" onClick={onRescan}>
          Rescan
        </button>
      </div>

      <p className="scan-views-used">
        Based on: {result.views_used.join(", ")}
        {result.views_used.length < 4 && " (more angles = better accuracy)"}
        {!result.segmentation_available &&
          " · segmentation model not installed — some readings are rougher estimates"}
        {!result.face_analysis_available &&
          " · face model not installed — face section skipped"}
      </p>

      {result.warnings.length > 0 && (
        <ul className="scan-warnings">
          {result.warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}

      {/* --- Core size ------------------------------------------------ */}
      <h4 className="scan-section-title">Measurements</h4>
      <div className="scan-results-grid">
        <div className="scan-result-card">
          <span className="scan-result-label">Height</span>
          <span className="scan-result-value">{result.height_cm} cm</span>
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">Shoulder width</span>
          <span className="scan-result-value">
            {measurements.shoulder_width_cm} cm
          </span>
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">Hip width</span>
          <span className="scan-result-value">
            {measurements.hip_width_cm} cm
          </span>
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">Neck length</span>
          <span className="scan-result-value">
            {measurements.neck_length_cm} cm
          </span>
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">Torso length</span>
          <span className="scan-result-value">
            {measurements.torso_length_cm} cm
          </span>
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">Upper arm</span>
          <span className="scan-result-value">
            {measurements.upper_arm_length_cm} cm
          </span>
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">Forearm</span>
          <span className="scan-result-value">
            {measurements.forearm_length_cm} cm
          </span>
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">Full arm length</span>
          <span className="scan-result-value">
            {measurements.arm_length_cm} cm
          </span>
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">Sleeve length</span>
          <span className="scan-result-value">
            {measurements.sleeve_length_cm} cm
          </span>
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">Thigh length</span>
          <span className="scan-result-value">
            {measurements.thigh_length_cm} cm
          </span>
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">Lower leg length</span>
          <span className="scan-result-value">
            {measurements.lower_leg_length_cm} cm
          </span>
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">Full leg length</span>
          <span className="scan-result-value">
            {measurements.leg_length_cm} cm
          </span>
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">Inseam</span>
          <span className="scan-result-value">{measurements.inseam_cm} cm</span>
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">
            Head size{" "}
            <ConfidenceTag level={measurements.head_size_confidence} />
          </span>
          <span className="scan-result-value">
            {measurements.head_width_cm} × {measurements.head_height_cm} cm
          </span>
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">
            Chest circumference{" "}
            <ConfidenceTag level={circumference.confidence} />
          </span>
          <span className="scan-result-value">{circumference.chest_cm} cm</span>
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">
            Waist circumference{" "}
            <ConfidenceTag level={circumference.confidence} />
          </span>
          <span className="scan-result-value">{circumference.waist_cm} cm</span>
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">
            Hip circumference <ConfidenceTag level={circumference.confidence} />
          </span>
          <span className="scan-result-value">{circumference.hip_cm} cm</span>
        </div>
      </div>

      {/* --- Proportions & symmetry ------------------------------------ */}
      <h4 className="scan-section-title">Proportions &amp; Symmetry</h4>
      <div className="scan-results-grid">
        <div className="scan-result-card scan-result-card-wide">
          <span className="scan-result-label">Build estimate</span>
          <span className="scan-result-value">
            {body_proportions.build_estimate}
          </span>
          <span className="scan-result-sub">
            {body_proportions.proportion_summary}
          </span>
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">Shoulder-to-waist</span>
          <span className="scan-result-value">
            {body_proportions.shoulder_to_waist_ratio}
          </span>
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">Waist-to-hip</span>
          <span className="scan-result-value">
            {body_proportions.waist_to_hip_ratio}
          </span>
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">Leg-to-torso</span>
          <span className="scan-result-value">
            {body_proportions.leg_to_torso_ratio}
          </span>
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">Arm-to-height</span>
          <span className="scan-result-value">
            {body_proportions.arm_to_height_ratio}
          </span>
        </div>
        <div className="scan-result-card scan-result-card-wide">
          <span className="scan-result-label">Limb symmetry</span>
          <span className="scan-result-value">
            {symmetry.overall_symmetry_pct}%
          </span>
          <span className="scan-result-sub">
            {symmetry.label} · arms {symmetry.arm_symmetry_pct}% · legs{" "}
            {symmetry.leg_symmetry_pct}%
          </span>
        </div>
      </div>

      {/* --- Posture ----------------------------------------------------- */}
      <h4 className="scan-section-title">Posture Screening</h4>
      <div className="scan-results-grid">
        <div className="scan-result-card scan-result-card-wide">
          <span className="scan-result-label">Standing posture</span>
          <span className="scan-result-value">
            {posture.standing_posture_summary}
          </span>
          {posture.limb_alignment_notes.length > 0 && (
            <span className="scan-result-sub">
              {posture.limb_alignment_notes.join("; ")}
            </span>
          )}
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">Head tilt</span>
          <span className="scan-result-value">{posture.head_tilt_deg}°</span>
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">Shoulder tilt</span>
          <span className="scan-result-value">
            {posture.shoulder_tilt_deg}°
          </span>
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">Hip tilt</span>
          <span className="scan-result-value">{posture.hip_tilt_deg}°</span>
        </div>
      </div>
      <p className="scan-disclaimer scan-disclaimer-inline">{posture.note}</p>

      {/* --- Appearance --------------------------------------------------- */}
      <h4 className="scan-section-title">Appearance</h4>
      <div className="scan-results-grid">
        <div className="scan-result-card">
          <span className="scan-result-label">
            Skin tone <ConfidenceTag level={appearance.skin_tone_confidence} />
          </span>
          <div className="scan-swatch-row">
            <span
              className="scan-swatch"
              style={{ background: appearance.skin_tone_hex }}
            />
            <span className="scan-result-value">
              {appearance.skin_tone_label}
            </span>
          </div>
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">
            Hair color{" "}
            <ConfidenceTag level={appearance.hair_color_confidence} />
          </span>
          <div className="scan-swatch-row">
            <span
              className="scan-swatch"
              style={{ background: appearance.hair_color_hex }}
            />
            <span className="scan-result-value">
              {appearance.hair_color_label}
            </span>
          </div>
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">Hair length</span>
          <span className="scan-result-value">
            {appearance.hair_length_label ?? "—"}
          </span>
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">Hair density</span>
          <span className="scan-result-value">
            {appearance.hair_density_label ?? "—"}
          </span>
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">Baldness</span>
          <BoolTag value={appearance.baldness_detected} />
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">Beard</span>
          <BoolTag value={appearance.beard_detected} />
          {appearance.beard_style && (
            <span className="scan-result-sub">{appearance.beard_style}</span>
          )}
        </div>
        <div className="scan-result-card">
          <span className="scan-result-label">Mustache</span>
          <BoolTag value={appearance.mustache_detected} />
        </div>

        {face?.available && (
          <>
            <div className="scan-result-card">
              <span className="scan-result-label">Face shape</span>
              <span className="scan-result-value">{face.face_shape}</span>
            </div>
            <div className="scan-result-card">
              <span className="scan-result-label">Face symmetry</span>
              <span className="scan-result-value">
                {face.face_symmetry_pct}%
              </span>
              <span className="scan-result-sub">
                {face.face_symmetry_label}
              </span>
            </div>
            <div className="scan-result-card">
              <span className="scan-result-label">
                Eye color <ConfidenceTag level="estimated" />
              </span>
              <div className="scan-swatch-row">
                <span
                  className="scan-swatch"
                  style={{ background: face.eye_color_hex }}
                />
                <span className="scan-result-value">
                  {face.eye_color_label}
                </span>
              </div>
            </div>
            <div className="scan-result-card">
              <span className="scan-result-label">Eye openness</span>
              <span className="scan-result-value">
                {face.eye_openness_label ?? "—"}
              </span>
            </div>
            <div className="scan-result-card">
              <span className="scan-result-label">Smile</span>
              <BoolTag value={face.smile_detected} />
              {face.smile_intensity !== null && (
                <span className="scan-result-sub">
                  intensity {face.smile_intensity}
                </span>
              )}
            </div>
            <div className="scan-result-card">
              <span className="scan-result-label">Facial landmarks</span>
              <span className="scan-result-value">
                {face.landmark_count} points
              </span>
            </div>
          </>
        )}
      </div>
      <p className="scan-disclaimer scan-disclaimer-inline">
        {appearance.note}
      </p>
      {face?.available && (
        <p className="scan-disclaimer scan-disclaimer-inline">{face.note}</p>
      )}
      {!result.face_analysis_available && (
        <p className="scan-disclaimer scan-disclaimer-inline">
          Face shape, face symmetry, smile, eye openness, and eye color need the
          Face Landmarker model installed on the backend (see
          detection-backend/src/engines/face_analysis.py for the one-time
          download command).
        </p>
      )}

      <p className="scan-disclaimer">{result.disclaimer}</p>
    </div>
  );
}
