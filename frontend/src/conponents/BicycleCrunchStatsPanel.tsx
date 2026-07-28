import type { BicycleCrunchData } from "../hooks/useBicycleCrunchSocket";

interface Props {
  data: BicycleCrunchData | undefined;
}

const PHASE_LABEL: Record<string, string> = {
  center: "CENTER",
  left: "LEFT",
  right: "RIGHT",
};

/**
 * Small self-contained crossover gauge — same idea as the Russian
 * twist's rotation gauge, just reading `crunch_signal` /
 * `signal_envelope` instead of a rotation angle. Doesn't depend on the
 * shared `AngleGauge` component (missing from this repo).
 */
function CrossoverGauge({
  signal,
  envelope,
  phase,
}: {
  signal: number | null;
  envelope: number | null;
  phase: string;
}) {
  const range = Math.max(envelope ?? 0.6, 0.3);
  const clamped = Math.max(-range, Math.min(range, signal ?? 0));
  const pct = 50 + (clamped / range) * 50;

  return (
    <div className="bcrunch-gauge">
      <div className="bcrunch-gauge-track">
        <div className="bcrunch-gauge-center-mark" />
        <div
          className={`bcrunch-gauge-needle bcrunch-gauge-needle--${phase}`}
          style={{ left: `${pct}%` }}
        />
      </div>
      <div className="bcrunch-gauge-labels">
        <span>RIGHT</span>
        <span>CENTER</span>
        <span>LEFT</span>
      </div>
    </div>
  );
}

export default function BicycleCrunchStatsPanel({ data }: Props) {
  const signal = data?.crunch_signal ?? null;
  const envelope = data?.signal_envelope ?? null;
  const phase = data?.phase ?? "center";

  return (
    <div className="arm-panel bcrunch-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">BICYCLE CRUNCH</span>
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
        <span className={`stage-badge ${phase === "center" ? "down" : "up"}`}>
          {PHASE_LABEL[phase]}
        </span>
      </div>

      <CrossoverGauge signal={signal} envelope={envelope} phase={phase} />

      <div className="bcrunch-split-row">
        <div className="bcrunch-split-item bcrunch-split-item--left">
          <span className="k">Left</span>
          <span className="v">{data?.left_count ?? 0}</span>
        </div>
        <div className="bcrunch-split-item bcrunch-split-item--right">
          <span className="k">Right</span>
          <span className="v">{data?.right_count ?? 0}</span>
        </div>
      </div>

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Crossover</span>
          <span className="v">{signal != null ? signal.toFixed(2) : "—"}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Legs</span>
          <span className="v">
            {!data?.legs_visible
              ? "not visible"
              : data.legs_alternating
                ? "pedaling"
                : "not alternating"}
          </span>
        </div>
      </div>

      <div
        className={`posture-line ${data?.framing_ok === false ? "bad" : "ok"}`}
      >
        {data?.framing_ok === false && data.framing_message
          ? data.framing_message
          : "Framing: good — full body visible in shot"}
      </div>

      <div className={`posture-line ${data?.base_ok ? "ok" : "bad"}`}>
        {data?.base_ok
          ? "Base position confirmed — counting reps"
          : (data?.base_message ?? "Waiting for a confirmed start position…")}
      </div>

      <div
        className={`posture-line ${data?.legs_alternating === false ? "bad" : "ok"}`}
      >
        {data?.legs_alternating === false
          ? (data.leg_message ?? "Extend your other leg like pedaling a bike.")
          : "Legs pedaling"}
      </div>
    </div>
  );
}
