import type { CalfRaiseData } from "../hooks/useCalfRaiseSocket";

interface Props {
  data: CalfRaiseData | undefined;
}

const UP_LIFT = 0.2;

/** Small heel-lift meter, self-contained on purpose — this whole panel
 * avoids the shared `.arm-panel` / `.pose-pill` classes (which live in
 * the missing `BicepPage.css`) and defines everything it needs in
 * `CalfRaisePage.css` instead, so it renders correctly on its own. */
function LiftMeter({ lift, stage }: { lift: number | null; stage: string }) {
  const clamped = Math.max(0, Math.min(1, (lift ?? 0) / (UP_LIFT * 1.4)));
  const pct = Math.round(clamped * 100);

  return (
    <div className="calf-lift-meter">
      <div className="calf-lift-meter-track">
        <div
          className={`calf-lift-meter-fill ${stage}`}
          style={{ height: `${pct}%` }}
        />
        <div
          className="calf-lift-meter-threshold"
          style={{
            bottom: `${Math.round((UP_LIFT / (UP_LIFT * 1.4)) * 100)}%`,
          }}
        />
      </div>
      <span className="calf-lift-meter-label">
        {lift != null ? lift.toFixed(2) : "—"}
      </span>
    </div>
  );
}

export default function CalfRaiseStatsPanel({ data }: Props) {
  const lift = data?.smoothed_lift ?? data?.lift ?? null;
  const quality = data?.rep_form_quality;

  return (
    <div className="calf-panel">
      <div className="calf-panel-head">
        <span className="calf-panel-label">CALF RAISE</span>
        <span
          className={`calf-pose-pill ${data?.pose_detected ? (data.low_visibility ? "warn" : "ok") : "bad"}`}
        >
          {data?.pose_detected
            ? data.low_visibility
              ? "Unstable"
              : "Tracking"
            : "No pose"}
        </span>
      </div>

      <div className="calf-panel-rep-row">
        <span className="calf-panel-rep-count">{data?.rep_count ?? 0}</span>
        <span className={`calf-stage-badge ${data?.stage ?? "down"}`}>
          {(data?.stage ?? "down") === "up" ? "RAISED" : "FLAT"}
        </span>
      </div>

      <LiftMeter lift={lift} stage={data?.stage ?? "down"} />

      <div className="calf-grid">
        <div className="calf-grid-item">
          <span className="k">Left heel</span>
          <span className="v">
            {data?.left_lift != null ? data.left_lift.toFixed(2) : "—"}
          </span>
        </div>
        <div className="calf-grid-item">
          <span className="k">Right heel</span>
          <span className="v">
            {data?.right_lift != null ? data.right_lift.toFixed(2) : "—"}
          </span>
        </div>
        <div className="calf-grid-item">
          <span className="k">Knee angle</span>
          <span className="v">
            {data?.knee_angle != null ? `${data.knee_angle.toFixed(0)}°` : "—"}
          </span>
        </div>
        <div className="calf-grid-item">
          <span className="k">Good / Flawed</span>
          <span className="v">
            {data?.good_reps ?? 0} / {data?.flawed_reps ?? 0}
          </span>
        </div>
        <div className="calf-grid-item">
          <span className="k">Last rep</span>
          <span className="v">
            {data?.rep_duration != null
              ? `${data.rep_duration.toFixed(2)}s`
              : "—"}
          </span>
        </div>
        <div className="calf-grid-item">
          <span className="k">Tempo</span>
          <span className="v">
            {data?.rep_classification
              ? data.rep_classification.replace("_", " ")
              : "—"}
          </span>
        </div>
      </div>

      <div className={`calf-quality-badge ${quality ?? ""}`}>
        {quality ? quality.replace("_", " ") : "form: —"}
      </div>

      <div
        className={`calf-posture-line ${data?.framing_ok === false ? "bad" : "ok"}`}
      >
        {data?.framing_ok === false && data.framing_message
          ? data.framing_message
          : "Framing: good — full body visible in shot"}
      </div>

      <div className={`calf-posture-line ${data?.position_ok ? "ok" : "bad"}`}>
        {data?.position_ok
          ? data?.calibrated
            ? "Standing position confirmed — counting reps"
            : "Calibrating your flat-footed baseline…"
          : (data?.position_message ??
            "Waiting for a confirmed standing position…")}
      </div>
    </div>
  );
}
