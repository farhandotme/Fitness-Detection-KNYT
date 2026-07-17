import type { SidePlankData } from "../hooks/useSidePlankSocket";
import AngleGauge from "./AngleGauge";

interface Props {
  data: SidePlankData | undefined;
}

// Mirrors side_plank.py's thresholds — kept here purely for the gauge's
// visual zones and the support-angle badge; the backend is the source of
// truth for what actually counts as a valid hold.
const ALIGN_BROKEN = 140;
const ALIGN_IDEAL = 165;
const KNEE_BROKEN = 100;
const KNEE_IDEAL = 165;
const SUPPORT_IDEAL = 90;
const SUPPORT_TOLERANCE = 35;

const ISSUE_LABELS: Record<string, string> = {
  hip_sag: "Hips sagging — lift and brace",
  hip_pike: "Hips piked too high — lower slightly",
  knees_bent: "Knees bent (modified variation)",
  shoulder_elbow_misalign: "Elbow not under shoulder",
  head_position: "Neck out of neutral",
};

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function sideLabel(side: SidePlankData["active_side"]): string {
  if (side === "left") return "Left (supporting arm)";
  if (side === "right") return "Right (supporting arm)";
  return "—";
}

export default function SidePlankStatsPanel({ data }: Props) {
  const holdState = data?.hold_state ?? "not_started";
  const quality = data?.hold_quality;
  const target = data?.target_seconds ?? null;
  const holdSeconds = data?.hold_seconds ?? 0;

  const supportAngle = data?.support_angle ?? null;
  const supportOk =
    supportAngle != null && Math.abs(supportAngle - SUPPORT_IDEAL) <= SUPPORT_TOLERANCE;

  const progressPct =
    target != null ? Math.min(100, (holdSeconds / Math.max(1, target)) * 100) : null;

  return (
    <div className="arm-panel sideplank-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">SIDE PLANK</span>
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

      <div className="sideplank-timer-row">
        <span className="sideplank-timer">{formatTime(holdSeconds)}</span>
        {target != null && (
          <span className="sideplank-timer-target">/ {formatTime(target)}</span>
        )}
        <span className={`stage-badge ${holdState === "holding" ? "up" : "down"}`}>
          {holdState === "holding"
            ? "HOLDING"
            : holdState === "broken"
              ? "BROKEN"
              : "NOT STARTED"}
        </span>
      </div>

      {progressPct != null && (
        <div className="progress-track sideplank-progress-track">
          <div className="progress-fill" style={{ width: `${progressPct}%` }} />
        </div>
      )}

      <div className="sideplank-side-line">
        Supporting side: <strong>{sideLabel(data?.active_side ?? null)}</strong>
      </div>

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Current streak</span>
          <span className="v">{(data?.current_streak_seconds ?? 0).toFixed(1)}s</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Best streak</span>
          <span className="v">{(data?.best_streak_seconds ?? 0).toFixed(1)}s</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Breaks</span>
          <span className="v">{data?.break_count ?? 0}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Good / Flawed time</span>
          <span className="v">
            {(data?.good_seconds ?? 0).toFixed(0)}s / {(data?.flawed_seconds ?? 0).toFixed(0)}s
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Form score</span>
          <span className="v">
            {data?.form_score != null ? data.form_score : "—"}
            {data?.avg_form_score != null ? ` (avg ${data.avg_form_score})` : ""}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Set</span>
          <span className="v">
            {data?.set_number ?? 1} / {data?.target_sets ?? 1}
          </span>
        </div>
      </div>

      <div className="sideplank-angles">
        <div className="sideplank-angle-block">
          <div className="deadbug-pair-title">Alignment (shoulder–hip–ankle)</div>
          <AngleGauge
            angle={data?.alignment_angle ?? null}
            upThreshold={ALIGN_BROKEN}
            downThreshold={ALIGN_IDEAL}
            stage={holdState === "holding" ? "up" : "down"}
            compact
          />
          <span className="v">
            {data?.alignment_angle != null ? `${data.alignment_angle.toFixed(0)}°` : "—"}
            {" · ideal ≥ "}
            {ALIGN_IDEAL}°
          </span>
        </div>

        <div className="sideplank-angle-block">
          <div className="deadbug-pair-title">Legs (hip–knee–ankle)</div>
          <AngleGauge
            angle={data?.knee_angle ?? null}
            upThreshold={KNEE_BROKEN}
            downThreshold={KNEE_IDEAL}
            stage={holdState === "holding" ? "up" : "down"}
            compact
          />
          <span className="v">
            {data?.knee_angle != null ? `${data.knee_angle.toFixed(0)}°` : "—"}
            {" · straight ≥ "}
            {KNEE_IDEAL}°
          </span>
        </div>

        <div className="sideplank-angle-block">
          <div className="deadbug-pair-title">Support elbow (shoulder–elbow–wrist)</div>
          <div className={`sideplank-support-badge ${supportOk ? "ok" : "warn"}`}>
            {supportAngle != null ? `${supportAngle.toFixed(0)}°` : "—"}
            {" "}
            (ideal {SUPPORT_IDEAL}° ± {SUPPORT_TOLERANCE}°)
          </div>
        </div>

        <div className="sideplank-angle-block">
          <div className="deadbug-pair-title">Head / neck</div>
          <div className="sideplank-support-badge neutral">
            {data?.head_angle != null ? `${data.head_angle.toFixed(0)}°` : "—"}
            {" "}
            {data?.calibrated ? "(calibrated)" : "(calibrating…)"}
          </div>
        </div>
      </div>

      <div className={`quality-badge ${quality ?? ""}`}>
        {quality ? quality.replace(/_/g, " ") : "form: —"}
      </div>

      <div className={`posture-line ${data?.framing_ok === false ? "bad" : "ok"}`}>
        {data?.framing_ok === false && data.framing_message
          ? data.framing_message
          : "Framing: good — side-on, full body visible"}
      </div>

      <div className={`posture-line ${data?.posture_ok === false ? "bad" : "ok"}`}>
        {data?.posture_ok === false && data.posture_issues.length > 0
          ? (data.posture_messages[0] ??
            data.posture_issues.map((i) => ISSUE_LABELS[i] ?? i).join(", "))
          : data?.calibrated
            ? "Form looks good"
            : "Hold a clean position — calibrating your neutral posture…"}
      </div>
    </div>
  );
}
