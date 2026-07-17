import type { LateralRaiseData } from "../hooks/useLateralRaiseSocket";
import AngleGauge from "./AngleGauge";

interface Props {
  data: LateralRaiseData | undefined;
}

const ISSUE_LABEL: Record<string, string> = {
  poor_posture: "Leaning / swinging",
  shrugging: "Shoulders shrugging up",
  elbows_too_bent: "Elbows too bent",
  asymmetric_raise: "Uneven arms",
};

// Mirrors the backend's LateralRaiseAnalyzer constants (lateral_raise.py). The analyzer's
// rep-counting state machine runs on `smoothed_lift`, a 0–100 score, not the raw degree angle —
// so the gauge needs to be driven off the same smoothed score and converted back to degrees
// using these same constants, or it can show a different "up"/"down" moment than what's actually
// being counted.
const REST_ANGLE = 35;
const RAISE_ANGLE = 85;
const LIFT_RAISED_THRESH = 72;
const LIFT_GROUNDED_THRESH = 24;

function liftToAngle(lift: number) {
  return REST_ANGLE + (lift / 100) * (RAISE_ANGLE - REST_ANGLE);
}

const UP_THRESHOLD_DEG = liftToAngle(LIFT_RAISED_THRESH);
const DOWN_THRESHOLD_DEG = liftToAngle(LIFT_GROUNDED_THRESH);

export default function LateralRaiseStatsPanel({ data }: Props) {
  const quality = data?.rep_form_quality;
  const issues = data?.posture_issues ?? [];

  // Prefer the smoothed value (what the backend actually bases counting on) and only fall
  // back to the raw angle if smoothing hasn't kicked in yet (e.g. the very first frame).
  const gaugeAngle =
    data?.smoothed_lift != null
      ? liftToAngle(data.smoothed_lift)
      : (data?.angle ?? null);

  return (
    <div className="arm-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">LATERAL RAISE</span>
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
        <span className={`stage-badge ${data?.stage ?? "down"}`}>
          {(data?.stage ?? "down") === "up" ? "SHOULDER HEIGHT" : "ARMS DOWN"}
        </span>
      </div>

      <AngleGauge
        angle={gaugeAngle}
        upThreshold={UP_THRESHOLD_DEG}
        downThreshold={DOWN_THRESHOLD_DEG}
        stage={data?.stage === "up" ? "up" : "down"}
      />

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Left abduction angle</span>
          <span className="v">
            {data?.left_abduction_angle != null
              ? `${data.left_abduction_angle.toFixed(1)}°`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Right abduction angle</span>
          <span className="v">
            {data?.right_abduction_angle != null
              ? `${data.right_abduction_angle.toFixed(1)}°`
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
          <span className="k">Calibration</span>
          <span className="v">
            {data?.calibrated ? "Ready" : "Calibrating…"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Cadence</span>
          <span className="v">
            {data?.reps_per_minute != null
              ? `${data.reps_per_minute} rpm`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Pace</span>
          <span className="v">
            {data?.pace_classification
              ? data.pace_classification.replace("_", " ")
              : "—"}
          </span>
        </div>
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
          : "Position: good — full arm span in frame, centered"}
      </div>

      {/* Every tracked correction, live — not just a single summary line,
          since the whole point of this exercise is getting all four checks
          right on every rep. */}
      {(
        [
          "poor_posture",
          "shrugging",
          "elbows_too_bent",
          "asymmetric_raise",
        ] as const
      ).map((key) => {
        const active = issues.includes(key);
        return (
          <div key={key} className={`posture-line ${active ? "bad" : "ok"}`}>
            {active
              ? (data?.posture_messages.find((_m, i) => issues[i] === key) ??
                ISSUE_LABEL[key])
              : `${ISSUE_LABEL[key]}: looks good`}
          </div>
        );
      })}
    </div>
  );
}
