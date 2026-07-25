import type { FlutterKicksData } from "../hooks/useFlutterKicksSocket";

interface LastCompletedRep {
  rep_duration: number | null;
  rep_classification: string | null;
  rep_form_quality: string | null;
  elevated_leg: "left" | "right" | null;
  feedback: string | null;
}

interface Props {
  data: FlutterKicksData | undefined;
  /**
   * The most recent COMPLETED rep's stats, persisted across frames.
   *
   * `data.rep_duration` / `data.rep_classification` / `data.rep_form_quality`
   * are edge-triggered — the backend only sets them non-null on the exact
   * frame a swap lands, then resets them to null again on every following
   * frame. Reading those fields directly here made "Last swap" / "Tempo" /
   * "Form" flash a value for one frame and then sit on a dash forever,
   * even after many good reps. This prop is the fix: the caller keeps the
   * last non-null values around (see `useFlutterKicksSocket`'s
   * `lastCompletedRep`) and we display those instead.
   */
  lastCompletedRep?: LastCompletedRep;
}

function viewLabel(view: FlutterKicksData["view_mode"]): string {
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

/** Small self-contained thigh-elevation bar for one leg — deliberately
 * doesn't depend on the shared `AngleGauge` component (missing from this
 * project), same "fully self-contained" approach as the Muay Thai Jab /
 * Side Plank pages. 180° (leg flat on the floor) sits at the left; ~90°
 * (leg raised) sits at the right. `isUp` comes straight from the backend
 * (`left_leg_up` / `right_leg_up`) rather than being re-derived here from
 * a hardcoded angle threshold, so this display can never drift out of
 * sync with what the counter is actually using to decide "up".
 */
function LegBar({
  label,
  angle,
  isUp,
}: {
  label: string;
  angle: number | null;
  isUp: boolean;
}) {
  const clamped = angle == null ? 180 : Math.min(180, Math.max(80, angle));
  const pct = ((180 - clamped) / (180 - 80)) * 100;

  return (
    <div className="leg-bar">
      <span className="leg-bar-label">{label}</span>
      <div className="leg-bar-track">
        <div
          className={`leg-bar-fill ${isUp ? "up" : "down"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="leg-bar-value">
        {angle != null ? `${angle.toFixed(0)}°` : "—"}
      </span>
      <span className={`leg-bar-state ${isUp ? "up" : "down"}`}>
        {isUp ? "UP" : "DOWN"}
      </span>
    </div>
  );
}

export default function FlutterKicksStatsPanel({
  data,
  lastCompletedRep,
}: Props) {
  // Persisted last-rep values (fixes the "always shows a dash" bug) —
  // fall back to the raw per-frame field only if no rep has completed yet
  // this connection (both will legitimately be null at session start).
  const quality = lastCompletedRep?.rep_form_quality ?? data?.rep_form_quality;
  const lastDuration = lastCompletedRep?.rep_duration ?? data?.rep_duration;
  const lastTempo =
    lastCompletedRep?.rep_classification ?? data?.rep_classification;

  return (
    <div className="flutter-panel">
      <div className="flutter-panel-head">
        <span className="flutter-panel-label">FLUTTER KICKS</span>
        <span
          className={`flutter-pose-pill ${data?.pose_detected ? (data.low_visibility ? "warn" : "ok") : "bad"}`}
        >
          {data?.pose_detected
            ? data.low_visibility
              ? "Unstable"
              : "Tracking"
            : "No pose"}
        </span>
      </div>

      <div className="flutter-rep-row">
        <span className="flutter-rep-count">{data?.rep_count ?? 0}</span>
        <span
          className={`flutter-stage-badge ${data?.elevated_leg ?? "neutral"}`}
        >
          {data?.elevated_leg
            ? `${data.elevated_leg.toUpperCase()} UP`
            : "NEUTRAL"}
        </span>
      </div>

      <div className="leg-bars">
        <LegBar
          label="Left thigh"
          angle={data?.left_thigh_angle ?? null}
          isUp={data?.left_leg_up ?? false}
        />
        <LegBar
          label="Right thigh"
          angle={data?.right_thigh_angle ?? null}
          isUp={data?.right_leg_up ?? false}
        />
      </div>
      <div className="leg-bar-scale-caption">
        180° = leg flat near the floor · smaller = more raised · a leg counts as
        "up" once it's clearly bent from straight AND clearly more raised than
        the other leg
      </div>

      <div className="flutter-grid">
        <div className="flutter-grid-item">
          <span className="k">Left / Right swaps</span>
          <span className="v">
            {data?.left_reps ?? 0} / {data?.right_reps ?? 0}
          </span>
        </div>
        <div className="flutter-grid-item">
          <span className="k">Good / Flawed</span>
          <span className="v">
            {data?.good_reps ?? 0} / {data?.flawed_reps ?? 0}
          </span>
        </div>
        <div className="flutter-grid-item">
          <span className="k">Last swap</span>
          <span className="v">
            {lastDuration != null ? `${lastDuration.toFixed(2)}s` : "—"}
          </span>
        </div>
        <div className="flutter-grid-item">
          <span className="k">Tempo</span>
          <span className="v">
            {lastTempo ? lastTempo.replace("_", " ") : "—"}
          </span>
        </div>
        <div className="flutter-grid-item">
          <span className="k">Cycles (L+R)</span>
          <span className="v">{data?.cycle_count ?? 0}</span>
        </div>
        <div className="flutter-grid-item">
          <span className="k">Camera</span>
          <span className="v">{viewLabel(data?.view_mode ?? null)}</span>
        </div>
      </div>

      <div className={`quality-badge ${quality ?? ""}`}>
        {quality ? quality.replace("_", " ") : "form: —"}
      </div>

      <div
        className={`flutter-posture-line ${data?.framing_ok === false ? "bad" : "ok"}`}
      >
        {data?.framing_ok === false && data.framing_message
          ? data.framing_message
          : "Framing: good — full body visible in shot"}
      </div>

      <div
        className={`flutter-posture-line ${data?.position_ok ? "ok" : "bad"}`}
      >
        {data?.position_ok
          ? "Lying position confirmed — counting swaps"
          : (data?.position_message ??
            "Waiting for a confirmed lying position…")}
      </div>
    </div>
  );
}
