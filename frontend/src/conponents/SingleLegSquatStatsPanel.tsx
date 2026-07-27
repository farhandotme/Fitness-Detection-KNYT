import type { SingleLegSquatData } from "../hooks/useSingleLegSquatSocket";
import AngleGauge from "./AngleGauge";

interface Props {
  data: SingleLegSquatData | undefined;
}

function modeLabel(mode: SingleLegSquatData["support_mode"]): string {
  switch (mode) {
    case "assisted":
      return "Assisted (shallow, balance help)";
    case "deep":
      return "Deep / pistol-style";
    default:
      return "Standard";
  }
}

function stageLabel(stage: SingleLegSquatData["stage"]): string {
  switch (stage) {
    case "descending":
      return "LOWERING";
    case "bottom":
      return "BOTTOM";
    case "rising":
      return "RISING";
    default:
      return "STANDING";
  }
}

export default function SingleLegSquatStatsPanel({ data }: Props) {
  const angle = data?.stance_knee_angle ?? null;
  const quality = data?.rep_form_quality;
  // Calibrated per-session by the backend — see single_leg_squat.py's
  // `_run_calibration`. Falls back to a sane default only for the brief
  // window before the first response arrives.
  const bottomAngle = data?.bottom_angle_threshold ?? 120;
  const topAngle = data?.top_angle_threshold ?? 160;

  return (
    <div className="arm-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">
          SINGLE LEG SQUAT · {(data?.current_side ?? "left").toUpperCase()}
        </span>
        <span
          className={`pose-pill ${
            !data?.pose_detected
              ? "bad"
              : data?.calibrated === false
                ? "warn"
                : data.low_visibility
                  ? "warn"
                  : "ok"
          }`}
        >
          {!data?.pose_detected
            ? "No pose"
            : data?.calibrated === false
              ? "Calibrating…"
              : data.low_visibility
                ? "Unstable"
                : "Tracking"}
        </span>
      </div>

      <div className="arm-panel-rep-row">
        <span className="arm-panel-rep-count">{data?.rep_count ?? 0}</span>
        <span className={`stage-badge ${data?.stage ?? "standing"}`}>
          {stageLabel(data?.stage ?? "standing")}
        </span>
      </div>

      <AngleGauge
        angle={angle}
        upThreshold={bottomAngle}
        downThreshold={topAngle}
        stage={data?.stage === "standing" ? "down" : "up"}
      />

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Stance knee angle</span>
          <span className="v">
            {angle != null ? `${angle.toFixed(1)}°` : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Depth</span>
          <span className="v">
            {data?.hip_depth_ratio != null
              ? `${Math.round(data.hip_depth_ratio * 100)}%`
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
          <span className="k">Tempo</span>
          <span className="v">
            {data?.rep_classification
              ? data.rep_classification.replace("_", " ")
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Torso angle</span>
          <span className="v">
            {data?.torso_angle != null
              ? `${data.torso_angle.toFixed(0)}°`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Balance</span>
          <span className="v">
            {data?.balance_confidence != null
              ? `${Math.round(data.balance_confidence * 100)}%`
              : "—"}
          </span>
        </div>
      </div>

      <div className="squat-mode-line">
        Mode: {modeLabel(data?.support_mode ?? "standard")}
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
          ? "Standing position confirmed — counting reps"
          : (data?.position_message ??
            "Waiting for a confirmed standing position…")}
      </div>

      <div
        className={`posture-line ${data?.knee_tracking_ok === false ? "bad" : "ok"}`}
      >
        {data?.knee_tracking_ok === false
          ? "Knee collapsing inward — track it over your foot"
          : "Knee tracking well over the foot"}
      </div>

      <div
        className={`posture-line ${data?.pelvis_level === false ? "bad" : "ok"}`}
      >
        {data?.pelvis_level === false
          ? "Hip dropping on the free side — keep the pelvis level"
          : "Pelvis staying level"}
      </div>

      <div
        className={`posture-line ${data?.bottom_lock || data?.stage === "bottom" ? "ok" : ""}`}
      >
        {data?.bottom_lock
          ? "Depth confirmed — nice, settled bottom position"
          : "Sit back and down to reach depth"}
      </div>
    </div>
  );
}
