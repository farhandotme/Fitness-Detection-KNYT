import type { ShoulderPressData } from "../hooks/useShoulderPressSocket";
import AngleGauge from "./AngleGauge";

interface Props {
  data: ShoulderPressData | undefined;
}

const ISSUE_LABEL: Record<string, string> = {
  poor_posture: "Leaning / arching back",
  wrist_not_stacked: "Wrist not stacked",
  elbows_flared: "Elbows too flared",
  asymmetric_press: "Uneven arms",
};

export default function ShoulderPressStatsPanel({ data }: Props) {
  const quality = data?.rep_form_quality;
  const issues = data?.posture_issues ?? [];

  return (
    <div className="arm-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">SHOULDER PRESS</span>
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
        <span className={`stage-badge ${data?.stage ?? "down"}`}>
          {(data?.stage ?? "down") === "up" ? "LOCKOUT" : "RACK"}
        </span>
      </div>

      <AngleGauge
        angle={data?.angle ?? null}
        upThreshold={160}
        downThreshold={95}
        stage={data?.stage === "up" ? "up" : "down"}
      />

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Left elbow angle</span>
          <span className="v">
            {data?.left_elbow_angle != null
              ? `${data.left_elbow_angle.toFixed(1)}°`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Right elbow angle</span>
          <span className="v">
            {data?.right_elbow_angle != null
              ? `${data.right_elbow_angle.toFixed(1)}°`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Good / Flawed</span>
          <span className="v">
            {data?.good_reps ?? 0} / {data?.flawed_reps ?? 0}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Half reps</span>
          <span className="v">{data?.partial_rep_count ?? 0}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Last rep</span>
          <span className="v">
            {data?.rep_duration != null
              ? `${data.rep_duration.toFixed(2)}s`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Tempo</span>
          <span className="v">
            {data?.rep_classification
              ? data.rep_classification.replace("_", " ")
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Calibration</span>
          <span className="v">
            {data?.calibrated ? "Ready" : "Calibrating…"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Cadence</span>
          <span className="v">
            {data?.reps_per_minute != null
              ? `${data.reps_per_minute} rpm`
              : "—"}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Pace</span>
          <span className="v">
            {data?.pace_classification
              ? data.pace_classification.replace("_", " ")
              : "—"}
          </span>
        </div>
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
          : "Position: good — full range overhead in frame, centered"}
      </div>

      {/* Every tracked correction, live — not just a single summary line,
          since the whole point of this exercise is getting all four checks
          right on every rep. */}
      {(["poor_posture", "wrist_not_stacked", "elbows_flared", "asymmetric_press"] as const).map(
        (key) => {
          const active = issues.includes(key);
          return (
            <div key={key} className={`posture-line ${active ? "bad" : "ok"}`}>
              {active
                ? (data?.posture_messages.find((_m, i) => issues[i] === key) ??
                  ISSUE_LABEL[key])
                : `${ISSUE_LABEL[key]}: looks good`}
            </div>
          );
        },
      )}
    </div>
  );
}
