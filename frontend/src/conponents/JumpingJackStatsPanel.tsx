import type { JumpingJackData } from "../hooks/useJumpingJackSocket";

interface Props {
  data: JumpingJackData | undefined;
}

// Same open/close lines the backend uses — kept in sync so the two bars
// on screen actually match when the rep counts.
const ARM_CLOSE = -0.05;
const ARM_OPEN = 0.2;
const ARM_FULL = 0.35;

const LEG_CLOSE = 1.3;
const LEG_OPEN = 1.7;
const LEG_FULL = 2.0;

function toPct(value: number | null | undefined, lo: number, hi: number): number {
  if (value == null) return 0;
  const pct = ((value - lo) / (hi - lo)) * 100;
  return Math.max(0, Math.min(100, pct));
}

export default function JumpingJackStatsPanel({ data }: Props) {
  const arm = data?.smoothed_arm_raise ?? data?.arm_raise ?? null;
  const leg = data?.smoothed_leg_spread_ratio ?? data?.leg_spread_ratio ?? null;
  const quality = data?.rep_form_quality;

  const armPct = toPct(arm, ARM_CLOSE, ARM_FULL);
  const legPct = toPct(leg, LEG_CLOSE, LEG_FULL);

  return (
    <div className="arm-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">JUMPING JACKS</span>
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
        <span className={`stage-badge ${data?.stage ?? "closed"}`}>
          {(data?.stage ?? "closed") === "open" ? "OPEN" : "CLOSED"}
        </span>
      </div>

      <div className="jj-bar-group">
        <div className="jj-bar-row">
          <span className="jj-bar-label">Arms up</span>
          <div className="jj-bar-track">
            <div className="jj-bar-fill jj-bar-arms" style={{ width: `${armPct}%` }} />
          </div>
        </div>
        <div className="jj-bar-row">
          <span className="jj-bar-label">Feet apart</span>
          <div className="jj-bar-track">
            <div className="jj-bar-fill jj-bar-legs" style={{ width: `${legPct}%` }} />
          </div>
        </div>
      </div>

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Good / Needs work</span>
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
          <span className="k">Pace</span>
          <span className="v">
            {data?.rep_classification ? data.rep_classification.replace("_", " ") : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Elapsed</span>
          <span className="v">{(data?.elapsed_time ?? 0).toFixed(0)}s</span>
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
          ? "Tracking locked in — counting reps"
          : (data?.position_message ?? "Getting a steady lock on your position…")}
      </div>
    </div>
  );
}
