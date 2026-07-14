import type { JumpingJackData } from "../hooks/useJumpingJackSocket";
import OpennessGauge from "./OpennessGauge";

interface Props {
  data: JumpingJackData | undefined;
}

const OPENNESS_CLOSED_THRESH = 22;
const OPENNESS_OPEN_THRESH = 72;

const PHASE_LABEL: Record<string, string> = {
  start: "READY",
  open: "OPENING",
  close: "CLOSING",
  rep_complete: "REP!",
};

function scoreBar(label: string, score: number | null, avg: number | null) {
  return (
    <div className="jj-score-row">
      <span className="jj-score-label">{label}</span>
      <div className="jj-score-track">
        <div
          className="jj-score-fill"
          style={{ width: `${score ?? avg ?? 0}%` }}
        />
      </div>
      <span className="jj-score-value">
        {score != null ? score : avg != null ? avg : "—"}
      </span>
    </div>
  );
}

export default function JumpingJackStatsPanel({ data }: Props) {
  const openness = data?.smoothed_openness ?? data?.openness ?? null;
  const quality = data?.rep_form_quality;
  const phase = data?.phase ?? "start";

  return (
    <div className="arm-panel jj-panel">
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
        <span
          className={`stage-badge ${data?.stage === "open" ? "up" : "down"}`}
        >
          {PHASE_LABEL[phase] ?? (data?.stage === "open" ? "OPEN" : "CLOSED")}
        </span>
      </div>

      <OpennessGauge
        value={openness}
        openThreshold={OPENNESS_OPEN_THRESH}
        closedThreshold={OPENNESS_CLOSED_THRESH}
        stage={data?.stage ?? "closed"}
      />

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Openness</span>
          <span className="v">
            {openness != null ? `${openness.toFixed(0)}/100` : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Velocity</span>
          <span className="v">
            {data?.openness_velocity != null
              ? `${data.openness_velocity.toFixed(0)}/s`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Arms L / R</span>
          <span className="v">
            {data?.arm_angle_left != null
              ? `${data.arm_angle_left.toFixed(0)}°`
              : "—"}{" "}
            /{" "}
            {data?.arm_angle_right != null
              ? `${data.arm_angle_right.toFixed(0)}°`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Leg spread</span>
          <span className="v">
            {data?.leg_spread_ratio != null
              ? data.leg_spread_ratio.toFixed(2)
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
          <span className="k">Half reps</span>
          <span className="v">{data?.partial_rep_count ?? 0}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Last rep</span>
          <span className="v">
            {data?.rep_duration != null
              ? `${data.rep_duration.toFixed(2)}s`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Tempo</span>
          <span className="v">
            {data?.rep_classification
              ? data.rep_classification.replace("_", " ")
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Pace</span>
          <span className="v">
            {data?.speed_analysis?.reps_per_minute != null
              ? `${data.speed_analysis.reps_per_minute}/min`
              : "—"}
          </span>
        </div>
      </div>

      <div className="jj-scores">
        {scoreBar(
          "Form",
          data?.form_score ?? null,
          data?.avg_form_score ?? null,
        )}
        {scoreBar(
          "Range of motion",
          data?.rom_score ?? null,
          data?.avg_rom_score ?? null,
        )}
        {scoreBar(
          "Stability",
          data?.stability_score ?? null,
          data?.avg_stability_score ?? null,
        )}
        {scoreBar(
          "L/R sync",
          data?.sync_score ?? null,
          data?.avg_sync_score ?? null,
        )}
      </div>

      <div className={`quality-badge ${quality ?? ""}`}>
        {quality ? quality.replace("_", " ") : "form: —"}
      </div>

      <div
        className={`posture-line ${data?.framing_ok === false ? "bad" : "ok"}`}
      >
        {data?.framing_ok === false && data.framing_message
          ? data.framing_message
          : "Position: good — full body in frame, centered"}
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
