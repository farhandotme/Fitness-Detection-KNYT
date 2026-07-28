import type { DancerPoseData } from "../hooks/useDancerPoseSocket";

interface Props {
  data: DancerPoseData | undefined;
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

const SUPPORT_LABEL: Record<string, string> = {
  free: "Free-standing",
  wall: "Wall-supported",
  strap: "Strap-assisted",
};

export default function DancerPoseStatsPanel({ data }: Props) {
  const state = data?.hold_state ?? "not_started";
  const quality = data?.hold_quality;

  return (
    <div className="arm-panel dancer-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">DANCER POSE</span>
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

      <div className={`dancer-timer dancer-timer--${state}`}>
        <div className="dancer-timer-value">
          {formatSeconds(data?.hold_seconds)}
        </div>
        {data?.target_seconds != null && (
          <div className="dancer-timer-target">
            / {formatSeconds(data.target_seconds)}
          </div>
        )}
      </div>

      <div className="dancer-state-row">
        <span className={`stage-badge ${state === "holding" ? "up" : "down"}`}>
          {STATE_LABEL[state]}
        </span>
        {data?.standing_side && (
          <span className="dancer-side-pill">
            standing on {data.standing_side}
          </span>
        )}
        {data?.support_mode && (
          <span className="dancer-support-pill">
            {SUPPORT_LABEL[data.support_mode] ?? data.support_mode}
          </span>
        )}
      </div>

      {data?.target_seconds != null && (
        <div className="dancer-progress-track">
          <div
            className="dancer-progress-fill"
            style={{
              width: `${Math.min(100, ((data.hold_seconds ?? 0) / data.target_seconds) * 100)}%`,
            }}
          />
        </div>
      )}

      <div className="dancer-balance">
        <span className="k">Balance confidence</span>
        <div className="dancer-balance-track">
          <div
            className={`dancer-balance-fill ${
              (data?.balance_confidence ?? 100) < 60 ? "low" : ""
            }`}
            style={{ width: `${data?.balance_confidence ?? 0}%` }}
          />
        </div>
        <span className="v">{data?.balance_confidence ?? "—"}%</span>
      </div>

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
          <span className="k">Kick height</span>
          <span className="v">
            {data?.lifted_leg_height != null
              ? data.lifted_leg_height.toFixed(2)
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Back knee bend</span>
          <span className="v">
            {data?.lifted_knee_angle != null
              ? `${data.lifted_knee_angle.toFixed(1)}°`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Front arm reaching</span>
          <span className="v">
            {data?.front_arm_reach_ok ? "Yes" : "Not yet"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Hand-foot connected</span>
          <span className="v">
            {data?.hand_foot_connected ? "Yes" : "Not yet"}
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
          : "Position: good — full body in frame"}
      </div>

      <div
        className={`posture-line ${data?.posture_ok === false ? "bad" : "ok"}`}
      >
        {data?.posture_ok === false && data.posture_issues.length > 0
          ? (data.posture_messages[0] ??
            data.posture_issues.join(", ").replace(/_/g, " "))
          : "Posture looks good"}
      </div>
    </div>
  );
}
