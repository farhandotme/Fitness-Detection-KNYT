import type { ChildsPoseData } from "../hooks/useChildsPoseSocket";

interface Props {
  data: ChildsPoseData | undefined;
}

function formatSeconds(s: number | undefined | null): string {
  const total = Math.max(0, s ?? 0);
  const m = Math.floor(total / 60);
  const sec = total - m * 60;
  if (m > 0) return `${m}:${sec.toFixed(1).padStart(4, "0")}`;
  return `${sec.toFixed(1)}s`;
}

const STATE_LABEL: Record<string, string> = {
  not_started: "GET READY",
  holding: "HOLDING",
  broken: "PAUSED",
};

function viewLabel(view: ChildsPoseData["view_mode"]): string {
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

export default function ChildsPoseStatsPanel({ data }: Props) {
  const state = data?.hold_state ?? "not_started";
  const quality = data?.hold_quality;
  const calibrating = data?.ready && !data?.is_calibrated;

  return (
    <div className="arm-panel childspose-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">CHILD'S POSE HOLD</span>
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

      {calibrating ? (
        <div className="childspose-calibrating">
          <div className="childspose-calibrating-label">
            Calibrating to your position…
          </div>
          <div className="childspose-calibrating-track">
            <div
              className="childspose-calibrating-fill"
              style={{ width: `${(data?.calibration_progress ?? 0) * 100}%` }}
            />
          </div>
          <div className="childspose-calibrating-hint">
            Hold tabletop steady — hands and knees down, back flat
          </div>
        </div>
      ) : (
        <>
          <div className={`childspose-timer childspose-timer--${state}`}>
            <div className="childspose-timer-value">
              {formatSeconds(data?.hold_seconds)}
            </div>
            {data?.target_seconds != null && (
              <div className="childspose-timer-target">
                / {formatSeconds(data.target_seconds)}
              </div>
            )}
          </div>

          <div className="childspose-state-row">
            <span
              className={`stage-badge ${state === "holding" ? "up" : "down"}`}
            >
              {STATE_LABEL[state]}
            </span>
            {data?.view_mode && (
              <span className="childspose-view-pill">
                {viewLabel(data.view_mode)}
              </span>
            )}
          </div>

          {data?.target_seconds != null && (
            <div className="childspose-progress-track">
              <div
                className="childspose-progress-fill"
                style={{
                  width: `${Math.min(100, ((data.hold_seconds ?? 0) / data.target_seconds) * 100)}%`,
                }}
              />
            </div>
          )}
        </>
      )}

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Current streak</span>
          <span className="v">
            {formatSeconds(data?.current_streak_seconds)}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Best streak</span>
          <span className="v">{formatSeconds(data?.best_streak_seconds)}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Breaks</span>
          <span className="v">{data?.break_count ?? 0}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Good / Flawed</span>
          <span className="v">
            {formatSeconds(data?.good_seconds)} /{" "}
            {formatSeconds(data?.flawed_seconds)}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Fold depth</span>
          <span className="v">
            {data?.smoothed_fold_ratio != null && data?.tabletop_baseline
              ? `${Math.round((data.smoothed_fold_ratio / data.tabletop_baseline) * 100)}%`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Chest fold</span>
          <span className="v">
            {data?.chest_fold != null ? data.chest_fold.toFixed(2) : "—"}
          </span>
        </div>
      </div>

      <div className="arm-grid" style={{ marginTop: 4 }}>
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
          : "Position: good — side-on, kneeling, full body in frame"}
      </div>

      <div
        className={`posture-line ${data?.posture_ok === false ? "bad" : "ok"}`}
      >
        {data?.posture_ok === false && data.posture_issues.length > 0
          ? (data.posture_messages[0] ??
            data.posture_issues.join(", ").replace(/_/g, " "))
          : "Form looks good"}
      </div>
    </div>
  );
}
