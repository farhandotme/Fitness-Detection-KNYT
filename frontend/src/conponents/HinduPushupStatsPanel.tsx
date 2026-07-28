import type { HinduPushupData } from "../hooks/useHinduPushupSocket";

interface Props {
  data: HinduPushupData | undefined;
}

// Mirrors the backend's DOWNDOG_ARC / UPDOG_ARC constants in
// src/detectors/hindu_pushup.py — kept in sync manually since the arc
// range is what the gauge below visualizes.
const DOWNDOG_ARC = -0.3;
const UPDOG_ARC = 0.26;
const GAUGE_MIN = -0.6;
const GAUGE_MAX = 0.7;

function viewLabel(view: HinduPushupData["view_mode"]): string {
  switch (view) {
    case "side":
      return "Side view";
    case "front":
      return "Front view (unsupported)";
    case "angled":
      return "Angled view";
    default:
      return "—";
  }
}

/** Horizontal arc gauge: Downward Dog on the left, Cobra on the right. */
function ArcGauge({
  arc,
  stage,
}: {
  arc: number | null;
  stage: HinduPushupData["stage"];
}) {
  const clamped = arc == null ? 0 : Math.max(GAUGE_MIN, Math.min(GAUGE_MAX, arc));
  const pct = ((clamped - GAUGE_MIN) / (GAUGE_MAX - GAUGE_MIN)) * 100;
  const downdogPct = ((DOWNDOG_ARC - GAUGE_MIN) / (GAUGE_MAX - GAUGE_MIN)) * 100;
  const updogPct = ((UPDOG_ARC - GAUGE_MIN) / (GAUGE_MAX - GAUGE_MIN)) * 100;

  return (
    <div className="hindu-arc-gauge">
      <div className="hindu-arc-gauge-track">
        <div
          className="hindu-arc-gauge-zone downdog-zone"
          style={{ left: 0, width: `${downdogPct}%` }}
        />
        <div
          className="hindu-arc-gauge-zone updog-zone"
          style={{ left: `${updogPct}%`, width: `${100 - updogPct}%` }}
        />
        {arc != null && (
          <div className="hindu-arc-gauge-marker" style={{ left: `${pct}%` }} />
        )}
      </div>
      <div className="hindu-arc-gauge-labels">
        <span className={stage === "downdog" ? "active" : ""}>
          🐕 Downward Dog
        </span>
        <span className={stage === "updog" ? "active" : ""}>🐍 Cobra</span>
      </div>
    </div>
  );
}

export default function HinduPushupStatsPanel({ data }: Props) {
  const arc = data?.smoothed_hip_arc ?? data?.hip_arc ?? null;
  const quality = data?.rep_form_quality;

  return (
    <div className="arm-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">HINDU PUSH-UP</span>
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
        <span className={`stage-badge ${data?.stage ?? "downdog"}`}>
          {(data?.stage ?? "downdog") === "updog" ? "COBRA" : "DOWNDOG"}
        </span>
      </div>

      <ArcGauge arc={arc} stage={data?.stage ?? "downdog"} />

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Hip arc</span>
          <span className="v">{arc != null ? arc.toFixed(2) : "—"}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Elbow angle</span>
          <span className="v">
            {data?.elbow_angle != null ? `${data.elbow_angle.toFixed(1)}°` : "—"}
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
          <span className="k">Tempo</span>
          <span className="v">
            {data?.rep_classification ? data.rep_classification.replace("_", " ") : "—"}
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

      <div
        className={`posture-line ${data?.framing_ok === false ? "bad" : "ok"}`}
      >
        {data?.framing_ok === false && data.framing_message
          ? data.framing_message
          : "Framing: good — full body visible in shot"}
      </div>

      <div className={`posture-line ${data?.position_ok ? "ok" : "bad"}`}>
        {data?.position_ok
          ? "Floor stance confirmed — counting reps"
          : (data?.position_message ??
            "Waiting for a confirmed Downward Dog position…")}
      </div>

      <div
        className={`posture-line ${data?.alignment_ok === false ? "bad" : "ok"}`}
      >
        {data?.alignment_ok === false && data.alignment_issue
          ? data.alignment_issue.replace(/_/g, " ")
          : "Form looks good"}
      </div>

      {(data?.partial_rep_count ?? 0) > 0 && (
        <div className="posture-line bad">
          {data?.partial_rep_count} shallow attempt(s) not counted — sink
          lower into Cobra.
        </div>
      )}
    </div>
  );
}
