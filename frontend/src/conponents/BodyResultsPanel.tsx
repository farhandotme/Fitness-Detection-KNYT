import type { BodyAnalysisResult } from "../pages/BodyAnalysisPage";

interface Props {
  result: BodyAnalysisResult;
  onRescan: () => void;
}

function ConfidenceTag({ level }: { level: string }) {
  return <span className={`confidence-tag confidence-${level}`}>{level}</span>;
}

export default function BodyResultsPanel({ result, onRescan }: Props) {
  const { measurements, body_composition, appearance } = result;

  return (
    <div className="scan-results">
      <div className="scan-results-header">
        <h3>Your Body Scan</h3>
        <button className="btn-ghost" onClick={onRescan}>
          Rescan
        </button>
      </div>

      <div className="scan-results-grid">
        <div className="scan-result-card">
          <span className="scan-result-label">Height</span>
          <span className="scan-result-value">{result.height_cm} cm</span>
        </div>

        <div className="scan-result-card">
          <span className="scan-result-label">
            Shoulder width <ConfidenceTag level="measured" />
          </span>
          <span className="scan-result-value">{measurements.shoulder_width_cm} cm</span>
        </div>

        <div className="scan-result-card">
          <span className="scan-result-label">
            Hip width <ConfidenceTag level="measured" />
          </span>
          <span className="scan-result-value">{measurements.hip_width_cm} cm</span>
        </div>

        <div className="scan-result-card">
          <span className="scan-result-label">
            Waist width <ConfidenceTag level={measurements.waist_confidence} />
          </span>
          <span className="scan-result-value">{measurements.waist_width_cm} cm</span>
        </div>

        <div className="scan-result-card">
          <span className="scan-result-label">
            Arm length <ConfidenceTag level="measured" />
          </span>
          <span className="scan-result-value">{measurements.arm_length_cm} cm</span>
        </div>

        <div className="scan-result-card">
          <span className="scan-result-label">
            Leg length <ConfidenceTag level="measured" />
          </span>
          <span className="scan-result-value">{measurements.leg_length_cm} cm</span>
        </div>

        <div className="scan-result-card">
          <span className="scan-result-label">
            Torso length <ConfidenceTag level="measured" />
          </span>
          <span className="scan-result-value">{measurements.torso_length_cm} cm</span>
        </div>

        {result.bmi !== null && (
          <div className="scan-result-card">
            <span className="scan-result-label">BMI</span>
            <span className="scan-result-value">{result.bmi}</span>
            <span className="scan-result-sub">{result.bmi_category}</span>
          </div>
        )}

        <div className="scan-result-card scan-result-card-wide">
          <span className="scan-result-label">Build estimate</span>
          <span className="scan-result-value">{body_composition.build_estimate}</span>
          <span className="scan-result-sub">
            waist-to-height {body_composition.waist_to_height_ratio} · shoulder-to-waist{" "}
            {body_composition.shoulder_to_waist_ratio}
          </span>
        </div>

        <div className="scan-result-card">
          <span className="scan-result-label">
            Skin tone <ConfidenceTag level={appearance.skin_tone_confidence} />
          </span>
          <div className="scan-swatch-row">
            <span className="scan-swatch" style={{ background: appearance.skin_tone_hex }} />
            <span className="scan-result-value">{appearance.skin_tone_label}</span>
          </div>
        </div>

        <div className="scan-result-card">
          <span className="scan-result-label">
            Hair color <ConfidenceTag level={appearance.hair_color_confidence} />
          </span>
          <div className="scan-swatch-row">
            <span className="scan-swatch" style={{ background: appearance.hair_color_hex }} />
            <span className="scan-result-value">{appearance.hair_color_label}</span>
          </div>
        </div>
      </div>

      <p className="scan-disclaimer">{result.disclaimer}</p>
    </div>
  );
}
