import type { ArnoldPressData } from "../hooks/useArnoldPressSocket";
import AngleGauge from "./AngleGauge";

interface Props {
  data: ArnoldPressData | undefined;
}

// Same values as `BOTTOM_ANGLE` / `TOP_ANGLE` in arnold_press.py — wired
// the same way the other exercises' gauges are (upThreshold = the
// smaller angle, downThreshold = the larger one — here inverted from
// leg-raise/squat since this angle counts UP toward the top instead of
// down).
const BOTTOM_ANGLE = 115;
const TOP_ANGLE = 150;

export default function ArnoldPressStatsPanel({ data }: Props) {
  const leftAngle = data?.left_elbow_angle ?? null;
  const rightAngle = data?.right_elbow_angle ?? null;
  const avgAngle =
    leftAngle != null && rightAngle != null
      ? (leftAngle + rightAngle) / 2
      : (leftAngle ?? rightAngle);
  const quality = data?.rep_form_quality;

  return (
    <div className="arm-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">ARNOLD PRESS</span>
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
          {(data?.stage ?? "down") === "up" ? "OVERHEAD" : "RACK"}
        </span>
      </div>

      <AngleGauge
        angle={avgAngle}
        upThreshold={TOP_ANGLE}
        downThreshold={BOTTOM_ANGLE}
        stage={data?.stage ?? "down"}
      />

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Left elbow angle</span>
          <span className="v">
            {leftAngle != null ? `${leftAngle.toFixed(1)}°` : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Right elbow angle</span>
          <span className="v">
            {rightAngle != null ? `${rightAngle.toFixed(1)}°` : "—"}
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
          ? "Upright position confirmed — counting reps"
          : (data?.position_message ??
            "Waiting for a confirmed upright position…")}
      </div>

      <div
        className={`posture-line ${data?.arms_in_sync === false ? "bad" : "ok"}`}
      >
        {data?.arms_in_sync === false
          ? "Arms aren't moving together — one is lagging"
          : "Arms are moving in sync"}
      </div>

      <div
        className={`posture-line ${data?.torso_stable_ok === false ? "bad" : "ok"}`}
      >
        {data?.torso_stable_ok === false
          ? "Leaning to use momentum — keep the torso still"
          : "Torso staying stable"}
      </div>

      <div
        className={`posture-line ${data?.stage === "up" && data?.wrist_overhead_ok === false ? "bad" : ""}`}
      >
        {data?.stage === "up" && data?.wrist_overhead_ok === false
          ? "Not quite overhead yet — press higher"
          : "Overhead extension looks good"}
      </div>

      <div
        className={`posture-line ${data?.stage === "down" && data?.rack_confirmed === false ? "bad" : "ok"}`}
      >
        {data?.stage === "down" && data?.rack_confirmed === false
          ? "Elbows too flared — tuck in for an Arnold press, not a shoulder press"
          : "Rack position confirmed — elbows tucked in"}
      </div>
    </div>
  );
}
