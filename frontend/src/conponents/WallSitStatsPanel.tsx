import type { WallSitData } from "../hooks/useWallSitSocket";

interface Props {
  data: WallSitData | undefined;
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

export default function WallSitStatsPanel({ data }: Props) {
  const state = data?.hold_state ?? "not_started";
  const quality = data?.hold_quality;

  return (
    <div className="arm-panel wallsit-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">WALL SIT</span>
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

      <div className={`wallsit-timer wallsit-timer--${state}`}>
        <div className="wallsit-timer-value">
          {formatSeconds(data?.hold_seconds)}
        </div>
        {data?.target_seconds != null && (
          <div className="wallsit-timer-target">
            / {formatSeconds(data.target_seconds)}
          </div>
        )}
      </div>

      <div className="wallsit-state-row">
        <span className={`stage-badge ${state === "holding" ? "up" : "down"}`}>
          {STATE_LABEL[state]}
        </span>
        {data?.legs_tracked && (
          <span className="wallsit-side-pill">{data.legs_tracked} legs</span>
        )}
      </div>

      {data?.target_seconds != null && (
        <div className="wallsit-progress-track">
          <div
            className="wallsit-progress-fill"
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
          <span className="k">Knee angle</span>
          <span className="v">
            {data?.knee_angle != null ? `${data.knee_angle.toFixed(1)}°` : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Back-to-wall lean</span>
          <span className="v">
            {data?.torso_lean_angle != null
              ? `${data.torso_lean_angle.toFixed(1)}°`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Knees over ankles</span>
          <span className="v">
            {data?.shin_angle != null ? `${data.shin_angle.toFixed(1)}°` : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Slide depth</span>
          <span className="v">
            {data?.hip_drop_fraction != null
              ? `${Math.round(data.hip_drop_fraction * 100)}%`
              : "Calibrating…"}
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
          : "Position: good — facing camera, full body in frame"}
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
