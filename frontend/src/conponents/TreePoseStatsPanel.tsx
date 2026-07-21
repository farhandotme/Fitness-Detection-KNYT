import type { TreePoseData } from "../hooks/useTreePoseSocket";

interface Props {
  data: TreePoseData | undefined;
}

function formatSeconds(s: number | undefined | null): string {
  const total = Math.max(0, s ?? 0);
  const m = Math.floor(total / 60);
  const sec = total - m * 60;
  if (m > 0) return `${m}:${sec.toFixed(1).padStart(4, "0")}`;
  return `${sec.toFixed(1)}s`;
}

const STATE_LABEL: Record<string, string> = {
  not_started: "GET READY",
  holding: "HOLDING",
  broken: "PAUSED",
};

export default function TreePoseStatsPanel({ data }: Props) {
  const state = data?.hold_state ?? "not_started";
  const quality = data?.hold_quality;
  const target = data?.target_seconds;

  return (
    <div className="arm-panel tree-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">TREE POSE</span>
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

      <div className={`tree-timer tree-timer--${state}`}>
        <div className="tree-timer-value">
          {formatSeconds(
            data?.active_leg === "right" ? data?.right_seconds : data?.left_seconds ?? data?.hold_seconds,
          )}
        </div>
        {target != null && <div className="tree-timer-target">/ {formatSeconds(target)}</div>}
      </div>

      <div className="tree-state-row">
        <span className={`stage-badge ${state === "holding" ? "up" : "down"}`}>
          {STATE_LABEL[state]}
        </span>
        {data?.active_leg && (
          <span className="tree-side-pill">standing on {data.active_leg} leg</span>
        )}
      </div>

      <div className="tree-legs-row">
        <div className={`tree-leg-card ${data?.left_complete ? "complete" : ""} ${data?.active_leg === "left" ? "active" : ""}`}>
          <span className="k">Left leg</span>
          <span className="v">{formatSeconds(data?.left_seconds)}</span>
          {data?.left_complete && <span className="tree-leg-check">✓</span>}
        </div>
        <div className={`tree-leg-card ${data?.right_complete ? "complete" : ""} ${data?.active_leg === "right" ? "active" : ""}`}>
          <span className="k">Right leg</span>
          <span className="v">{formatSeconds(data?.right_seconds)}</span>
          {data?.right_complete && <span className="tree-leg-check">✓</span>}
        </div>
      </div>

      {target != null && (
        <div className="tree-progress-track">
          <div
            className="tree-progress-fill tree-progress-fill--left"
            style={{
              width: `${Math.min(100, ((data?.left_seconds ?? 0) / target) * 100)}%`,
            }}
          />
          <div
            className="tree-progress-fill tree-progress-fill--right"
            style={{
              width: `${Math.min(100, ((data?.right_seconds ?? 0) / target) * 100)}%`,
            }}
          />
        </div>
      )}

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Current streak</span>
          <span className="v">{formatSeconds(data?.current_streak_seconds)}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Best streak</span>
          <span className="v">{formatSeconds(data?.best_streak_seconds)}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Breaks</span>
          <span className="v">{data?.break_count ?? 0}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Good / Flawed</span>
          <span className="v">
            {formatSeconds(data?.good_seconds)} / {formatSeconds(data?.flawed_seconds)}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Standing knee</span>
          <span className="v">
            {data?.standing_knee_angle != null ? `${data.standing_knee_angle.toFixed(1)}°` : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Torso tilt</span>
          <span className="v">
            {data?.torso_tilt_angle != null ? `${data.torso_tilt_angle.toFixed(1)}°` : "—"}
          </span>
        </div>
      </div>

      <div className="arm-grid" style={{ marginTop: 4 }}>
        <div className="arm-grid-item">
          <span className="k">Form score</span>
          <span className="v">{data?.form_score != null ? data.form_score : (data?.avg_form_score ?? "—")}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Avg form</span>
          <span className="v">{data?.avg_form_score ?? "—"}</span>
        </div>
      </div>

      <div className={`quality-badge ${quality ?? ""}`}>
        {quality ? quality.replace("_", " ") : "form: —"}
      </div>

      <div className={`posture-line ${data?.framing_ok === false ? "bad" : "ok"}`}>
        {data?.framing_ok === false && data.framing_message
          ? data.framing_message
          : "Position: good — front-on, full body in frame"}
      </div>

      <div className={`posture-line ${data?.posture_ok === false ? "bad" : "ok"}`}>
        {data?.posture_ok === false && data.posture_issues.length > 0
          ? (data.posture_messages[0] ?? data.posture_issues.join(", ").replace(/_/g, " "))
          : "Posture looks good"}
      </div>
    </div>
  );
}
