import type { MountainClimberData } from "../hooks/useMountainClimberSocket";

interface Props {
  data: MountainClimberData | undefined;
}

const DRIVEN_ANGLE = 125;
const EXTENDED_ANGLE = 155;

/**
 * Small inline hip-angle bar per leg — the same pattern as
 * JabStatsPanel's `MiniAngleBar`, just flipped (a mountain climber's
 * "rest" state is a high angle, its "active" state is a low angle,
 * the opposite of a jab's guard/extend). Everything else on this panel
 * reuses PushupStatsPanel's shared classes (`arm-panel`, `stage-badge`,
 * `arm-grid`, `posture-line`, `pose-pill`).
 */
function MiniAngleBar({
  label,
  angle,
  stage,
}: {
  label: string;
  angle: number | null;
  stage: "extended" | "driven";
}) {
  const pct =
    angle == null
      ? 0
      : Math.max(
          0,
          Math.min(
            100,
            ((EXTENDED_ANGLE - angle) / (EXTENDED_ANGLE - DRIVEN_ANGLE)) * 100,
          ),
        );
  return (
    <div className="jab-angle-bar">
      <div className="jab-angle-bar-head">
        <span className="k">{label}</span>
        <span className={`stage-badge ${stage}`}>
          {stage === "driven" ? "DRIVE" : "PLANK"}
        </span>
      </div>
      <div className="jab-angle-bar-track">
        <div className="jab-angle-bar-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="v">{angle != null ? `${angle.toFixed(0)}°` : "—"}</span>
    </div>
  );
}

export default function MountainClimberStatsPanel({ data }: Props) {
  const tempo = data?.drive_classification;

  return (
    <div className="arm-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">MOUNTAIN CLIMBER</span>
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
        <span className="stage-badge">total knee drives</span>
      </div>

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Left leg</span>
          <span className="v">{data?.left_count ?? 0}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Right leg</span>
          <span className="v">{data?.right_count ?? 0}</span>
        </div>
      </div>

      <MiniAngleBar
        label="Left hip"
        angle={data?.left_hip_angle ?? null}
        stage={data?.left_stage ?? "extended"}
      />
      <MiniAngleBar
        label="Right hip"
        angle={data?.right_hip_angle ?? null}
        stage={data?.right_stage ?? "extended"}
      />

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Last drive</span>
          <span className="v">
            {data?.drive_duration != null
              ? `${data.drive_duration.toFixed(2)}s`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Tempo</span>
          <span className="v">{tempo ? tempo.replace("_", " ") : "—"}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Leg</span>
          <span className="v">{data?.drive_leg ? data.drive_leg : "—"}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Elapsed</span>
          <span className="v">{(data?.elapsed_time ?? 0).toFixed(0)}s</span>
        </div>
      </div>

      <div
        className={`posture-line ${data?.framing_ok === false ? "bad" : "ok"}`}
      >
        {data?.framing_ok === false && data.framing_message
          ? data.framing_message
          : "Framing: good — full body visible"}
      </div>

      <div className={`posture-line ${data?.stance_ok ? "ok" : "bad"}`}>
        {data?.stance_ok
          ? "Plank confirmed — counting knee drives"
          : (data?.stance_message ?? "Waiting for a confirmed plank base…")}
      </div>
    </div>
  );
}
