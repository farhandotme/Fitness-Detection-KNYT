import type { ButtKicksData } from "../hooks/useButtKicksSocket";

interface Props {
  data: ButtKicksData | undefined;
}

const STAGE_LABEL: Record<string, string> = {
  neutral: "GET READY",
  ready: "ALTERNATING",
  left_kick: "LEFT KICK",
  right_kick: "RIGHT KICK",
  both_kick: "KICKING",
};

export default function ButtKicksStatsPanel({ data }: Props) {
  const quality = data?.rep_form_quality;
  const stage = data?.stage ?? "neutral";
  const confidencePct = Math.round((data?.motion_confidence ?? 0) * 100);
  const peakPct = Math.round((data?.kick_peak_score ?? 0) * 100);

  return (
    <div className="bk-panel">
      <div className="bk-panel-head">
        <span className="bk-panel-label">BUTT KICKS</span>
        <span
          className={`bk-pose-pill ${data?.pose_detected ? (data.low_visibility ? "warn" : "ok") : "bad"}`}
        >
          {data?.pose_detected
            ? data.low_visibility
              ? "Unstable"
              : "Tracking"
            : "No pose"}
        </span>
      </div>

      <div className="bk-rep-row">
        <span className="bk-rep-count">{data?.rep_count ?? 0}</span>
        <span className={`bk-stage-badge bk-stage-${stage}`}>
          {STAGE_LABEL[stage] ?? "GET READY"}
        </span>
      </div>

      <div className="bk-split-row">
        <div
          className={`bk-split-item ${stage === "left_kick" ? "active" : ""}`}
        >
          <span className="k">Left</span>
          <span className="v">{data?.left_reps ?? 0}</span>
        </div>
        <div
          className={`bk-split-item ${stage === "right_kick" ? "active" : ""}`}
        >
          <span className="k">Right</span>
          <span className="v">{data?.right_reps ?? 0}</span>
        </div>
      </div>

      <div className="bk-meter">
        <div className="bk-meter-label">
          <span>Kick height</span>
          <span>{peakPct}%</span>
        </div>
        <div className="bk-meter-track">
          <div className="bk-meter-fill" style={{ width: `${peakPct}%` }} />
        </div>
      </div>

      <div className="bk-grid">
        <div className="bk-grid-item">
          <span className="k">Knee flexion</span>
          <span className="v">
            {data?.knee_flexion_deg != null
              ? `${data.knee_flexion_deg.toFixed(0)}°`
              : "—"}
          </span>
        </div>
        <div className="bk-grid-item">
          <span className="k">Cadence</span>
          <span className="v">
            {data?.cadence_estimate != null
              ? `${data.cadence_estimate.toFixed(0)}/min`
              : "—"}
          </span>
        </div>
        <div className="bk-grid-item">
          <span className="k">Good / Flawed</span>
          <span className="v">
            {data?.good_reps ?? 0} / {data?.flawed_reps ?? 0}
          </span>
        </div>
        <div className="bk-grid-item">
          <span className="k">Last rep</span>
          <span className="v">
            {data?.rep_duration != null
              ? `${data.rep_duration.toFixed(2)}s`
              : "—"}
          </span>
        </div>
        <div className="bk-grid-item">
          <span className="k">Tempo</span>
          <span className="v">
            {data?.rep_classification
              ? data.rep_classification.replace("_", " ")
              : "—"}
          </span>
        </div>
        <div className="bk-grid-item">
          <span className="k">Tracking confidence</span>
          <span className="v">{confidencePct}%</span>
        </div>
      </div>

      <div className={`bk-quality-badge ${quality ?? ""}`}>
        {quality ? quality.replace("_", " ") : "form: —"}
      </div>

      <div
        className={`bk-posture-line ${data?.framing_ok === false ? "bad" : "ok"}`}
      >
        {data?.framing_ok === false && data.framing_message
          ? data.framing_message
          : "Framing: good — full body visible in shot"}
      </div>

      <div className={`bk-posture-line ${data?.position_ok ? "ok" : "bad"}`}>
        {data?.position_ok
          ? "Standing tall — counting kicks"
          : (data?.position_message ?? "Stand tall with your legs in frame…")}
      </div>
    </div>
  );
}
