import type { InchwormData } from "../hooks/useInchwormSocket";

interface Props {
  data: InchwormData | undefined;
}

function viewLabel(view: InchwormData["view_mode"]): string {
  switch (view) {
    case "side":
      return "Side view";
    case "front":
      return "Front view";
    case "angled":
      return "Angled view";
    default:
      return "—";
  }
}

function checkRow(label: string, ok: boolean, badText: string) {
  return (
    <div className={`inchworm-check-row ${ok ? "ok" : "bad"}`}>
      <span className="inchworm-check-dot">{ok ? "✓" : "✕"}</span>
      <span className="inchworm-check-label">{label}</span>
      {!ok && <span className="inchworm-check-hint">{badText}</span>}
    </div>
  );
}

export default function InchwormStatsPanel({ data }: Props) {
  const quality = data?.rep_form_quality;
  const stage = data?.stage ?? "standing";
  const holdProgress = Math.min(1, Math.max(0, data?.hold_progress ?? 0));
  const holdPct = Math.round(holdProgress * 100);

  return (
    <div className="arm-panel inchworm-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">INCHWORM</span>
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
        <span className={`stage-badge ${stage}`}>
          {stage === "plank" ? "PLANK" : "STANDING"}
        </span>
      </div>

      <div className="inchworm-hold-gauge">
        <div className="inchworm-hold-track">
          <div
            className={`inchworm-hold-fill ${data?.hold_confirmed ? "confirmed" : ""}`}
            style={{ width: `${holdPct}%` }}
          />
        </div>
        <div className="inchworm-hold-caption">
          {stage === "plank"
            ? data?.hold_confirmed
              ? `Hold confirmed (${(data?.hold_elapsed ?? 0).toFixed(1)}s) — walk back and stand up`
              : `Holding plank: ${(data?.hold_elapsed ?? 0).toFixed(1)}s / ${(data?.hold_required ?? 1).toFixed(1)}s`
            : "Walk your hands out to a full plank to start the hold timer"}
        </div>
      </div>

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Torso incline</span>
          <span className="v">
            {data?.torso_incline != null ? `${data.torso_incline.toFixed(0)}°` : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Good / Flawed</span>
          <span className="v">
            {data?.good_reps ?? 0} / {data?.flawed_reps ?? 0}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Not held long enough</span>
          <span className="v">{data?.partial_rep_count ?? 0}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Last hold</span>
          <span className="v">
            {data?.rep_hold_duration != null
              ? `${data.rep_hold_duration.toFixed(2)}s`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Hold quality</span>
          <span className="v">
            {data?.rep_classification
              ? data.rep_classification.replace(/_/g, " ")
              : "—"}
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

      <div className="inchworm-checklist">
        {checkRow(
          "Hands directly below shoulders",
          data?.hands_aligned ?? true,
          "Walk hands in under your shoulders",
        )}
        {checkRow(
          "Legs straight",
          data?.legs_straight ?? true,
          "Straighten your knees",
        )}
        {checkRow(
          "Neck neutral, eyes ahead",
          data?.neck_neutral ?? true,
          "Lift your head slightly",
        )}
      </div>

      <div className={`posture-line ${data?.position_ok || data?.standing_confirmed ? "ok" : "bad"}`}>
        {data?.position_message ??
          (stage === "plank"
            ? "Full plank confirmed — hold steady"
            : "Standing tall — ready for the next rep")}
      </div>
    </div>
  );
}
