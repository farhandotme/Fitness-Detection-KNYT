import type { BridgeHoldData } from "../hooks/useBridgeHoldSocket";

interface Props {
  data: BridgeHoldData | undefined;
  targetSeconds: number;
}

// Matches ALIGN_BROKEN / ALIGN_RESUME / ALIGN_IDEAL in bridge_pose.py.
const ALIGN_BROKEN = 140;
const ALIGN_IDEAL = 165;

// Matches KNEE_MIN_BROKEN / KNEE_IDEAL_MIN / KNEE_IDEAL_MAX / KNEE_MAX_BROKEN.
const KNEE_MIN_BROKEN = 60;
const KNEE_IDEAL_MIN = 80;
const KNEE_IDEAL_MAX = 130;
const KNEE_MAX_BROKEN = 150;

const RING_RADIUS = 54;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

function formatSeconds(s: number): string {
  return s >= 60
    ? `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`
    : s.toFixed(1);
}

export default function BridgeHoldStatsPanel({ data, targetSeconds }: Props) {
  const holdSeconds = data?.hold_seconds ?? 0;
  const progress = Math.min(1, holdSeconds / Math.max(1, targetSeconds));
  const isHolding = data?.is_holding ?? false;
  const state = data?.hold_state ?? "not_started";

  const alignPct = data?.alignment_angle != null
    ? Math.min(100, Math.max(0, ((data.alignment_angle - 100) / (180 - 100)) * 100))
    : null;

  const kneePct = data?.knee_angle != null
    ? Math.min(100, Math.max(0, ((data.knee_angle - 30) / (170 - 30)) * 100))
    : null;
  const kneeIdealStart = ((KNEE_IDEAL_MIN - 30) / (170 - 30)) * 100;
  const kneeIdealWidth = ((KNEE_IDEAL_MAX - KNEE_IDEAL_MIN) / (170 - 30)) * 100;

  return (
    <div className="arm-panel bh-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">GLUTE BRIDGE HOLD</span>
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

      <div className="bh-ring-wrap">
        <svg className="bh-ring" viewBox="0 0 130 130">
          <circle
            className="bh-ring-track"
            cx="65"
            cy="65"
            r={RING_RADIUS}
            fill="none"
            strokeWidth="10"
          />
          <circle
            className={`bh-ring-fill ${isHolding ? "holding" : state === "broken" ? "broken" : ""}`}
            cx="65"
            cy="65"
            r={RING_RADIUS}
            fill="none"
            strokeWidth="10"
            strokeDasharray={RING_CIRCUMFERENCE}
            strokeDashoffset={RING_CIRCUMFERENCE * (1 - progress)}
            strokeLinecap="round"
            transform="rotate(-90 65 65)"
          />
        </svg>
        <div className="bh-ring-center">
          <span className="bh-ring-time">{formatSeconds(holdSeconds)}</span>
          <span className="bh-ring-target">/ {formatSeconds(targetSeconds)}s</span>
        </div>
      </div>

      <div
        className={`bh-state-banner ${
          isHolding ? "holding" : state === "broken" ? "broken" : "not-started"
        }`}
      >
        {isHolding
          ? "✅ Holding — timer running"
          : state === "broken"
            ? "⏸ Form broken — timer paused"
            : "Get into position to start"}
      </div>

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Current streak</span>
          <span className="v">{formatSeconds(data?.current_streak_seconds ?? 0)}s</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Best streak</span>
          <span className="v">{formatSeconds(data?.best_streak_seconds ?? 0)}s</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Breaks</span>
          <span className="v">{data?.break_count ?? 0}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Good / Flawed</span>
          <span className="v">
            {formatSeconds(data?.good_seconds ?? 0)}s / {formatSeconds(data?.flawed_seconds ?? 0)}s
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Active side</span>
          <span className="v">{data?.active_side ?? "—"}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Form score</span>
          <span className="v">
            {data?.form_score != null
              ? data.form_score
              : data?.avg_form_score != null
                ? data.avg_form_score
                : "—"}
          </span>
        </div>
      </div>

      <div className="bh-sweet-spot">
        <span className="bh-sweet-spot-label">Alignment (shoulder-hip-knee)</span>
        <div className="bh-sweet-spot-track">
          <div
            className="bh-sweet-spot-zone"
            style={{
              left: `${((ALIGN_IDEAL - 100) / (180 - 100)) * 100}%`,
              width: `${100 - ((ALIGN_IDEAL - 100) / (180 - 100)) * 100}%`,
            }}
          />
          <div
            className="bh-sweet-spot-danger"
            style={{ width: `${((ALIGN_BROKEN - 100) / (180 - 100)) * 100}%` }}
          />
          {alignPct != null && (
            <div className="bh-sweet-spot-marker" style={{ left: `${alignPct}%` }} />
          )}
        </div>
        <span className="bh-sweet-spot-value">
          {data?.alignment_angle != null ? `${data.alignment_angle.toFixed(0)}°` : "—"}
        </span>
      </div>

      <div className="bh-sweet-spot">
        <span className="bh-sweet-spot-label">Knee angle</span>
        <div className="bh-sweet-spot-track">
          <div
            className="bh-sweet-spot-danger"
            style={{ width: `${((KNEE_MIN_BROKEN - 30) / (170 - 30)) * 100}%` }}
          />
          <div
            className="bh-sweet-spot-zone"
            style={{ left: `${kneeIdealStart}%`, width: `${kneeIdealWidth}%` }}
          />
          <div
            className="bh-sweet-spot-danger"
            style={{
              left: `${((KNEE_MAX_BROKEN - 30) / (170 - 30)) * 100}%`,
              width: `${100 - ((KNEE_MAX_BROKEN - 30) / (170 - 30)) * 100}%`,
            }}
          />
          {kneePct != null && (
            <div className="bh-sweet-spot-marker" style={{ left: `${kneePct}%` }} />
          )}
        </div>
        <span className="bh-sweet-spot-value">
          {data?.knee_angle != null ? `${data.knee_angle.toFixed(0)}°` : "—"}
        </span>
      </div>

      <div
        className={`posture-line ${data?.framing_ok === false ? "bad" : "ok"}`}
      >
        {data?.framing_ok === false && data.framing_message
          ? data.framing_message
          : "Position: good — side-on, full body in frame"}
      </div>

      <div
        className={`posture-line ${data?.posture_ok === false ? "bad" : "ok"}`}
      >
        {data?.posture_ok === false && data.posture_issues.length > 0
          ? (data.posture_messages[0] ??
            data.posture_issues.join(", ").replace(/_/g, " "))
          : "Posture looks good"}
      </div>
    </div>
  );
}
