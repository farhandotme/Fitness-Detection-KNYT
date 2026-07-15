import type { PlankHoldData } from "../hooks/usePlankHoldSocket";

interface Props {
  data: PlankHoldData | undefined;
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

export default function PlankHoldStatsPanel({ data }: Props) {
  const state = data?.hold_state ?? "not_started";
  const quality = data?.hold_quality;

  return (
    <div className="arm-panel plank-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">PLANK HOLD</span>
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

      <div className={`plank-timer plank-timer--${state}`}>
        <div className="plank-timer-value">
          {formatSeconds(data?.hold_seconds)}
        </div>
        {data?.target_seconds != null && (
          <div className="plank-timer-target">
            / {formatSeconds(data.target_seconds)}
          </div>
        )}
      </div>

      <div className="plank-state-row">
        <span className={`stage-badge ${state === "holding" ? "up" : "down"}`}>
          {STATE_LABEL[state]}
        </span>
        {data?.active_side && (
          <span className="plank-side-pill">{data.active_side} side</span>
        )}
      </div>

      {data?.target_seconds != null && (
        <div className="plank-progress-track">
          <div
            className="plank-progress-fill"
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
          <span className="k">Alignment</span>
          <span className="v">
            {data?.alignment_angle != null
              ? `${data.alignment_angle.toFixed(1)}°`
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
          <span className="k">Head angle</span>
          <span className="v">
            {data?.head_angle != null ? `${data.head_angle.toFixed(1)}°` : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Calibration</span>
          <span className="v">
            {data?.calibrated ? "Ready" : "Calibrating…"}
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
          : "Position: good — side-on, full body in frame"}
      </div>

      <div
        className={`posture-line ${data?.posture_ok === false ? "bad" : "ok"}`}
      >
        {data?.posture_ok === false && data.posture_issues.length > 0
          ? (data.posture_messages[0] ??
            data.posture_issues.join(", ").replace(/_/g, " "))
          : data?.calibrated
            ? "Posture looks good"
            : "Calibrating your form baseline…"}
      </div>
    </div>
  );
}
