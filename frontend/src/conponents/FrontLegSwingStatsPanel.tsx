import type { FrontLegSwingData } from "../hooks/useFrontLegSwingSocket";

interface Props {
  data: FrontLegSwingData | undefined;
}

function viewLabel(view: FrontLegSwingData["view_mode"]): string {
  switch (view) {
    case "side":
      return "Side view";
    case "front":
      return "Front view";
    case "angled":
      return "Angled view";
    default:
      return "—";
  }
}

function legLabel(leg: FrontLegSwingData["active_leg"]): string {
  if (leg === "left") return "Left leg";
  if (leg === "right") return "Right leg";
  return "—";
}

export default function FrontLegSwingStatsPanel({ data }: Props) {
  const angle = data?.swing_angle ?? null;
  const quality = data?.rep_form_quality;
  const pct = angle == null ? 0 : Math.max(0, Math.min(100, (angle / 65) * 100));

  return (
    <div className="arm-panel frontswing-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">FRONT LEG SWING</span>
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
        <span className="arm-panel-rep-count">{data?.rep_count ?? 0}</span>
        <span className={`stage-badge ${data?.stage === "out" ? "down" : "up"}`}>
          {data?.stage === "out" ? "SWINGING" : "RESTING"}
        </span>
      </div>

      <div className="frontswing-gauge">
        <div className="frontswing-gauge-track">
          <div
            className={`frontswing-gauge-fill ${data?.stage === "out" ? "down" : "up"}`}
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="frontswing-gauge-labels">
          <span>Resting</span>
          <span>Swing height</span>
        </div>
      </div>

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Working leg</span>
          <span className="v">{legLabel(data?.active_leg ?? null)}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Swing angle</span>
          <span className="v">{angle != null ? `${angle.toFixed(1)}°` : "—"}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Stance knee</span>
          <span className="v">
            {data?.stance_knee_angle != null
              ? `${data.stance_knee_angle.toFixed(1)}°`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Swing knee</span>
          <span className="v">
            {data?.swing_knee_angle != null
              ? `${data.swing_knee_angle.toFixed(1)}°`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Foot lift</span>
          <span className="v">
            {data?.foot_lift_ratio != null
              ? `${(data.foot_lift_ratio * 100).toFixed(0)}%`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Good / Flawed</span>
          <span className="v">
            {data?.good_reps ?? 0} / {data?.flawed_reps ?? 0}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Last rep</span>
          <span className="v">
            {data?.rep_duration != null ? `${data.rep_duration.toFixed(2)}s` : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Camera</span>
          <span className="v">{viewLabel(data?.view_mode ?? null)}</span>
        </div>
      </div>

      <div className={`quality-badge ${quality ?? ""}`}>
        {quality ? quality.replace("_", " ") : "form: —"}
      </div>

      <div className={`posture-line ${data?.framing_ok === false ? "bad" : "ok"}`}>
        {data?.framing_ok === false && data.framing_message
          ? data.framing_message
          : "Framing: good — full body visible in shot"}
      </div>

      <div className={`posture-line ${data?.position_ok ? "ok" : "bad"}`}>
        {data?.position_ok
          ? "Side-on position confirmed — counting reps"
          : (data?.position_message ?? "Waiting for a confirmed side-on position…")}
      </div>

      <div
        className={`posture-line ${data?.stage === "out" && data?.foot_lifted === false ? "bad" : "ok"}`}
      >
        {data?.stage === "out" && data?.foot_lifted === false
          ? "Foot still on the ground — lift it clear before swinging"
          : "Foot lift: confirmed off the ground"}
      </div>

      <div className={`posture-line ${data?.torso_upright_ok === false ? "bad" : "ok"}`}>
        {data?.torso_upright_ok === false
          ? "Rocking too far — stay upright, don't use momentum"
          : "Torso posture looks upright"}
      </div>
    </div>
  );
}
