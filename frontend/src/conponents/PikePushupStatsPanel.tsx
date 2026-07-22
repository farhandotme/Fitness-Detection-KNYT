import type { PikePushupData } from "../hooks/usePikePushupSocket";

interface Props {
  data: PikePushupData | undefined;
}

const UP_ANGLE = 100;
const DOWN_ANGLE = 155;

function viewLabel(view: PikePushupData["view_mode"]): string {
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

/** Small self-contained elbow-angle gauge — avoids depending on a shared
 * AngleGauge component that isn't present in this project export. */
function ElbowAngleGauge({
  angle,
  stage,
}: {
  angle: number | null;
  stage: string;
}) {
  const clamped =
    angle != null
      ? Math.max(UP_ANGLE - 15, Math.min(DOWN_ANGLE + 15, angle))
      : null;
  const span = DOWN_ANGLE + 15 - (UP_ANGLE - 15);
  const pct = clamped != null ? ((clamped - (UP_ANGLE - 15)) / span) * 100 : 0;

  return (
    <div className="pike-gauge">
      <div className="pike-gauge-track">
        <div
          className={`pike-gauge-fill ${stage === "up" ? "up" : "down"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="pike-gauge-labels">
        <span>Bent ({UP_ANGLE}°)</span>
        <span>Extended ({DOWN_ANGLE}°)</span>
      </div>
    </div>
  );
}

export default function PikePushupStatsPanel({ data }: Props) {
  const angle = data?.smoothed_angle ?? data?.angle ?? null;
  const quality = data?.rep_form_quality;

  return (
    <div className="arm-panel pike-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">PIKE PUSH-UP</span>
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

      <ElbowAngleGauge angle={angle} stage={data?.stage ?? "down"} />

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Elbow angle</span>
          <span className="v">
            {angle != null ? `${angle.toFixed(1)}°` : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Hip angle</span>
          <span className="v">
            {data?.hip_angle != null ? `${data.hip_angle.toFixed(0)}°` : "—"}
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
          ? "Pike position confirmed — counting reps"
          : (data?.position_message ??
            "Waiting for a confirmed pike position…")}
      </div>

      <div
        className={`posture-line ${data?.alignment_ok === false ? "bad" : "ok"}`}
      >
        {data?.alignment_ok === false && data.alignment_issue
          ? data.alignment_issue.replace(/_/g, " ")
          : "Form looks good — hips high, legs straight"}
      </div>
    </div>
  );
}
