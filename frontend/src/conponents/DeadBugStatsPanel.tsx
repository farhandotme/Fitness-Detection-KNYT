import type { DeadBugData } from "../hooks/useDeadBugSocket";

interface Props {
  data: DeadBugData | undefined;
}

const REASON_LABEL: Record<string, string> = {
  tempo: "too fast / too slow",
  cross_limb: "all 4 limbs moved",
  hip_drift: "hips shifted",
};

export default function DeadBugStatsPanel({ data }: Props) {
  return (
    <div className="arm-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">DEAD BUG</span>
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
        <span className="stage-badge">total reps</span>
      </div>

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Right arm + left leg</span>
          <span className="v">{data?.right_arm_left_leg_count ?? 0}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Left arm + right leg</span>
          <span className="v">{data?.left_arm_right_leg_count ?? 0}</span>
        </div>
      </div>

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Elapsed</span>
          <span className="v">{(data?.elapsed_time ?? 0).toFixed(0)}s</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Last rejected</span>
          <span className="v">
            {data?.invalid_attempt && data.invalid_reason
              ? REASON_LABEL[data.invalid_reason]
              : "—"}
          </span>
        </div>
      </div>

      <div
        className={`posture-line ${data?.framing_ok === false ? "bad" : "ok"}`}
      >
        {data?.framing_ok === false && data.framing_message
          ? data.framing_message
          : "Framing: good — full body and reach visible"}
      </div>

      <div className={`posture-line ${data?.stance_ok ? "ok" : "bad"}`}>
        {data?.stance_ok
          ? "Tabletop confirmed — counting reps"
          : (data?.stance_message ?? "Waiting for a confirmed tabletop position…")}
      </div>

      <div className={`posture-line ${data?.invalid_attempt ? "bad" : "ok"}`}>
        {data?.invalid_attempt
          ? `Attempt rejected — ${REASON_LABEL[data.invalid_reason ?? ""] ?? "form issue"}`
          : "Only real, coordinated opposite arm/leg reps count"}
      </div>
    </div>
  );
}
