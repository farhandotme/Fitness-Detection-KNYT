import type { BentOverRowData } from "../hooks/useBentOverRowSocket";

interface Props {
  data: BentOverRowData | undefined;
}

function checkRow(label: string, ok: boolean, badText: string) {
  return (
    <div className={`bor-check-row ${ok ? "ok" : "bad"}`}>
      <span className="bor-check-dot">{ok ? "✓" : "✕"}</span>
      <span className="bor-check-label">{label}</span>
      {!ok && <span className="bor-check-hint">{badText}</span>}
    </div>
  );
}

export default function BentOverRowStatsPanel({ data }: Props) {
  const quality = data?.rep_form_quality;
  const stage = data?.stage ?? "down";
  const inPosition = data?.in_position ?? false;

  return (
    <div className="arm-panel bor-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">BENT-OVER ROW</span>
        <span
          className={`pose-pill ${data?.pose_detected ? (data.low_visibility ? "warn" : "ok") : "bad"}`}
        >
          {data?.pose_detected
            ? data.low_visibility
              ? "Unstable"
              : "Tracking"
            : "No pose"}
        </span>
      </div>

      <div className="arm-panel-rep-row">
        <span className="arm-panel-rep-count">{data?.rep_count ?? 0}</span>
        <span className={`stage-badge ${stage}`}>
          {stage === "up" ? "PULLED UP" : "HANGING"}
        </span>
      </div>

      <div className={`bor-position-banner ${inPosition ? "ok" : "bad"}`}>
        {inPosition
          ? "✓ In row position — reps are counting"
          : "⚠ Not in position — reps are paused"}
      </div>

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Torso hinge</span>
          <span className="v">
            {data?.torso_incline != null
              ? `${data.torso_incline.toFixed(0)}°`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Elbow angle</span>
          <span className="v">
            {data?.elbow_angle != null
              ? `${data.elbow_angle.toFixed(0)}°`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Good / Flawed</span>
          <span className="v">
            {data?.good_reps ?? 0} / {data?.flawed_reps ?? 0}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Elapsed</span>
          <span className="v">{(data?.elapsed_time ?? 0).toFixed(0)}s</span>
        </div>
      </div>

      <div className={`quality-badge ${quality ?? ""}`}>
        {quality ? quality.replace("_", " ") : "form: —"}
      </div>

      <div
        className={`posture-line ${data?.framing_ok === false ? "bad" : "ok"}`}
      >
        {data?.framing_ok === false && data.framing_message
          ? data.framing_message
          : "Framing: good — full body visible in shot"}
      </div>

      <div className="bor-checklist">
        {checkRow(
          "Back flat",
          data?.back_flat ?? true,
          "Don't round your spine",
        )}
        {checkRow(
          "Elbows tracking straight back",
          data?.elbows_tracking ?? true,
          "Drive elbows back, not out to the sides",
        )}
        {checkRow(
          "Stayed hinged through the rep",
          data?.stayed_hinged ?? true,
          "Avoid standing upright mid-pull",
        )}
      </div>

      <div className={`posture-line ${inPosition ? "ok" : "bad"}`}>
        {data?.position_message ?? "Hinge forward at the hips to begin."}
      </div>
    </div>
  );
}
