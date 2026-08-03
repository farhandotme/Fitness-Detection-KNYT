import type { ShoulderStandData } from "../hooks/useShoulderStandSocket";

interface Props {
  data: ShoulderStandData | undefined;
}

function formatTime(seconds: number): string {
  const s = Math.max(0, seconds);
  const m = Math.floor(s / 60);
  const rem = (s % 60).toFixed(1);
  return m > 0 ? `${m}:${rem.padStart(4, "0")}` : `${rem}s`;
}

function stageLabel(stage: ShoulderStandData["stage"]): string {
  switch (stage) {
    case "holding":
      return "HOLDING";
    case "adjusting":
      return "ADJUSTING";
    default:
      return "NOT IN POSE";
  }
}

export default function ShoulderStandStatsPanel({ data }: Props) {
  const target = data?.target_hold_seconds ?? null;
  const holdTime = data?.hold_time ?? 0;
  const progress = target ? Math.min(1, holdTime / target) : 0;

  return (
    <div className="arm-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">SHOULDER STAND</span>
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

      <div className="sstand-timer-row">
        <span className={`sstand-timer ${data?.form_ok ? "active" : ""}`}>
          {formatTime(holdTime)}
        </span>
        <span className={`stage-badge ${data?.stage ?? "not_in_pose"}`}>
          {stageLabel(data?.stage ?? "not_in_pose")}
        </span>
      </div>

      {target != null && (
        <div className="progress-track">
          <div
            className="progress-fill"
            style={{ width: `${progress * 100}%` }}
          />
        </div>
      )}
      {target != null && (
        <div className="progress-caption">
          {formatTime(holdTime)} / {formatTime(target)}
        </div>
      )}

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Best hold</span>
          <span className="v">{formatTime(data?.best_hold_time ?? 0)}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Interruptions</span>
          <span className="v">{data?.interruption_count ?? 0}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Body alignment</span>
          <span className="v">
            {data?.body_alignment_deg != null
              ? `${data.body_alignment_deg.toFixed(0)}°`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Knee angles</span>
          <span className="v">
            {data?.left_knee_angle != null && data?.right_knee_angle != null
              ? `${data.left_knee_angle.toFixed(0)}° / ${data.right_knee_angle.toFixed(0)}°`
              : "—"}
          </span>
        </div>
      </div>

      <div
        className={`quality-badge ${data?.form_ok ? "good" : data?.stage === "adjusting" ? "needs_improvement" : ""}`}
      >
        {data?.form_ok
          ? "form: holding"
          : data?.stage === "adjusting"
            ? "form: adjusting"
            : "form: —"}
      </div>

      <div
        className={`posture-line ${data?.framing_ok === false ? "bad" : "ok"}`}
      >
        {data?.framing_ok === false && data.framing_message
          ? data.framing_message
          : "Framing: good — full body visible in shot"}
      </div>

      <div
        className={`posture-line ${data?.hip_inversion_ok === false && data?.position_ok ? "bad" : "ok"}`}
      >
        {data?.hip_inversion_ok
          ? "Hips inverted above shoulders"
          : "Lift your hips higher above your shoulders"}
      </div>

      <div
        className={`posture-line ${data?.legs_raised_ok === false && data?.position_ok ? "bad" : "ok"}`}
      >
        {data?.legs_raised_ok
          ? "Legs raised well above hips"
          : "Raise your legs further overhead"}
      </div>

      <div
        className={`posture-line ${data?.knee_straight_ok === false && data?.position_ok ? "bad" : "ok"}`}
      >
        {data?.knee_straight_ok
          ? "Legs extended straight"
          : "Straighten your knees"}
      </div>

      <div
        className={`posture-line ${data?.alignment_ok === false && data?.position_ok ? "bad" : "ok"}`}
      >
        {data?.alignment_ok
          ? "Body in one straight vertical line"
          : "Keep shoulders, hips, and legs stacked vertically"}
      </div>

      <div className="sstand-safety-note">
        ⚠️ This checks body alignment only — it can't verify your neck position.
        Keep your chin gently tucked, weight on your shoulders/upper arms (not
        your neck), and come down immediately if you feel any neck strain.
      </div>
    </div>
  );
}
