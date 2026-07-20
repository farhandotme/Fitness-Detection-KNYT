import type { JabData } from "../hooks/useJabSocket";

interface Props {
  data: JabData | undefined;
}

const GUARD_ANGLE = 110;
const EXTEND_ANGLE = 150;

/** Small inline elbow-angle gauge — self-contained so this panel doesn't
 * depend on the (missing from this repo snapshot) shared AngleGauge
 * component. Renders a horizontal bar per arm from guard -> extended. */
function MiniAngleBar({
  label,
  angle,
  stage,
}: {
  label: string;
  angle: number | null;
  stage: "guard" | "extended";
}) {
  const pct =
    angle == null
      ? 0
      : Math.max(
          0,
          Math.min(
            100,
            ((angle - GUARD_ANGLE) / (EXTEND_ANGLE - GUARD_ANGLE)) * 100,
          ),
        );
  return (
    <div className="jab-arm-bar">
      <div className="jab-arm-bar-head">
        <span className="k">{label}</span>
        <span className={`jab-stage-badge ${stage}`}>
          {stage === "extended" ? "PUNCH" : "GUARD"}
        </span>
      </div>
      <div className="jab-arm-bar-track">
        <div className="jab-arm-bar-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="jab-arm-bar-value">
        {angle != null ? `${angle.toFixed(0)}°` : "—"}
      </span>
    </div>
  );
}

export default function JabStatsPanel({ data }: Props) {
  const tempo = data?.punch_classification;

  return (
    <div className="arm-panel jab-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">MUAY THAI JAB</span>
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
        <span className="jab-count-caption">total jabs</span>
      </div>

      <div className="jab-hand-split">
        <div className="jab-hand-split-item">
          <span className="k">Left</span>
          <span className="v">{data?.left_count ?? 0}</span>
        </div>
        <div className="jab-hand-split-item">
          <span className="k">Right</span>
          <span className="v">{data?.right_count ?? 0}</span>
        </div>
      </div>

      <MiniAngleBar
        label="Left arm"
        angle={data?.left_elbow_angle ?? null}
        stage={data?.left_stage ?? "guard"}
      />
      <MiniAngleBar
        label="Right arm"
        angle={data?.right_elbow_angle ?? null}
        stage={data?.right_stage ?? "guard"}
      />

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Last punch</span>
          <span className="v">
            {data?.punch_duration != null
              ? `${data.punch_duration.toFixed(2)}s`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Tempo</span>
          <span className="v">{tempo ? tempo.replace("_", " ") : "—"}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Hand</span>
          <span className="v">
            {data?.punch_hand ? data.punch_hand : "—"}
          </span>
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
          : "Framing: good — upper body fully visible"}
      </div>

      <div className={`posture-line ${data?.stance_ok ? "ok" : "bad"}`}>
        {data?.stance_ok
          ? "Stance confirmed — counting jabs"
          : (data?.stance_message ?? "Waiting for a confirmed boxing stance…")}
      </div>
    </div>
  );
}
