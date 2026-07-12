import type { PushupData } from "../hooks/usePushupSocket";
import AngleGauge from "./AngleGauge";

interface Props {
  data: PushupData | undefined;
}

const UP_ANGLE = 95;
const DOWN_ANGLE = 155;

function viewLabel(view: PushupData["view_mode"]): string {
  switch (view) {
    case "side":
      return "Side view";
    case "front":
      return "Front view";
    case "angled":
      return "Angled view";
    default:
      return "—";
  }
}

export default function PushupStatsPanel({ data }: Props) {
  const angle = data?.smoothed_angle ?? data?.angle ?? null;
  const quality = data?.rep_form_quality;

  return (
    <div className="arm-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">PUSH-UP</span>
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
        <span className={`stage-badge ${data?.stage ?? "down"}`}>
          {(data?.stage ?? "down") === "up" ? "BOTTOM" : "TOP"}
        </span>
      </div>

      <AngleGauge
        angle={angle}
        upThreshold={UP_ANGLE}
        downThreshold={DOWN_ANGLE}
        stage={data?.stage ?? "down"}
      />

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Elbow angle</span>
          <span className="v">
            {angle != null ? `${angle.toFixed(1)}°` : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Velocity</span>
          <span className="v">
            {data?.angle_velocity != null
              ? `${data.angle_velocity.toFixed(0)}°/s`
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
          <span className="k">Last rep</span>
          <span className="v">
            {data?.rep_duration != null
              ? `${data.rep_duration.toFixed(2)}s`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Tempo</span>
          <span className="v">
            {data?.rep_classification
              ? data.rep_classification.replace("_", " ")
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Camera</span>
          <span className="v">{viewLabel(data?.view_mode ?? null)}</span>
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

      <div className={`posture-line ${data?.position_ok ? "ok" : "bad"}`}>
        {data?.position_ok
          ? "Plank position confirmed — counting reps"
          : (data?.position_message ??
            "Waiting for a confirmed floor plank position…")}
      </div>

      <div
        className={`posture-line ${data?.alignment_ok === false ? "bad" : "ok"}`}
      >
        {data?.alignment_ok === false && data.alignment_issue
          ? data.alignment_issue.replace(/_/g, " ")
          : "Body line looks straight"}
      </div>
    </div>
  );
}
