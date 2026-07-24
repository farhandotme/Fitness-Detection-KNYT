import type { WindmillData } from "../hooks/useWindMillRotationStretch";

interface Props {
  result: WindmillData;
  lastCompletedRep: {
    rep_side: "left" | "right" | null;
    rep_duration: number | null;
    rep_classification: string | null;
    rep_form_quality: string | null;
    feedback: string | null;
  };
  repsPerSet: number;
}

export default function WindmillStatsPanel({
  result,
  lastCompletedRep,
  repsPerSet,
}: Props) {
  const {
    rep_count,
    left_reps,
    right_reps,
    good_reps,
    flawed_reps,
    stage,
    current_side,
    ready,
    position_message,
    framing_message,
    feedback,
    smoothed_lean_angle,
  } = result;

  return (
    <div className="windmill-stats-panel">
      <div className="windmill-stat-row windmill-stat-row--primary">
        <div className="windmill-stat">
          <span className="windmill-stat-label">Reps</span>
          <span className="windmill-stat-value">
            {rep_count}
            {repsPerSet ? (
              <span className="windmill-stat-of">/{repsPerSet}</span>
            ) : null}
          </span>
        </div>
        <div className="windmill-stat">
          <span className="windmill-stat-label">Left arm down</span>
          <span className="windmill-stat-value">{left_reps}</span>
        </div>
        <div className="windmill-stat">
          <span className="windmill-stat-label">Right arm down</span>
          <span className="windmill-stat-value">{right_reps}</span>
        </div>
      </div>

      <div className="windmill-stat-row">
        <div className="windmill-stat">
          <span className="windmill-stat-label">Good form</span>
          <span className="windmill-stat-value windmill-stat-value--good">
            {good_reps}
          </span>
        </div>
        <div className="windmill-stat">
          <span className="windmill-stat-label">Needs work</span>
          <span className="windmill-stat-value windmill-stat-value--flawed">
            {flawed_reps}
          </span>
        </div>
        <div className="windmill-stat">
          <span className="windmill-stat-label">Stage</span>
          <span className="windmill-stat-value">
            {stage === "bent"
              ? current_side
                ? `reaching (${current_side})`
                : "reaching"
              : "tall / T-pose"}
          </span>
        </div>
      </div>

      <div className="windmill-stat-row">
        <div className="windmill-stat">
          <span className="windmill-stat-label">Hinge angle</span>
          <span className="windmill-stat-value">
            {smoothed_lean_angle != null
              ? `${Math.abs(smoothed_lean_angle).toFixed(0)}°`
              : "—"}
          </span>
        </div>
        <div className="windmill-stat">
          <span className="windmill-stat-label">Ready</span>
          <span className="windmill-stat-value">{ready ? "Yes" : "No"}</span>
        </div>
      </div>

      {lastCompletedRep.rep_side && (
        <div className="windmill-last-rep">
          Last rep: {lastCompletedRep.rep_side} side —{" "}
          {lastCompletedRep.rep_form_quality === "good"
            ? "good form"
            : "needs work"}
          {lastCompletedRep.rep_duration
            ? ` (${lastCompletedRep.rep_duration.toFixed(2)}s, ${lastCompletedRep.rep_classification})`
            : ""}
        </div>
      )}

      <div className="windmill-feedback">
        {framing_message || position_message || feedback || "Get ready..."}
      </div>
    </div>
  );
}
