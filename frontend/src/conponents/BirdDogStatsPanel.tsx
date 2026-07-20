import type { BirdDogData } from "../hooks/useBirdDogSocket";

interface Props {
  data: BirdDogData | undefined;
}

function sideLabel(side: BirdDogData["reach_arm_side"]): string {
  if (side === "left") return "Left";
  if (side === "right") return "Right";
  return "—";
}

function deg(n: number | null | undefined): string {
  return n != null ? `${n.toFixed(0)}°` : "—";
}

export default function BirdDogStatsPanel({ data }: Props) {
  const stage = data?.stage ?? "tabletop";
  const quality = data?.rep_form_quality;
  const armSide = data?.reach_arm_side ?? null;
  const legSide = data?.reach_leg_side ?? null;

  // The contralateral pairing is the whole anti-cheat point — surface it
  // front and center, not buried in a grid cell.
  const pairingOk = armSide == null || legSide == null || armSide !== legSide;

  // Best-available current reach angle per limb, whichever side is
  // reading higher right now — shown live, in every stage, so the
  // numbers visibly move the instant tracking is working, calibrated
  // or not.
  const armAngle =
    data?.left_arm_reach_angle != null || data?.right_arm_reach_angle != null
      ? Math.max(data?.left_arm_reach_angle ?? 0, data?.right_arm_reach_angle ?? 0)
      : null;
  const legAngle =
    data?.left_leg_reach_angle != null || data?.right_leg_reach_angle != null
      ? Math.max(data?.left_leg_reach_angle ?? 0, data?.right_leg_reach_angle ?? 0)
      : null;

  return (
    <div className="arm-panel">
      <div className="arm-panel-head">
        <span className="arm-panel-label">BIRD DOG</span>
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
          {stage === "reaching" ? "REACHING" : "TABLETOP"}
        </span>
      </div>

      {data?.calibrating && (
        <div className="calib-banner">
          <span className="calib-dot" />
          Calibrating to your camera angle — hold tabletop position still…
        </div>
      )}

      <div className="bird-dog-pairing">
        <div className={`bird-dog-limb ${armSide ? "active" : ""}`}>
          <span className="k">Arm</span>
          <span className="v">{sideLabel(armSide)}</span>
          <span className="angle">{deg(armAngle)}</span>
        </div>
        <div
          className={`bird-dog-pairing-x ${
            armSide && legSide ? (pairingOk ? "ok" : "bad") : ""
          }`}
        >
          {armSide && legSide ? (pairingOk ? "✓ opposite" : "✕ same side") : "+"}
        </div>
        <div className={`bird-dog-limb ${legSide ? "active" : ""}`}>
          <span className="k">Leg</span>
          <span className="v">{sideLabel(legSide)}</span>
          <span className="angle">{deg(legAngle)}</span>
        </div>
      </div>

      <div className="arm-grid">
        <div className="arm-grid-item">
          <span className="k">Elbow angle</span>
          <span className="v">{deg(data?.elbow_angle)}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Knee angle</span>
          <span className="v">{deg(data?.knee_angle)}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Back line</span>
          <span className="v">{deg(data?.alignment_angle)}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Good / Flawed</span>
          <span className="v">
            {data?.good_reps ?? 0} / {data?.flawed_reps ?? 0}
          </span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Not counted</span>
          <span className="v">{data?.rejected_reps ?? 0}</span>
        </div>
        <div className="arm-grid-item">
          <span className="k">Base position</span>
          <span className="v">{data?.ready ? "Confirmed" : "Not set"}</span>
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

      <div className={`posture-line ${data?.ready ? "ok" : "bad"}`}>
        {data?.ready
          ? "Tabletop position confirmed — counting reps"
          : data?.calibrating
            ? "Learning your resting tabletop angles…"
            : "Waiting for a confirmed all-fours position…"}
      </div>

      <div
        className={`posture-line ${
          data?.posture_issues && data.posture_issues.length > 0 ? "bad" : "ok"
        }`}
      >
        {data?.posture_issues && data.posture_issues.length > 0
          ? data.posture_issues.map((i) => i.replace(/_/g, " ")).join(", ")
          : "Back line and hips look level"}
      </div>
    </div>
  );
}
