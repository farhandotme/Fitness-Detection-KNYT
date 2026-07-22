import type { ChairPoseData } from "../hooks/useChairPoseSocket";

interface Props {
  data: ChairPoseData | undefined;
}

function holdStateLabel(
  state: ChairPoseData["hold_state"] | undefined,
): string {
  switch (state) {
    case "not_started":
      return "Get ready";
    case "holding":
      return "Holding";
    case "broken":
      return "Paused";
    default:
      return "—";
  }
}

function formatSeconds(value: number | undefined): string {
  const s = value ?? 0;
  return `${s.toFixed(1)}s`;
}

export default function ChairPoseStatsPanel({ data }: Props) {
  const holdState = data?.hold_state ?? "not_started";
  const holdSeconds = data?.hold_seconds ?? 0;
  const targetSeconds = data?.target_seconds ?? null;
  const progressPct = targetSeconds
    ? Math.min(100, (holdSeconds / targetSeconds) * 100)
    : 0;

  return (
    <div className="arm-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">CHAIR POSE HOLD</span>
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
        <span className="arm-panel-rep-count">
          {formatSeconds(holdSeconds)}
        </span>
        <span className={`stage-badge ${holdState}`}>
          {holdStateLabel(holdState)}
        </span>
      </div>

      {targetSeconds != null && (
        <>
          <div className="chair-hold-bar">
            <div
              className="chair-hold-bar-fill"
              style={{ width: `${progressPct}%` }}
            />
          </div>
          <div className="arm-panel-caption">
            {formatSeconds(holdSeconds)} / {formatSeconds(targetSeconds)}
          </div>
        </>
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
          <span className="k">Knee angle</span>
          <span className="v">
            {data?.knee_angle != null ? `${data.knee_angle.toFixed(1)}°` : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Hip angle</span>
          <span className="v">
            {data?.hip_angle != null ? `${data.hip_angle.toFixed(1)}°` : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Torso lean</span>
          <span className="v">
            {data?.torso_angle != null
              ? `${data.torso_angle.toFixed(1)}°`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Breaks</span>
          <span className="v">{data?.break_count ?? 0}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Form score</span>
          <span className="v">
            {data?.form_score != null ? `${data.form_score}` : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Avg form score</span>
          <span className="v">
            {data?.avg_form_score != null ? `${data.avg_form_score}` : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Confidence</span>
          <span className="v">
            {data?.confidence != null ? `${data.confidence}%` : "—"}
          </span>
        </div>
      </div>

      <div
        className={`posture-line ${data?.framing_ok === false ? "bad" : "ok"}`}
      >
        {data?.framing_ok === false && data.framing_message
          ? data.framing_message
          : "Framing: good — full body visible in shot"}
      </div>

      <div className={`posture-line ${data?.arms_ok === false ? "bad" : "ok"}`}>
        {data?.arms_ok === false && data.arms_message
          ? data.arms_message
          : "Arms: good position"}
      </div>

      {(data?.posture_messages?.length ?? 0) > 0 && (
        <div className="posture-line bad">{data!.posture_messages[0]}</div>
      )}

      <div className="posture-line ok">{data?.feedback ?? "—"}</div>
    </div>
  );
}
