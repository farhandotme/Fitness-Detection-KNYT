import type { AdvancedBridgePoseData } from "./useAdvancedBridgePoseSocket";

interface Props {
  data: AdvancedBridgePoseData | undefined;
}

function formatSeconds(s: number): string {
  const total = Math.max(0, s);
  const m = Math.floor(total / 60);
  const sec = total - m * 60;
  if (m > 0) return `${m}:${sec.toFixed(0).padStart(2, "0")}`;
  return `${sec.toFixed(1)}s`;
}

function issueLabel(issue: string): string {
  switch (issue) {
    case "arms_bent":
      return "Arms not fully extended";
    case "legs_bent":
      return "Legs not fully extended";
    case "head_position":
      return "Head/neck drifted";
    default:
      return issue.replace(/_/g, " ");
  }
}

export default function AdvancedBridgePoseStatsPanel({ data }: Props) {
  const quality = data?.hold_quality;
  const issues = data?.posture_issues ?? [];

  // Arch angle: smaller = deeper arch. Map ~180 (flat) -> 0% and ~60
  // (deep wheel) -> 100% for the gauge.
  const angle = data?.arch_angle ?? null;
  const pct =
    angle == null ? 0 : Math.max(0, Math.min(100, ((180 - angle) / 120) * 100));

  return (
    <div className="arm-panel bridge-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">ADVANCED BRIDGE POSE</span>
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

      <div className="bridge-timer-row">
        <span className="bridge-timer-big">
          {formatSeconds(data?.hold_seconds ?? 0)}
        </span>
        <span className={`stage-badge ${data?.is_holding ? "up" : "down"}`}>
          {data?.hold_state === "not_started"
            ? "NOT STARTED"
            : data?.is_holding
              ? "HOLDING"
              : "BROKEN"}
        </span>
      </div>

      {data?.target_seconds != null && (
        <div className="bridge-target-caption">
          Target: {formatSeconds(data.target_seconds)} · current streak{" "}
          {formatSeconds(data?.current_streak_seconds ?? 0)}
        </div>
      )}

      <div className="bridge-gauge">
        <div className="bridge-gauge-track">
          <div
            className={`bridge-gauge-fill ${data?.is_holding ? "up" : "down"}`}
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="bridge-gauge-labels">
          <span>Flat</span>
          <span>Deep arch</span>
        </div>
      </div>

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Arch angle</span>
          <span className="v">
            {angle != null ? `${angle.toFixed(1)}°` : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Elbow angle</span>
          <span className="v">
            {data?.elbow_angle != null
              ? `${data.elbow_angle.toFixed(1)}°`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Knee angle</span>
          <span className="v">
            {data?.knee_angle != null ? `${data.knee_angle.toFixed(1)}°` : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Good / Flawed</span>
          <span className="v">
            {formatSeconds(data?.good_seconds ?? 0)} /{" "}
            {formatSeconds(data?.flawed_seconds ?? 0)}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Best streak</span>
          <span className="v">
            {formatSeconds(data?.best_streak_seconds ?? 0)}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Breaks</span>
          <span className="v">{data?.break_count ?? 0}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Form score</span>
          <span className="v">
            {data?.avg_form_score != null ? data.avg_form_score : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Camera</span>
          <span className="v">
            {data?.view_mode === "side"
              ? "Side view"
              : data?.view_mode === "front"
                ? "Front view"
                : data?.view_mode === "angled"
                  ? "Angled view"
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

      <div className={`posture-line ${data?.is_holding ? "ok" : "bad"}`}>
        {data?.is_holding
          ? "Bridge confirmed — hips are the highest point, timer running"
          : (data?.feedback ?? "Waiting for a confirmed bridge position…")}
      </div>

      {issues.length > 0 && (
        <div className="posture-line bad">
          {issues.map(issueLabel).join(" · ")}
        </div>
      )}

      {!data?.calibrated && data?.is_holding && (
        <div className="posture-line calibrating">
          Calibrating your neutral head/neck position…
        </div>
      )}
    </div>
  );
}
