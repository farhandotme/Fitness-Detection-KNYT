import type { LegRaiseData } from "../hooks/useLegRaiseSocket";
import AngleGauge from "./AngleGauge";

interface Props {
  data: LegRaiseData | undefined;
}

// Same values as `BOTTOM_ANGLE` / `TOP_ANGLE` in leg_raise.py — the gauge
// reads the hip-flexion angle counting DOWN from bottom to top, so it's
// wired the same way pushup's elbow gauge is (upThreshold = the smaller
// angle, downThreshold = the larger one).
const TOP_ANGLE = 135;
const BOTTOM_ANGLE = 155;

function viewLabel(view: LegRaiseData["view_mode"]): string {
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

export default function LegRaiseStatsPanel({ data }: Props) {
  const leftAngle = data?.left_leg_angle ?? null;
  const rightAngle = data?.right_leg_angle ?? null;
  const avgAngle =
    leftAngle != null && rightAngle != null
      ? (leftAngle + rightAngle) / 2
      : (leftAngle ?? rightAngle);
  const quality = data?.rep_form_quality;

  return (
    <div className="arm-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">LEG RAISE</span>
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
          {(data?.stage ?? "down") === "up" ? "TOP" : "BOTTOM"}
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
          <span className="k">Left leg angle</span>
          <span className="v">
            {leftAngle != null ? `${leftAngle.toFixed(1)}°` : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Right leg angle</span>
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
          ? "Lying position confirmed — counting reps"
          : (data?.position_message ??
            "Waiting for a confirmed lying-flat position…")}
      </div>

      <div
        className={`posture-line ${data?.legs_in_sync === false ? "bad" : "ok"}`}
      >
        {data?.legs_in_sync === false
          ? "Legs aren't moving together — one is lagging"
          : "Legs are moving in sync"}
      </div>

      <div
        className={`posture-line ${data?.back_control_ok === false ? "bad" : "ok"}`}
      >
        {data?.back_control_ok === false
          ? "Lower back arching — keep your core braced"
          : "Lower back looks controlled"}
      </div>

      {data?.variation === "straight" && (
        <div
          className={`posture-line ${data?.knee_bend_ok === false ? "bad" : "ok"}`}
        >
          {data?.knee_bend_ok === false
            ? "Knees bending — straighten your legs more if you can"
            : "Legs staying straight"}
        </div>
      )}
    </div>
  );
}
