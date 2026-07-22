import type { SumoSquatData } from "../hooks/useSumoSquatSocket";

interface Props {
  data: SumoSquatData | undefined;
}

const SQUAT_ANGLE = 120;
const STAND_ANGLE = 160;

function viewLabel(view: SumoSquatData["view_mode"]): string {
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

/**
 * Small inline knee-angle gauge — deliberately self-contained (no shared
 * `AngleGauge` component dependency) so this panel doesn't break if that
 * component doesn't exist elsewhere in the app.
 */
function KneeAngleGauge({
  angle,
  stage,
}: {
  angle: number | null;
  stage: string;
}) {
  const pct =
    angle == null
      ? 0
      : Math.max(
          0,
          Math.min(
            100,
            ((STAND_ANGLE - angle) / (STAND_ANGLE - SQUAT_ANGLE)) * 100,
          ),
        );

  return (
    <div className="sumo-gauge">
      <div className="sumo-gauge-track">
        <div
          className={`sumo-gauge-fill ${stage === "down" ? "down" : "up"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="sumo-gauge-labels">
        <span>Standing</span>
        <span>Squat depth</span>
      </div>
    </div>
  );
}

export default function SumoSquatStatsPanel({ data }: Props) {
  const angle = data?.smoothed_angle ?? data?.angle ?? null;
  const quality = data?.rep_form_quality;

  return (
    <div className="arm-panel sumo-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">SUMO SQUAT</span>
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
        <span className={`stage-badge ${data?.stage ?? "up"}`}>
          {(data?.stage ?? "up") === "down" ? "SQUAT" : "STANDING"}
        </span>
      </div>

      <KneeAngleGauge angle={angle} stage={data?.stage ?? "up"} />

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Knee angle</span>
          <span className="v">
            {angle != null ? `${angle.toFixed(1)}°` : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Stance width</span>
          <span className="v">
            {data?.stance_ratio != null
              ? `${data.stance_ratio.toFixed(2)}x`
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
          ? "Sumo stance confirmed — counting reps"
          : (data?.position_message ??
            "Waiting for a confirmed wide sumo stance…")}
      </div>

      <div
        className={`posture-line ${data?.knee_tracking_ok === false ? "bad" : "ok"}`}
      >
        {data?.knee_tracking_ok === false
          ? "Knees caving in — push them out over your toes"
          : "Knee tracking looks good"}
      </div>

      <div
        className={`posture-line ${data?.torso_upright_ok === false ? "bad" : "ok"}`}
      >
        {data?.torso_upright_ok === false
          ? "Leaning too far forward — keep your chest up"
          : "Torso posture looks upright"}
      </div>
    </div>
  );
}
