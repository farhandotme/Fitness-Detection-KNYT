import type { ShoulderPressData } from "../hooks/useShoulderPressSocket";
import AngleGauge from "./AngleGauge";

interface Props {
  data: ShoulderPressData | undefined;
}

const BOTTOM_ANGLE = 100;
const TOP_ANGLE = 150;

export default function ShoulderPressStatsPanel({ data }: Props) {
  const angle = data?.smoothed_angle ?? data?.angle ?? null;
  const quality = data?.rep_form_quality;

  return (
    <div className="arm-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">SHOULDER PRESS</span>
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
        <span className={`stage-badge ${data?.stage ?? "bottom"}`}>
          {(data?.stage ?? "bottom") === "top" ? "ARMS UP" : "SHOULDERS"}
        </span>
      </div>

      <AngleGauge
        angle={angle}
        upThreshold={BOTTOM_ANGLE}
        downThreshold={TOP_ANGLE}
        stage={data?.stage === "top" ? "up" : "down"}
      />

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Arm angle</span>
          <span className="v">
            {angle != null ? `${angle.toFixed(1)}°` : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Good / Needs work</span>
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
          <span className="k">Pace</span>
          <span className="v">
            {data?.rep_classification
              ? data.rep_classification.replace("_", " ")
              : "—"}
          </span>
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
          : "Framing: good — arms fully visible in shot"}
      </div>

      <div className={`posture-line ${data?.position_ok ? "ok" : "bad"}`}>
        {data?.position_ok
          ? "Standing position confirmed — counting reps"
          : (data?.position_message ??
            "Waiting for a clear standing position…")}
      </div>

      <div className={`posture-line ${data?.lean_ok === false ? "bad" : "ok"}`}>
        {data?.lean_ok === false
          ? "Try not to lean backward as you press"
          : "Posture looks steady"}
      </div>
    </div>
  );
}
