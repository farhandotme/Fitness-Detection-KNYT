import type { MountainClimberData } from "../hooks/useMountainClimberSocket";
import AngleGauge from "./AngleGauge";

interface Props {
  data: MountainClimberData | undefined;
}

const STAGE_LABEL: Record<string, string> = {
  ready: "READY",
  drive: "DRIVE",
};

function formatIssue(issue: string) {
  return issue.replace(/_/g, " ");
}

export default function MountainClimberStatsPanel({ data }: Props) {
  const quality = data?.rep_form_quality;
  const activeLeg = data?.active_leg;
  const stage = data?.stage ?? "ready";
  const stageClass = stage === "drive" ? "up" : "down";
  const stageLabel = activeLeg
    ? activeLeg.toUpperCase()
    : (STAGE_LABEL[stage] ?? "READY");

  const hasPose = Boolean(data?.pose_detected);
  const isUnstable = Boolean(data?.low_visibility);
  const postureBad = data?.posture_ok === false;
  const framingBad = data?.framing_ok === false;

  const leftDrive = data?.left_knee_drive === true;
  const rightDrive = data?.right_knee_drive === true;
  const bothDrive = leftDrive && rightDrive;

  const primaryFeedback =
    framingBad && data?.framing_message
      ? data.framing_message
      : postureBad && data?.posture_messages?.length
        ? data.posture_messages[0]
        : (data?.feedback ?? null);

  return (
    <div className="arm-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">MOUNTAIN CLIMBER</span>
        <span
          className={`pose-pill ${
            hasPose ? (isUnstable ? "warn" : "ok") : "bad"
          }`}
        >
          {hasPose ? (isUnstable ? "Unstable" : "Tracking") : "No pose"}
        </span>
      </div>

      <div className="arm-panel-rep-row">
        <span className="arm-panel-rep-count">{data?.rep_count ?? 0}</span>
        <span className={`stage-badge ${stageClass}`}>{stageLabel}</span>
      </div>

      <AngleGauge
        angle={data?.body_alignment ?? null}
        upThreshold={140}
        downThreshold={180}
        stage={stage === "drive" ? "up" : "down"}
      />

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Left knee</span>
          <span className="v">
            {data?.left_knee_drive == null ? "—" : leftDrive ? "Drive" : "Rest"}
          </span>
        </div>

        <div className="arm-grid-item">
          <span className="k">Right knee</span>
          <span className="v">
            {data?.right_knee_drive == null
              ? "—"
              : rightDrive
                ? "Drive"
                : "Rest"}
          </span>
        </div>

        <div className="arm-grid-item">
          <span className="k">Good / Flawed</span>
          <span className="v">
            {data?.good_reps ?? 0} / {data?.flawed_reps ?? 0}
          </span>
        </div>

        <div className="arm-grid-item">
          <span className="k">Tempo</span>
          <span className="v">
            {data?.pace_classification
              ? data.pace_classification.replace("_", " ")
              : "—"}
          </span>
        </div>

        <div className="arm-grid-item">
          <span className="k">Alignment</span>
          <span className="v">
            {data?.body_alignment != null
              ? `${data.body_alignment.toFixed(1)}°`
              : "—"}
          </span>
        </div>

        <div className="arm-grid-item">
          <span className="k">Elapsed</span>
          <span className="v">
            {data?.elapsed_time != null
              ? `${data.elapsed_time.toFixed(0)}s`
              : "—"}
          </span>
        </div>

        <div className="arm-grid-item">
          <span className="k">Form score</span>
          <span className="v">
            {data?.form_score != null ? `${data.form_score}` : "—"}
          </span>
        </div>

        <div className="arm-grid-item">
          <span className="k">Calibration</span>
          <span className="v">{data?.calibrated ? "Ready" : "Learning"}</span>
        </div>
      </div>

      <div className={`quality-badge ${quality ?? ""}`}>
        {quality ? formatIssue(quality) : "form: —"}
      </div>

      <div className={`posture-line ${framingBad ? "bad" : "ok"}`}>
        {framingBad && data?.framing_message
          ? data.framing_message
          : "Position: good — full body visible and centered"}
      </div>

      <div className={`posture-line ${postureBad ? "bad" : "ok"}`}>
        {postureBad && data?.posture_messages?.length
          ? data.posture_messages[0]
          : data?.calibrated
            ? "Posture looks good"
            : "Calibrating your form baseline…"}
      </div>

      <div className={`posture-line ${bothDrive ? "bad" : "ok"}`}>
        {bothDrive
          ? "Drive only one knee at a time."
          : "Alternation looks good"}
      </div>

      <div className="posture-line ok">
        {primaryFeedback ?? "Hold a strong plank and drive knees alternately."}
      </div>
    </div>
  );
}
