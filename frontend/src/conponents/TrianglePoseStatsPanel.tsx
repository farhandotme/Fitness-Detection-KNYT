import type { TrianglePoseData } from "../hooks/useTrianglePoseSocket";

interface Props {
  data: TrianglePoseData | undefined;
}

function formatSeconds(s: number): string {
  const total = Math.max(0, s);
  const m = Math.floor(total / 60);
  const sec = total - m * 60;
  if (m > 0) return `${m}:${sec.toFixed(0).padStart(2, "0")}`;
  return `${sec.toFixed(1)}s`;
}

function sideLabel(side: TrianglePoseData["active_side"]): string {
  if (side === "left") return "Left leg forward";
  if (side === "right") return "Right leg forward";
  return "—";
}

export default function TrianglePoseStatsPanel({ data }: Props) {
  const quality = data?.hold_quality;
  const holdState = data?.hold_state ?? "not_started";

  return (
    <div className="tri-panel">
      <div className="tri-panel-head">
        <span className="tri-panel-label">TRIANGLE POSE</span>
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

      <div className="tri-timer-row">
        <span className="tri-timer">{formatSeconds(data?.hold_seconds ?? 0)}</span>
        <span className={`stage-badge ${holdState === "holding" ? "down" : "up"}`}>
          {holdState === "holding"
            ? "HOLDING"
            : holdState === "broken"
              ? "PAUSED"
              : "NOT STARTED"}
        </span>
      </div>

      <div className="tri-side-row">
        <span>{sideLabel(data?.active_side ?? null)}</span>
        {data?.expected_side && (
          <span
            className={`side-badge ${data.side_matches ? "ok" : "bad"}`}
          >
            target: {data.expected_side}
          </span>
        )}
      </div>

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Front knee</span>
          <span className="v">
            {data?.front_knee_angle != null
              ? `${data.front_knee_angle.toFixed(0)}°`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Back knee</span>
          <span className="v">
            {data?.back_knee_angle != null
              ? `${data.back_knee_angle.toFixed(0)}°`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Torso tilt</span>
          <span className="v">
            {data?.torso_tilt_angle != null
              ? `${data.torso_tilt_angle.toFixed(0)}°`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Stance width</span>
          <span className="v">
            {data?.stance_ratio != null ? `${data.stance_ratio.toFixed(2)}x` : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Current streak</span>
          <span className="v">
            {formatSeconds(data?.current_streak_seconds ?? 0)}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Best streak</span>
          <span className="v">{formatSeconds(data?.best_streak_seconds ?? 0)}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Breaks</span>
          <span className="v">{data?.break_count ?? 0}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Form score</span>
          <span className="v">
            {data?.avg_form_score != null ? `${data.avg_form_score}` : "—"}
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
          ? "Triangle Pose confirmed — timer running"
          : "Waiting for a confirmed Triangle Pose…"}
      </div>

      {data?.posture_messages && data.posture_messages.length > 0 && (
        <div className="posture-line bad">{data.posture_messages[0]}</div>
      )}
    </div>
  );
}
