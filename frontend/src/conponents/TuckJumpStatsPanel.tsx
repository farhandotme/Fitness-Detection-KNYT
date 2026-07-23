import type { TuckJumpData } from "../hooks/useTuckJumpSocket";

interface Props {
  data: TuckJumpData | undefined;
}

/** 180deg (standing) -> 0deg (max tuck), rendered as a fill percentage. */
function tuckFillPct(angle: number | null): number {
  if (angle == null) return 0;
  const pct = ((180 - angle) / 180) * 100;
  return Math.max(0, Math.min(100, pct));
}

function hipRisePct(rise: number | null): number {
  if (rise == null) return 0;
  return Math.max(0, Math.min(100, (rise / 0.3) * 100));
}

export default function TuckJumpStatsPanel({ data }: Props) {
  const angle = data?.smoothed_tuck_angle ?? data?.tuck_angle ?? null;
  const quality = data?.rep_form_quality;

  return (
    <div className="tj-panel">
      <div className="tj-panel-head">
        <span className="tj-panel-label">TUCK JUMP</span>
        <span
          className={`tj-pose-pill ${data?.pose_detected ? (data.low_visibility ? "warn" : "ok") : "bad"}`}
        >
          {data?.pose_detected
            ? data.low_visibility
              ? "Unstable"
              : "Tracking"
            : "No pose"}
        </span>
      </div>

      <div className="tj-rep-row">
        <span className="tj-rep-count">{data?.rep_count ?? 0}</span>
        <span className={`tj-stage-badge ${data?.stage ?? "down"}`}>
          {(data?.stage ?? "down") === "up" ? "TUCKED" : "STANDING"}
        </span>
        {data?.airborne && <span className="tj-airborne-badge">AIRBORNE</span>}
      </div>

      <div className="tj-gauge">
        <div className="tj-gauge-row">
          <span className="tj-gauge-label">Knee tuck</span>
          <div className="tj-gauge-track">
            <div
              className="tj-gauge-fill tuck"
              style={{ width: `${tuckFillPct(angle)}%` }}
            />
          </div>
        </div>
        <div className="tj-gauge-row">
          <span className="tj-gauge-label">Jump height</span>
          <div className="tj-gauge-track">
            <div
              className="tj-gauge-fill rise"
              style={{ width: `${hipRisePct(data?.hip_rise ?? null)}%` }}
            />
          </div>
        </div>
      </div>

      <div className="tj-grid">
        <div className="tj-grid-item">
          <span className="k">Tuck angle</span>
          <span className="v">
            {angle != null ? `${angle.toFixed(0)}°` : "—"}
          </span>
        </div>
        <div className="tj-grid-item">
          <span className="k">Good / Flawed</span>
          <span className="v">
            {data?.good_reps ?? 0} / {data?.flawed_reps ?? 0}
          </span>
        </div>
        <div className="tj-grid-item">
          <span className="k">Last rep</span>
          <span className="v">
            {data?.rep_duration != null
              ? `${data.rep_duration.toFixed(2)}s`
              : "—"}
          </span>
        </div>
        <div className="tj-grid-item">
          <span className="k">Tempo</span>
          <span className="v">
            {data?.rep_classification
              ? data.rep_classification.replace("_", " ")
              : "—"}
          </span>
        </div>
        <div className="tj-grid-item">
          <span className="k">No jump</span>
          <span className="v">{data?.no_jump_count ?? 0}</span>
        </div>
        <div className="tj-grid-item">
          <span className="k">No tuck</span>
          <span className="v">{data?.no_tuck_count ?? 0}</span>
        </div>
      </div>

      <div className={`tj-quality-badge ${quality ?? ""}`}>
        {quality ? quality.replace("_", " ") : "form: —"}
      </div>

      <div
        className={`tj-posture-line ${data?.framing_ok === false ? "bad" : "ok"}`}
      >
        {data?.framing_ok === false && data.framing_message
          ? data.framing_message
          : "Framing: good — full body visible in shot"}
      </div>

      <div className={`tj-posture-line ${data?.ready ? "ok" : "bad"}`}>
        {data?.ready
          ? "Standing position confirmed — counting reps"
          : `Calibrating — hold a tall standing position (${Math.round((data?.calibration_progress ?? 0) * 100)}%)`}
      </div>
    </div>
  );
}
