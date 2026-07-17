import type { DeadBugData } from "../hooks/useDeadBugSocket";
import AngleGauge from "./AngleGauge";

interface Props {
  data: DeadBugData | undefined;
}

// Mirrors dead_bug.py's ARM_BENT_THRESHOLD / ARM_STRAIGHT_MIN and
// LEG_BENT_THRESHOLD / LEG_EXTENDED_MIN — kept here purely for the gauge's
// visual zones, the backend is the source of truth for what actually
// counts as "extended".
const ARM_BENT = 110;
const ARM_STRAIGHT = 150;
const LEG_BENT = 110;
const LEG_EXTENDED = 150;

const ISSUE_LABELS: Record<string, string> = {
  arched_back: "Lower back lifting off the floor",
  leg_too_low: "Leg dropping too low",
  arm_not_straight: "Reaching arm not straight",
};

function sideLabel(side: DeadBugData["active_side"]): string {
  if (side === "right_arm_left_leg") return "Right arm + Left leg";
  if (side === "left_arm_right_leg") return "Left arm + Right leg";
  return "—";
}

export default function DeadBugStatsPanel({ data }: Props) {
  const quality = data?.rep_form_quality;
  const activeSide = data?.active_side ?? null;
  const rightPairActive = activeSide === "right_arm_left_leg";
  const leftPairActive = activeSide === "left_arm_right_leg";

  return (
    <div className="arm-panel deadbug-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">DEAD BUG</span>
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
          className={`stage-badge ${data?.phase === "rep_complete" ? "up" : "down"}`}
        >
          {data?.phase === "rep_complete"
            ? "REP COMPLETE"
            : activeSide
              ? "EXTENDING"
              : "START POSITION"}
        </span>
      </div>

      <div className="deadbug-active-side">
        Active side: <strong>{sideLabel(activeSide)}</strong>
      </div>

      <div className="deadbug-pairs">
        <div className={`deadbug-pair ${rightPairActive ? "active" : ""}`}>
          <div className="deadbug-pair-title">Right arm ↔ Left leg</div>
          <div className="deadbug-pair-gauges">
            <div className="deadbug-gauge-block">
              <span className="k">Right arm</span>
              <AngleGauge
                angle={data?.right_arm_angle ?? null}
                upThreshold={ARM_BENT}
                downThreshold={ARM_STRAIGHT}
                stage={rightPairActive ? "up" : "down"}
                compact
              />
              <span className="v">
                {data?.right_arm_angle != null
                  ? `${data.right_arm_angle.toFixed(0)}°`
                  : "—"}
              </span>
            </div>
            <div className="deadbug-gauge-block">
              <span className="k">Left leg</span>
              <AngleGauge
                angle={data?.left_leg_angle ?? null}
                upThreshold={LEG_BENT}
                downThreshold={LEG_EXTENDED}
                stage={rightPairActive ? "up" : "down"}
                compact
              />
              <span className="v">
                {data?.left_leg_angle != null
                  ? `${data.left_leg_angle.toFixed(0)}°`
                  : "—"}
              </span>
            </div>
          </div>
        </div>

        <div className={`deadbug-pair ${leftPairActive ? "active" : ""}`}>
          <div className="deadbug-pair-title">Left arm ↔ Right leg</div>
          <div className="deadbug-pair-gauges">
            <div className="deadbug-gauge-block">
              <span className="k">Left arm</span>
              <AngleGauge
                angle={data?.left_arm_angle ?? null}
                upThreshold={ARM_BENT}
                downThreshold={ARM_STRAIGHT}
                stage={leftPairActive ? "up" : "down"}
                compact
              />
              <span className="v">
                {data?.left_arm_angle != null
                  ? `${data.left_arm_angle.toFixed(0)}°`
                  : "—"}
              </span>
            </div>
            <div className="deadbug-gauge-block">
              <span className="k">Right leg</span>
              <AngleGauge
                angle={data?.right_leg_angle ?? null}
                upThreshold={LEG_BENT}
                downThreshold={LEG_EXTENDED}
                stage={leftPairActive ? "up" : "down"}
                compact
              />
              <span className="v">
                {data?.right_leg_angle != null
                  ? `${data.right_leg_angle.toFixed(0)}°`
                  : "—"}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Good / Flawed</span>
          <span className="v">
            {data?.good_reps ?? 0} / {data?.flawed_reps ?? 0}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Too shallow</span>
          <span className="v">{data?.not_counted_incomplete ?? 0}</span>
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
              ? data.rep_classification.replace(/_/g, " ")
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Set</span>
          <span className="v">
            {data?.set_number ?? 1} / {data?.target_sets ?? 1}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Calibration</span>
          <span className="v">
            {data?.calibrated ? "Ready" : "Calibrating…"}
          </span>
        </div>
      </div>

      <div className={`quality-badge ${quality ?? ""}`}>
        {quality ? quality.replace(/_/g, " ") : "form: —"}
      </div>

      <div
        className={`posture-line ${data?.framing_ok === false ? "bad" : "ok"}`}
      >
        {data?.framing_ok === false && data.framing_message
          ? data.framing_message
          : "Framing: good — full body visible from the side"}
      </div>

      <div
        className={`posture-line ${data?.posture_ok === false ? "bad" : "ok"}`}
      >
        {data?.posture_ok === false && data.posture_issues.length > 0
          ? (data.posture_messages[0] ??
            data.posture_issues.map((i) => ISSUE_LABELS[i] ?? i).join(", "))
          : data?.calibrated
            ? "Core brace looks good"
            : "Hold your start position — calibrating your baseline…"}
      </div>
    </div>
  );
}
