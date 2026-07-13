import { useState } from "react";
import BodyScanCamera from "../conponents/BodyScanCamera";
import BodyResultsPanel from "../conponents/BodyResultsPanel";
import "./BodyAnalysisPage.css";

export interface BodyAnalysisResult {
  height_cm: number;
  weight_kg: number | null;
  bmi: number | null;
  bmi_category: string | null;
  measurements: {
    shoulder_width_cm: number;
    hip_width_cm: number;
    waist_width_cm: number;
    waist_confidence: "measured" | "estimated";
    arm_length_cm: number;
    leg_length_cm: number;
    torso_length_cm: number;
  };
  body_composition: {
    waist_to_height_ratio: number;
    shoulder_to_waist_ratio: number;
    build_estimate: string;
  };
  appearance: {
    skin_tone_hex: string;
    skin_tone_label: string;
    skin_tone_confidence: "measured" | "estimated";
    hair_color_hex: string;
    hair_color_label: string;
    hair_color_confidence: "measured" | "estimated";
  };
  disclaimer: string;
  segmentation_available: boolean;
}

type Phase =
  | "height-input"
  | "camera"
  | "scanning"
  | "processing"
  | "results"
  | "error";

// Falls back to deriving an HTTP url from the websocket url env var that
// the other pages already use, so this works without extra .env setup.
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
  const [weightKg, setWeightKg] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BodyAnalysisResult | null>(null);

  function startScan() {
    const h = parseFloat(heightCm);
    if (!h || h < 100 || h > 250) {
      setError("Enter a height between 100 and 250 cm.");
      return;
    }
    setError(null);
    setPhase("camera");
    // Small delay so the camera stream has a moment to start before the
    // countdown begins — avoids counting down over a black frame.
    window.setTimeout(() => setPhase("scanning"), 600);
  }

  async function handleCapture(dataUrl: string) {
    setPhase("processing");
    try {
      const response = await fetch(`${API_BASE}/api/body-analysis`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          image: dataUrl,
          height_cm: parseFloat(heightCm),
          weight_kg: weightKg ? parseFloat(weightKg) : null,
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
    setPhase("camera");
    window.setTimeout(() => setPhase("scanning"), 600);
  }

  return (
    <div className="body-analysis-page">
      <div className="body-analysis-header">
        <h2 className="body-analysis-title">Full Body Analysis</h2>
        <p className="body-analysis-subtitle">
          Stand back so your whole body is visible. A 5-second countdown starts
          when you hit "Start Scan," then it captures automatically.
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
            We use this as the reference point to calculate every other
            measurement — a camera alone can't tell absolute size.
          </p>

          <label className="scan-height-label" htmlFor="weight-input">
            Your weight (kg) — optional, adds BMI
          </label>
          <input
            id="weight-input"
            type="number"
            inputMode="decimal"
            placeholder="e.g. 70"
            value={weightKg}
            onChange={(e) => setWeightKg(e.target.value)}
            className="scan-height-input"
          />

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
          <BodyScanCamera
            active
            scanning={phase === "scanning"}
            countdownSeconds={5}
            onCapture={handleCapture}
            onError={handleCameraError}
          />
          <p className="scan-status">
            {phase === "camera" && "Getting the camera ready…"}
            {phase === "scanning" &&
              "Stand fully in frame — capturing in a moment"}
            {phase === "processing" && "Analyzing your scan…"}
          </p>
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
