import type { RussianTwistData } from "../hooks/useRussianTwistSocket";

interface Props {
  data: RussianTwistData | undefined;
}

const ROT_ENTER_DEG = 20; // mirrors backend ROT_ENTER_DEG, for the gauge only

const PHASE_LABEL: Record<string, string> = {
  center: "CENTER",
  left: "LEFT",
  right: "RIGHT",
};

/**
 * Small self-contained rotation gauge — a horizontal bar with a center
 * mark and a needle offset by the current torso rotation angle. Doesn't
 * depend on the shared `AngleGauge` component (missing from this repo,
 * same gap the jab page's mini gauge worked around).
 */
function RotationGauge({
  rotation,
  phase,
}: {
  rotation: number | null;
  phase: string;
}) {
  const clamped = Math.max(-45, Math.min(45, rotation ?? 0));
  const pct = 50 + (clamped / 45) * 50; // 0–100, 50 = center

  return (
    <div className="rtwist-gauge">
      <div className="rtwist-gauge-track">
        <div className="rtwist-gauge-center-mark" />
        <div
          className="rtwist-gauge-enter-band rtwist-gauge-enter-band--left"
          style={{ width: `${(ROT_ENTER_DEG / 45) * 50}%` }}
        />
        <div
          className="rtwist-gauge-enter-band rtwist-gauge-enter-band--right"
          style={{ width: `${(ROT_ENTER_DEG / 45) * 50}%` }}
        />
        <div
          className={`rtwist-gauge-needle rtwist-gauge-needle--${phase}`}
          style={{ left: `${pct}%` }}
        />
      </div>
      <div className="rtwist-gauge-labels">
        <span>RIGHT</span>
        <span>CENTER</span>
        <span>LEFT</span>
      </div>
    </div>
  );
}

export default function RussianTwistStatsPanel({ data }: Props) {
  const rotation = data?.torso_rotation_deg ?? null;
  const phase = data?.phase ?? "center";

  return (
    <div className="arm-panel rtwist-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">RUSSIAN TWIST</span>
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

      <RotationGauge rotation={rotation} phase={phase} />

      <div className="rtwist-split-row">
        <div className="rtwist-split-item rtwist-split-item--left">
          <span className="k">Left</span>
          <span className="v">{data?.left_count ?? 0}</span>
        </div>
        <div className="rtwist-split-item rtwist-split-item--right">
          <span className="k">Right</span>
          <span className="v">{data?.right_count ?? 0}</span>
        </div>
      </div>

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Rotation</span>
          <span className="v">
            {rotation != null ? `${rotation.toFixed(1)}°` : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Legs</span>
          <span className="v">
            {!data?.legs_visible
              ? "not visible"
              : data.legs_stable
                ? "stable"
                : "swinging"}
          </span>
        </div>
      </div>

      <div
        className={`posture-line ${data?.framing_ok === false ? "bad" : "ok"}`}
      >
        {data?.framing_ok === false && data.framing_message
          ? data.framing_message
          : "Framing: good — full torso visible in shot"}
      </div>

      <div className={`posture-line ${data?.seated_ok ? "ok" : "bad"}`}>
        {data?.seated_ok
          ? "Seated twist position confirmed — counting reps"
          : (data?.seated_message ??
            "Waiting for a confirmed seated position…")}
      </div>

      <div
        className={`posture-line ${data?.legs_stable === false ? "bad" : "ok"}`}
      >
        {data?.legs_stable === false
          ? (data.leg_message ?? "Keep your legs still.")
          : "Legs steady"}
      </div>
    </div>
  );
}
