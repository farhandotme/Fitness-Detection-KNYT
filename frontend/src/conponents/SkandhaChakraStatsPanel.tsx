import type { SkandhaChakraData } from "../hooks/useSkandhaChakraSocket";

interface Props {
  data: SkandhaChakraData | undefined;
}

function directionLabel(dir: SkandhaChakraData["rotation_direction"]): string {
  if (dir === "forward") return "Forward";
  if (dir === "backward") return "Backward";
  return "—";
}

function targetLabel(dir: SkandhaChakraData["target_direction"]): string {
  switch (dir) {
    case "forward":
      return "Forward only";
    case "backward":
      return "Backward only";
    default:
      return "Either direction";
  }
}

/**
 * Rotation is a fundamentally different shape of progress than a rep's
 * linear angle gauge (what every other exercise's stats panel uses) — a
 * fraction of one revolution, not a bounded joint angle. So this panel
 * uses a circular progress ring instead of reaching for `AngleGauge`,
 * which wouldn't represent "how far around the circle" honestly.
 */
function RotationRing({
  progress,
  direction,
}: {
  progress: number;
  direction: SkandhaChakraData["rotation_direction"];
}) {
  const size = 96;
  const stroke = 8;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.max(0, Math.min(1, progress));
  const offset = circumference * (1 - clamped);

  return (
    <div className="chakra-ring-wrap">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="rgba(242, 239, 228, 0.12)"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={direction === "backward" ? "#D9A441" : "#84C760"}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: "stroke-dashoffset 80ms linear" }}
        />
      </svg>
      <div className="chakra-ring-label">{Math.round(clamped * 100)}%</div>
    </div>
  );
}

export default function SkandhaChakraStatsPanel({ data }: Props) {
  const quality = data?.rep_form_quality;

  return (
    <div className="arm-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">SKANDHA CHAKRA</span>
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
        <span className={`stage-badge ${data?.stage ?? "waiting"}`}>
          {data?.stage === "rotating" ? "ROTATING" : "WAITING"}
        </span>
      </div>

      <RotationRing
        progress={data?.rotation_progress ?? 0}
        direction={data?.rotation_direction ?? null}
      />

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Direction</span>
          <span className="v">{directionLabel(data?.rotation_direction ?? null)}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Counting</span>
          <span className="v">{targetLabel(data?.target_direction ?? "either")}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Good / Flawed</span>
          <span className="v">
            {data?.good_reps ?? 0} / {data?.flawed_reps ?? 0}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Last circle</span>
          <span className="v">
            {data?.rep_duration != null ? `${data.rep_duration.toFixed(2)}s` : "—"}
          </span>
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
          : "Framing: good — full circle fits in shot"}
      </div>

      <div className={`posture-line ${data?.position_ok ? "ok" : "bad"}`}>
        {data?.position_ok
          ? "Upright position confirmed — counting rotations"
          : (data?.position_message ??
            "Waiting for a confirmed upright position…")}
      </div>

      <div
        className={`posture-line ${data?.arms_in_sync === false ? "bad" : "ok"}`}
      >
        {data?.arms_in_sync === false
          ? "Arms aren't circling together — match the pace"
          : "Arms circling in sync"}
      </div>
    </div>
  );
}
