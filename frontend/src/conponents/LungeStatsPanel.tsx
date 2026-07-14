import type { LungeData } from "../hooks/useLungeSocket";
import AngleGauge from "./AngleGauge";

interface Props {
  data: LungeData | undefined;
}

const UP_ANGLE = 100; // front knee angle at the bottom of a good lunge
const DOWN_ANGLE = 165; // front knee angle standing tall

const LEG_LABEL: Record<string, string> = {
  left: "LEFT LEG",
  right: "RIGHT LEG",
};

export default function LungeStatsPanel({ data }: Props) {
  const displayAngle =
    data?.front_knee_angle ??
    (data?.left_knee_angle != null && data?.right_knee_angle != null
      ? Math.min(data.left_knee_angle, data.right_knee_angle)
      : null);
  const quality = data?.rep_form_quality;
  const activeLeg = data?.active_leg;

  return (
    <div className="arm-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">LUNGE</span>
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
        <span className={`stage-badge ${data?.stage ?? "standing"}`}>
          {activeLeg
            ? LEG_LABEL[activeLeg]
            : (data?.stage ?? "standing") === "down"
              ? "LUNGING"
              : "STANDING"}
        </span>
      </div>

      <AngleGauge
        angle={displayAngle}
        upThreshold={UP_ANGLE}
        downThreshold={DOWN_ANGLE}
        stage={data?.stage === "down" ? "up" : "down"}
      />

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Front knee</span>
          <span className="v">
            {displayAngle != null ? `${displayAngle.toFixed(1)}°` : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Back knee</span>
          <span className="v">
            {data?.back_knee_angle != null
              ? `${data.back_knee_angle.toFixed(1)}°`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Left / Right reps</span>
          <span className="v">
            {data?.left_reps ?? 0} / {data?.right_reps ?? 0}
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
        <div className="arm-grid-item">
          <span className="k">Calibration</span>
          <span className="v">
            {data?.calibrated ? "Ready" : "Calibrating…"}
          </span>
        </div>
      </div>

      <div className="arm-grid" style={{ marginTop: 4 }}>
        <div className="arm-grid-item">
          <span className="k">Form score</span>
          <span className="v">
            {data?.form_score != null
              ? data.form_score
              : (data?.avg_form_score ?? "—")}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Avg form</span>
          <span className="v">{data?.avg_form_score ?? "—"}</span>
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

      <div
        className={`posture-line ${data?.leg_balance_ok === false ? "bad" : "ok"}`}
      >
        {data?.leg_balance_ok === false && data.leg_balance_message
          ? data.leg_balance_message
          : "Leg balance looks good"}
      </div>
    </div>
  );
}
