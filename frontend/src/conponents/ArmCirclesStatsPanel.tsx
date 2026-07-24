import type { ArmCirclesData } from "../hooks/useArmCirclesSocket";

interface Props {
  data: ArmCirclesData | undefined;
}

function dirArrow(dir: "forward" | "backward" | null): string {
  if (dir === "forward") return "↻";
  if (dir === "backward") return "↺";
  return "—";
}

export default function ArmCirclesStatsPanel({ data }: Props) {
  const quality = data?.rep_form_quality;

  return (
    <div className="arm-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">ARM CIRCLES</span>
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
        <span className="arm-panel-rep-label">rounds (both arms)</span>
      </div>

      {/* Per-arm breakdown — the "how much have I done, each arm" data */}
      <div className="arm-circles-side-by-side">
        <div className="arm-circles-arm-card">
          <span className="arm-circles-arm-title">LEFT ARM</span>
          <span className="arm-circles-arm-count">
            {data?.left_arm_rounds ?? 0}
          </span>
          <span className="arm-circles-arm-sub">
            {dirArrow(data?.left_direction ?? null)}{" "}
            {data?.left_arm_extended ? "extended" : "tucked in"}
          </span>
        </div>
        <div className="arm-circles-arm-card">
          <span className="arm-circles-arm-title">RIGHT ARM</span>
          <span className="arm-circles-arm-count">
            {data?.right_arm_rounds ?? 0}
          </span>
          <span className="arm-circles-arm-sub">
            {dirArrow(data?.right_direction ?? null)}{" "}
            {data?.right_arm_extended ? "extended" : "tucked in"}
          </span>
        </div>
      </div>

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Left elbow</span>
          <span className="v">
            {data?.left_elbow_angle != null
              ? `${data.left_elbow_angle.toFixed(1)}°`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Right elbow</span>
          <span className="v">
            {data?.right_elbow_angle != null
              ? `${data.right_elbow_angle.toFixed(1)}°`
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
          <span className="k">Target</span>
          <span className="v">
            {data?.rep_count ?? 0} / {data?.target_reps ?? "—"}
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
          : "Framing: good — both arms visible in shot"}
      </div>
    </div>
  );
}
