import type { StandingCrossCrunchData } from "../hooks/useStandingCrossCrunchSocket";

interface Props {
  data: StandingCrossCrunchData | undefined;
}

function sideLabel(side: "left" | "right" | null): string {
  if (side === "left") return "LEFT";
  if (side === "right") return "RIGHT";
  return "—";
}

export default function StandingCrossCrunchStatsPanel({ data }: Props) {
  const quality = data?.rep_form_quality;

  return (
    <div className="ccrunch-panel">
      <div className="ccrunch-panel-head">
        <span className="ccrunch-panel-label">STANDING CROSS CRUNCH</span>
        <span
          className={`ccrunch-pose-pill ${
            data?.pose_detected ? (data.low_visibility ? "warn" : "ok") : "bad"
          }`}
        >
          {data?.pose_detected
            ? data.low_visibility
              ? "Unstable"
              : "Tracking"
            : "No pose"}
        </span>
      </div>

      <div className="ccrunch-rep-row">
        <span className="ccrunch-rep-count">{data?.rep_count ?? 0}</span>
        <span className={`ccrunch-stage-badge ${data?.stage ?? "down"}`}>
          {(data?.stage ?? "down") === "up" ? "CRUNCHING" : "STANDING"}
        </span>
      </div>

      <div className="ccrunch-side-row">
        <div className={`ccrunch-side-chip ${data?.current_side === "left" ? "active" : ""}`}>
          <span className="k">Left knee gap</span>
          <span className="v">{data?.left_knee_gap ?? "—"}</span>
        </div>
        <div className={`ccrunch-side-chip ${data?.current_side === "right" ? "active" : ""}`}>
          <span className="k">Right knee gap</span>
          <span className="v">{data?.right_knee_gap ?? "—"}</span>
        </div>
      </div>

      <div className="ccrunch-grid">
        <div className="ccrunch-grid-item">
          <span className="k">Hands behind head</span>
          <span className="v">{data?.hands_ok ? "OK" : "Check"}</span>
        </div>
        <div className="ccrunch-grid-item">
          <span className="k">Cross distance</span>
          <span className="v">{data?.cross_distance ?? "—"}</span>
        </div>
        <div className="ccrunch-grid-item">
          <span className="k">Last side counted</span>
          <span className="v">{sideLabel(data?.last_completed_side ?? null)}</span>
        </div>
        <div className="ccrunch-grid-item">
          <span className="k">Next side expected</span>
          <span className="v">{sideLabel(data?.expected_next_side ?? null)}</span>
        </div>
        <div className="ccrunch-grid-item">
          <span className="k">Good reps</span>
          <span className="v">{data?.good_reps ?? 0}</span>
        </div>
        <div className="ccrunch-grid-item">
          <span className="k">Needs improvement</span>
          <span className="v">{data?.flawed_reps ?? 0}</span>
        </div>
      </div>

      {data?.alternation_broken && (
        <div className="ccrunch-alert warn">
          Same side repeated — not counted. Switch sides to keep the
          left-right cadence going.
        </div>
      )}

      {quality === "needs_improvement" && !data?.alternation_broken && (
        <div className="ccrunch-alert notice">
          Rep counted, but bring your elbow further across to your knee for
          a fuller crunch.
        </div>
      )}

      <div className="ccrunch-feedback">{data?.feedback ?? "Get ready…"}</div>
    </div>
  );
}
