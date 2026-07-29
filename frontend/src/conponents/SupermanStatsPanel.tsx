import type { SupermanData } from "../hooks/useSupermanSocket";

interface Props {
  data: SupermanData | undefined;
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

function viewLabel(view: SupermanData["view_mode"]): string {
  switch (view) {
    case "side":
      return "Side view";
    case "front":
      return "Front view (unsupported)";
    case "angled":
      return "Angled view";
    default:
      return "—";
  }
}

export default function SupermanStatsPanel({ data }: Props) {
  const state = data?.hold_state ?? "not_started";
  const quality = data?.hold_quality;

  return (
    <div className="arm-panel superman-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">SUPERMAN HOLD</span>
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

      <div className={`superman-timer superman-timer--${state}`}>
        <div className="superman-timer-value">
          {formatSeconds(data?.hold_seconds)}
        </div>
        {data?.target_seconds != null && (
          <div className="superman-timer-target">
            / {formatSeconds(data.target_seconds)}
          </div>
        )}
      </div>

      <div className="superman-state-row">
        <span className={`stage-badge ${state === "holding" ? "up" : "down"}`}>
          {STATE_LABEL[state]}
        </span>
        {data?.view_mode && (
          <span className="superman-view-pill">
            {viewLabel(data.view_mode)}
          </span>
        )}
      </div>

      {data?.target_seconds != null && (
        <div className="superman-progress-track">
          <div
            className="superman-progress-fill"
            style={{
              width: `${Math.min(100, ((data.hold_seconds ?? 0) / data.target_seconds) * 100)}%`,
            }}
          />
        </div>
      )}

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Current streak</span>
          <span className="v">
            {formatSeconds(data?.current_streak_seconds)}
          </span>
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
            {formatSeconds(data?.good_seconds)} /{" "}
            {formatSeconds(data?.flawed_seconds)}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Chest rise</span>
          <span className="v">
            {data?.chest_rise != null ? data.chest_rise.toFixed(2) : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Leg rise</span>
          <span className="v">
            {data?.leg_rise != null ? data.leg_rise.toFixed(2) : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Lift depth</span>
          <span className="v">
            {data?.smoothed_lift != null ? data.smoothed_lift.toFixed(2) : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Arm extension</span>
          <span className="v">
            {data?.elbow_angle != null
              ? `${data.elbow_angle.toFixed(1)}°`
              : "—"}
          </span>
        </div>
      </div>

      <div className="arm-grid" style={{ marginTop: 4 }}>
        <div className="arm-grid-item">
          <span className="k">Form score</span>
          <span className="v">
            {data?.form_score != null
              ? data.form_score
              : (data?.avg_form_score ?? "—")}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Avg form</span>
          <span className="v">{data?.avg_form_score ?? "—"}</span>
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
          : "Position: good — side-on, lying flat, full body in frame"}
      </div>

      <div
        className={`posture-line ${data?.posture_ok === false ? "bad" : "ok"}`}
      >
        {data?.posture_ok === false && data.posture_issues.length > 0
          ? (data.posture_messages[0] ??
            data.posture_issues.join(", ").replace(/_/g, " "))
          : "Form looks good"}
      </div>
    </div>
  );
}
