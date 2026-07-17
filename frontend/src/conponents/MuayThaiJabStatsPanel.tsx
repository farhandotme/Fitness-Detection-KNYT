import type { JabData } from "../hooks/useMuayThaiJabSocket";
import AngleGauge from "./AngleGauge";

interface Props {
  data: JabData | undefined;
}

// Mirrors muay_thai_jab.py's GUARD_ELBOW_ANGLE / PUNCH_ELBOW_ANGLE exactly —
// the gauge should show the same guard/punch band the backend is actually
// gating on, not an approximation.
const GUARD_ELBOW_ANGLE = 85;
const PUNCH_ELBOW_ANGLE = 150;

const PHASE_LABEL: Record<string, string> = {
  guard: "GUARD",
  left_punch: "LEFT JAB",
  right_punch: "RIGHT JAB",
  both_punching: "BOTH HANDS",
  rep_complete: "JAB LANDED",
};

const TEMPO_LABEL: Record<string, string> = {
  too_fast: "Too fast (uncontrolled)",
  fast: "Fast",
  good: "Good",
  slow: "Slow",
  too_slow: "Too slow (telegraphed)",
};

function formatIssue(issue: string) {
  return issue.replace(/_/g, " ");
}

export default function MuayThaiJabStatsPanel({ data }: Props) {
  const quality = data?.rep_form_quality;
  const punchingHand = data?.punching_hand;
  const stage = data?.stage ?? "guard";
  const stageClass = stage === "guard" ? "down" : "up";
  const stageLabel = PHASE_LABEL[stage] ?? stage.toUpperCase();

  const hasPose = Boolean(data?.pose_detected);
  const isUnstable = Boolean(data?.low_visibility);
  const framingBad = data?.framing_ok === false;
  const postureBad = data?.posture_ok === false;

  // Whichever hand is actually doing something is what the gauge should
  // track; idle between punches, show whichever elbow is currently more
  // extended (most likely to be mid-recovery / about to lead).
  const displayAngle =
    punchingHand === "left"
      ? data?.left_elbow_angle
      : punchingHand === "right"
        ? data?.right_elbow_angle
        : punchingHand === "both"
          ? Math.max(data?.left_elbow_angle ?? 0, data?.right_elbow_angle ?? 0)
          : (data?.left_elbow_angle ?? data?.right_elbow_angle ?? null);

  const guardDropped = data?.posture_issues.includes("dropped_guard") ?? false;
  const overreaching = data?.posture_issues.includes("overreaching") ?? false;

  return (
    <div className="arm-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">MUAY THAI JAB</span>
        <span
          className={`pose-pill ${hasPose ? (isUnstable ? "warn" : "ok") : "bad"}`}
        >
          {hasPose ? (isUnstable ? "Unstable" : "Tracking") : "No pose"}
        </span>
      </div>

      <div className="arm-panel-rep-row">
        <span className="arm-panel-rep-count">{data?.rep_count ?? 0}</span>
        <span className={`stage-badge ${stageClass}`}>{stageLabel}</span>
      </div>

      <AngleGauge
        angle={displayAngle ?? null}
        upThreshold={PUNCH_ELBOW_ANGLE}
        downThreshold={GUARD_ELBOW_ANGLE}
        stage={stageClass}
      />

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Left elbow</span>
          <span className="v">
            {data?.left_elbow_angle != null
              ? `${data.left_elbow_angle.toFixed(1)}°`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Right elbow</span>
          <span className="v">
            {data?.right_elbow_angle != null
              ? `${data.right_elbow_angle.toFixed(1)}°`
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
          <span className="k">Half jabs</span>
          <span className="v">{data?.partial_rep_count ?? 0}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Last jab</span>
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
              ? (TEMPO_LABEL[data.rep_classification] ??
                data.rep_classification.replace("_", " "))
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Punch speed</span>
          <span className="v">
            {data?.rep_avg_speed != null ? `${data.rep_avg_speed}°/s` : "—"}
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
        {quality ? formatIssue(quality) : "form: —"}
      </div>

      {/* This is the single most important number on this exercise: the
          backend only counts a jab if the hand genuinely launched from —
          and returned to — guard. Rejected "no guard" attempts are its own
          counter, separate from flawed reps, so surface it as its own
          line rather than folding it into "flawed". */}
      <div
        className={`posture-line ${(data?.not_counted_no_guard ?? 0) > 0 ? "bad" : "ok"}`}
      >
        {(data?.not_counted_no_guard ?? 0) > 0
          ? `${data?.not_counted_no_guard} punch${data?.not_counted_no_guard === 1 ? "" : "es"} not counted — thrown or returned outside your guard`
          : "Every punch has launched from a real guard"}
      </div>

      <div className={`posture-line ${framingBad ? "bad" : "ok"}`}>
        {framingBad && data?.framing_message
          ? data.framing_message
          : "Position: good — guard and full extension fit in frame"}
      </div>

      <div className={`posture-line ${guardDropped ? "bad" : "ok"}`}>
        {guardDropped
          ? (data?.posture_messages.find((_m) => true) ??
            "Keep your other hand up guarding your chin.")
          : "Off-hand guard: up and covering"}
      </div>

      <div className={`posture-line ${overreaching ? "bad" : "ok"}`}>
        {overreaching
          ? "Extend your arm, not your whole body — don't lunge into the punch."
          : "Stance: balanced, not lunging"}
      </div>

      <div className={`posture-line ${postureBad ? "bad" : "ok"}`}>
        {data?.calibrated
          ? postureBad
            ? "Form needs a correction — see above"
            : "Overall form looks good"
          : "Hold your guard still — calibrating your baseline…"}
      </div>
    </div>
  );
}
