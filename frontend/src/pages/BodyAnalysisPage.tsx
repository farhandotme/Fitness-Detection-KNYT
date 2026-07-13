import { useState } from "react";
import BodyScanCamera from "../conponents/BodyScanCamera";
import BodyResultsPanel from "../conponents/BodyResultsPanel";
import "./BodyAnalysisPage.css";

export interface BodyAnalysisResult {
  height_cm: number;
  views_used: string[];
  warnings: string[];
  measurements: {
    shoulder_width_cm: number;
    hip_width_cm: number;
    neck_length_cm: number;
    torso_length_cm: number;
    upper_arm_length_cm: number;
    forearm_length_cm: number;
    arm_length_cm: number;
    sleeve_length_cm: number;
    thigh_length_cm: number;
    lower_leg_length_cm: number;
    leg_length_cm: number;
    inseam_cm: number;
    head_width_cm: number;
    head_height_cm: number;
    head_size_confidence: "measured" | "estimated" | "approximate";
  };
  circumference: {
    chest_cm: number;
    waist_cm: number;
    hip_cm: number;
    confidence: "measured" | "estimated";
  };
  body_proportions: {
    shoulder_to_waist_ratio: number;
    waist_to_hip_ratio: number;
    waist_to_height_ratio: number;
    leg_to_torso_ratio: number;
    arm_to_height_ratio: number;
    build_estimate: string;
    proportion_summary: string;
  };
  symmetry: {
    arm_symmetry_pct: number;
    leg_symmetry_pct: number;
    overall_symmetry_pct: number;
    label: string;
    note: string;
  };
  posture: {
    head_tilt_deg: number;
    shoulder_tilt_deg: number;
    hip_tilt_deg: number;
    neck_alignment_offset: number;
    spine_lean_offset: number;
    body_balance_offset: number;
    limb_alignment_notes: string[];
    flags: string[];
    standing_posture_summary: string;
    note: string;
  };
  appearance: {
    skin_tone_hex: string;
    skin_tone_label: string;
    skin_tone_confidence: "measured" | "estimated";
    hair_color_hex: string;
    hair_color_label: string;
    hair_color_confidence: "measured" | "estimated";
    hair_length_label: string | null;
    hair_density_label: string | null;
    baldness_detected: boolean | null;
    beard_detected: boolean | null;
    beard_style: string | null;
    mustache_detected: boolean | null;
    confidence: "estimated" | "unavailable";
    note: string;
  };
  face?: {
    available: boolean;
    face_shape: string;
    face_symmetry_pct: number;
    face_symmetry_label: string;
    smile_detected: boolean | null;
    smile_intensity: number | null;
    left_eye_openness: number | null;
    right_eye_openness: number | null;
    eye_openness_label: string | null;
    eye_color_hex: string;
    eye_color_label: string;
    landmark_count: number;
    confidence: string;
    note: string;
  };
  disclaimer: string;
  segmentation_available: boolean;
  face_analysis_available: boolean;
}

type Phase =
  | "height-input"
  | "camera"
  | "scanning"
  | "processing"
  | "results"
  | "error";

interface ViewStep {
  key: "front" | "left" | "right" | "back";
  label: string;
  instruction: string;
  required: boolean;
}

const VIEW_STEPS: ViewStep[] = [
  {
    key: "front",
    label: "Front",
    instruction: "Face the camera directly",
    required: true,
  },
  {
    key: "left",
    label: "Left side",
    instruction: "Turn so your left side faces the camera",
    required: false,
  },
  {
    key: "right",
    label: "Right side",
    instruction: "Turn so your right side faces the camera",
    required: false,
  },
  {
    key: "back",
    label: "Back",
    instruction: "Turn around, back to the camera",
    required: false,
  },
];

const API_BASE =
  import.meta.env.VITE_API_BASE_URL ??
  (import.meta.env.VITE_WEBSOCKET_FASTAPI_URL as string | undefined)?.replace(
    /^ws/,
    "http",
  ) ??
  "http://localhost:8000";

export default function BodyAnalysisPage() {
  const [phase, setPhase] = useState<Phase>("height-input");
  const [heightCm, setHeightCm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BodyAnalysisResult | null>(null);

  const [stepIndex, setStepIndex] = useState(0);
  const [captures, setCaptures] = useState<Record<string, string>>({});

  const currentStep = VIEW_STEPS[stepIndex];

  function startScan() {
    const h = parseFloat(heightCm);
    if (!h || h < 100 || h > 250) {
      setError("Enter a height between 100 and 250 cm.");
      return;
    }
    setError(null);
    setCaptures({});
    setStepIndex(0);
    setPhase("camera");
    window.setTimeout(() => setPhase("scanning"), 600);
  }

  function handleCapture(dataUrl: string) {
    const nextCaptures = { ...captures, [currentStep.key]: dataUrl };
    setCaptures(nextCaptures);

    if (stepIndex < VIEW_STEPS.length - 1) {
      setStepIndex(stepIndex + 1);
      setPhase("camera");
      window.setTimeout(() => setPhase("scanning"), 900);
    } else {
      submitScan(nextCaptures);
    }
  }

  function skipStep() {
    if (currentStep.required) return;
    if (stepIndex < VIEW_STEPS.length - 1) {
      setStepIndex(stepIndex + 1);
      setPhase("camera");
      window.setTimeout(() => setPhase("scanning"), 300);
    } else {
      submitScan(captures);
    }
  }

  async function submitScan(shots: Record<string, string>) {
    setPhase("processing");
    try {
      const response = await fetch(`${API_BASE}/api/body-analysis`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          front: shots.front,
          left: shots.left ?? null,
          right: shots.right ?? null,
          back: shots.back ?? null,
          height_cm: parseFloat(heightCm),
        }),
      });

      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? "Scan failed — try again.");
      }

      const data: BodyAnalysisResult = await response.json();
      setResult(data);
      setPhase("results");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scan failed — try again.");
      setPhase("error");
    }
  }

  function handleCameraError(message: string) {
    setError(message);
    setPhase("error");
  }

  function retry() {
    setError(null);
    setResult(null);
    setCaptures({});
    setStepIndex(0);
    setPhase("camera");
    window.setTimeout(() => setPhase("scanning"), 600);
  }

  return (
    <div className="body-analysis-page">
      <div className="body-analysis-header">
        <h2 className="body-analysis-title">Full Body Analysis</h2>
        <p className="body-analysis-subtitle">
          Four quick photos — front, left, right, back — give us real depth
          measurements, not just a flat guess. Only the front photo is required;
          side/back photos can be skipped but improve accuracy. Height is the
          only number you type — a camera can't measure weight, so that's not
          part of this scan.
        </p>
      </div>

      {phase === "height-input" && (
        <div className="scan-height-card">
          <label className="scan-height-label" htmlFor="height-input">
            Your height (cm)
          </label>
          <input
            id="height-input"
            type="number"
            inputMode="decimal"
            placeholder="e.g. 175"
            value={heightCm}
            onChange={(e) => setHeightCm(e.target.value)}
            className="scan-height-input"
          />
          <p className="scan-height-hint">
            This is the ONLY number we need — it's the reference point every
            other measurement below is calculated from. A camera alone can't
            tell absolute size (or weight), so we don't ask for anything else.
          </p>

          {error && <p className="scan-error">{error}</p>}
          <button className="btn-primary" onClick={startScan}>
            Start Scan
          </button>
        </div>
      )}

      {(phase === "camera" ||
        phase === "scanning" ||
        phase === "processing") && (
        <div className="scan-camera-wrap">
          <div className="scan-progress">
            {VIEW_STEPS.map((step, i) => (
              <span
                key={step.key}
                className={`scan-progress-dot ${i < stepIndex ? "done" : ""} ${
                  i === stepIndex ? "active" : ""
                }`}
              >
                {step.label}
              </span>
            ))}
          </div>

          <BodyScanCamera
            active
            scanning={phase === "scanning"}
            countdownSeconds={5}
            onCapture={handleCapture}
            onError={handleCameraError}
          />

          <p className="scan-status">
            {phase === "camera" && `Getting ready — ${currentStep.instruction}`}
            {phase === "scanning" && currentStep.instruction}
            {phase === "processing" && "Analyzing your scan…"}
          </p>

          {phase === "scanning" && !currentStep.required && (
            <button className="btn-ghost" onClick={skipStep}>
              Skip this angle
            </button>
          )}
        </div>
      )}

      {phase === "error" && (
        <div className="scan-height-card">
          <p className="scan-error">{error}</p>
          <button className="btn-primary" onClick={retry}>
            Try Again
          </button>
        </div>
      )}

      {phase === "results" && result && (
        <BodyResultsPanel result={result} onRescan={retry} />
      )}
    </div>
  );
}
