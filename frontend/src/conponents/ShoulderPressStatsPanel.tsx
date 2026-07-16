import type { ShoulderPressData } from "../hooks/useShoulderPressSocket";
import AngleGauge from "./AngleGauge";

interface Props {
  data: ShoulderPressData | undefined;
}

// Elbow angle (shoulder-elbow-wrist): "racked" ~ 90° (dumbbells at shoulder
// height), "pressed" ~ 170° (arms extended overhead) — same up/down naming
// convention as squat/bicep curl so the shared AngleGauge works unmodified.
const PRESSED_ANGLE = 165;
const RACKED_ANGLE = 95;

export default function ShoulderPressStatsPanel({ data }: Props) {
  const angle =
    data?.smoothed_angle ??
    (data?.left_elbow_angle != null && data?.right_elbow_angle != null
      ? (data.left_elbow_angle + data.right_elbow_angle) / 2
      : null);
  const quality = data?.rep_form_quality;
  const stage = data?.stage ?? "racked";

  return (
    <div className="arm-panel sp-panel">
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
        <span className={`stage-badge ${stage === "pressed" ? "up" : "down"}`}>
          {stage === "pressed" ? "PRESSED" : "RACKED"}
        </span>
      </div>

      <AngleGauge
        angle={angle}
        upThreshold={RACKED_ANGLE}
        downThreshold={PRESSED_ANGLE}
        stage={stage === "pressed" ? "up" : "down"}
      />

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Left elbow</span>
          <span className="v">
            {data?.left_elbow_angle != null
              ? `${data.left_elbow_angle.toFixed(0)}°`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Right elbow</span>
          <span className="v">
            {data?.right_elbow_angle != null
              ? `${data.right_elbow_angle.toFixed(0)}°`
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
          <span className="k">Half reps</span>
          <span className="v">{data?.partial_rep_count ?? 0}</span>
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
      </div>

      <div className={`quality-badge ${quality ?? ""}`}>
        {quality ? quality.replace("_", " ") : "form: —"}
      </div>

      <div
        className={`posture-line ${data?.framing_ok === false ? "bad" : "ok"}`}
      >
        {data?.framing_ok === false && data.framing_message
          ? data.framing_message
          : "Position: good — full body in frame, centered"}
      </div>

      <div
        className={`posture-line ${data?.posture_ok === false ? "bad" : "ok"}`}
      >
        {data?.posture_ok === false && data.posture_issues.length > 0
          ? (data.posture_messages[0] ??
            data.posture_issues.join(", ").replace(/_/g, " "))
          : data?.calibrated
            ? "Posture looks good"
            : "Calibrating your form baseline…"}
      </div>
    </div>
  );
}
