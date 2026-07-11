import type { SquatData } from "../hooks/useSquatSocket";
import AngleGauge from "./AngleGauge";

interface Props {
  data: SquatData | undefined;
}

const UP_ANGLE = 100;
const DOWN_ANGLE = 160;

export default function SquatStatsPanel({ data }: Props) {
  const angle = data?.smoothed_angle ?? data?.angle ?? null;
  const quality = data?.rep_form_quality;

  return (
    <div className="arm-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">SQUAT</span>
        <span className={`pose-pill ${data?.pose_detected ? (data.low_visibility ? "warn" : "ok") : "bad"}`}>
          {data?.pose_detected ? (data.low_visibility ? "Unstable" : "Tracking") : "No pose"}
        </span>
      </div>

      <div className="arm-panel-rep-row">
        <span className="arm-panel-rep-count">{data?.rep_count ?? 0}</span>
        <span className={`stage-badge ${data?.stage ?? "down"}`}>
          {(data?.stage ?? "down") === "up" ? "SQUATTED" : "STANDING"}
        </span>
      </div>

      <AngleGauge angle={angle} upThreshold={UP_ANGLE} downThreshold={DOWN_ANGLE} stage={data?.stage ?? "down"} />

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Knee angle</span>
          <span className="v">{angle != null ? `${angle.toFixed(1)}°` : "—"}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Velocity</span>
          <span className="v">{data?.angle_velocity != null ? `${data.angle_velocity.toFixed(0)}°/s` : "—"}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Good / Flawed</span>
          <span className="v">{data?.good_reps ?? 0} / {data?.flawed_reps ?? 0}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Last rep</span>
          <span className="v">{data?.rep_duration != null ? `${data.rep_duration.toFixed(2)}s` : "—"}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Tempo</span>
          <span className="v">{data?.rep_classification ? data.rep_classification.replace("_", " ") : "—"}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Calibration</span>
          <span className="v">{data?.calibrated ? "Ready" : "Calibrating…"}</span>
        </div>
      </div>

      <div className={`quality-badge ${quality ?? ""}`}>{quality ? quality.replace("_", " ") : "form: —"}</div>

      <div className={`posture-line ${data?.posture_ok === false ? "bad" : "ok"}`}>
        {data?.posture_ok === false && data.posture_issues.length > 0
          ? data.posture_messages[0] ?? data.posture_issues.join(", ").replace(/_/g, " ")
          : "Posture looks good"}
      </div>
    </div>
  );
}
