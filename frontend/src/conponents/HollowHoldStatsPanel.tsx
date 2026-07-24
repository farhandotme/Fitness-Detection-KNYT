import type { HollowHoldData } from "../hooks/useHollowHoldSocket";

interface Props {
  data: HollowHoldData | undefined;
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
    case "hip_lift":
      return "Hips lifting off the mat";
    case "knee_bent":
      return "Knees bent";
    case "legs_too_high":
      return "Legs raised too high";
    case "arms_not_overhead":
      return "Arms not fully overhead";
    default:
      return issue.replace(/_/g, " ");
  }
}

export default function HollowHoldStatsPanel({ data }: Props) {
  const quality = data?.hold_quality;
  const issues = data?.posture_issues ?? [];

  return (
    <div className="arm-panel hollow-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">HOLLOW HOLD</span>
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

      <div className="hollow-timer-row">
        <span className="hollow-timer-big">
          {formatSeconds(data?.hold_seconds ?? 0)}
        </span>
        <span
          className={`stage-badge ${data?.is_holding ? "up" : "down"}`}
        >
          {data?.hold_state === "not_started"
            ? "NOT STARTED"
            : data?.is_holding
              ? "HOLDING"
              : "BROKEN"}
        </span>
      </div>

      {data?.target_seconds != null && (
        <div className="hollow-target-caption">
          Target: {formatSeconds(data.target_seconds)} · current streak{" "}
          {formatSeconds(data?.current_streak_seconds ?? 0)}
        </div>
      )}

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Shoulder lift</span>
          <span className="v">
            {data?.shoulder_lift_deg != null
              ? `${data.shoulder_lift_deg.toFixed(1)}°`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Leg lift</span>
          <span className="v">
            {data?.leg_lift_deg != null
              ? `${data.leg_lift_deg.toFixed(1)}°`
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
          <span className="k">Elbow angle</span>
          <span className="v">
            {data?.elbow_angle != null
              ? `${data.elbow_angle.toFixed(1)}°`
              : "—"}
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
          ? "Hollow position confirmed — timer running"
          : (data?.feedback ?? "Waiting for a confirmed hollow hold position…")}
      </div>

      {issues.length > 0 && (
        <div className="posture-line bad">
          {issues.map(issueLabel).join(" · ")}
        </div>
      )}

      {!data?.calibrated && data?.is_holding && (
        <div className="posture-line calibrating">
          Calibrating your resting hip baseline…
        </div>
      )}
    </div>
  );
}
