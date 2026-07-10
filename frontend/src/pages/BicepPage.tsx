import { useEffect, useMemo, useState } from "react";
import useRepWebSocket, {
  type ArmData,
  type ArmMode,
} from "../hooks/usebicepCurlSocket";
import BicepCamera from "../conponents/BicepCamera";
import ArmStatsPanel from "../conponents/ArmStatsPanel";
import "./BicepPage.css";

const SELECT_ARM: ArmMode[] = ["left", "right", "both"];

const MODE_LABELS: Record<ArmMode, string> = {
  left: "LEFT ARM",
  right: "RIGHT ARM",
  both: "BOTH ARMS",
};

const POSE_CONNECTIONS: [number, number][] = [
  [11, 13],
  [13, 15],
  [12, 14],
  [14, 16],
  [11, 12],
  [23, 24],
  [11, 23],
  [12, 24],
  [23, 25],
  [25, 27],
  [24, 26],
  [26, 28],
];

const REP_PRESETS = [5, 10, 15, 20];

type Phase = "setup" | "active" | "complete";

function BicepPage() {
  const [armMode, setArmMode] = useState<ArmMode>("left");
  const [targetReps, setTargetReps] = useState(10);
  const [phase, setPhase] = useState<Phase>("setup");
  const [cameraError, setCameraError] = useState<string | null>(null);

  const {
    connected,
    result,
    lastCompletedRep,
    sendFrame,
    start,
    stop,
    socketError,
  } = useRepWebSocket();

  const skeleton = result.landmarks?.length
    ? [{ points: result.landmarks, connections: POSE_CONNECTIONS }]
    : [];

  const currentReps = result.rep_count ?? 0;
  const progressPct = Math.min(
    100,
    (currentReps / Math.max(1, targetReps)) * 100,
  );

  // Client-side target gate: the backend's own target is hardcoded, so we
  // watch rep_count ourselves and cut the connection the moment the user's
  // requested rep count is reached.
  useEffect(() => {
    if (phase === "active" && currentReps >= targetReps) {
      stop();
      setPhase("complete");
    }
  }, [phase, currentReps, targetReps, stop]);

  function handleStart() {
    setCameraError(null);
    setPhase("active");
    start(armMode);
  }

  function handleStop() {
    stop();
    setPhase("setup");
  }

  function handleReset() {
    stop();
    setCameraError(null);
    setPhase("setup");
  }

  const singleArmData: ArmData | undefined = useMemo(() => {
    if (armMode === "both") return undefined;
    return result as unknown as ArmData;
  }, [armMode, result]);

  const sessionGood = result.good_reps ?? 0;
  const sessionFlawed = result.flawed_reps ?? 0;
  const elapsed = result.elapsed_time ?? result.left_arm?.elapsed_time ?? 0;

  return (
    <div className="bicep-page">
      <div className="bicep-header">
        <div className="bicep-header-left">
          <h1 className="bicep-title">Bicep Curl Trainer</h1>

          <div className="exercise-picker">
            {SELECT_ARM.map((ex) => (
              <button
                key={ex}
                className={`pill ${armMode === ex ? "active" : ""}`}
                disabled={phase !== "setup"}
                onClick={() => setArmMode(ex)}
              >
                {MODE_LABELS[ex]}
              </button>
            ))}
          </div>
        </div>

        <div className="bicep-header-right">
          {phase === "setup" && (
            <div className="reps-setup">
              <label htmlFor="target-reps" className="reps-setup-label">
                Reps to complete
              </label>
              <div className="reps-setup-controls">
                <input
                  id="target-reps"
                  type="number"
                  min={1}
                  max={100}
                  value={targetReps}
                  onChange={(e) =>
                    setTargetReps(
                      Math.max(1, Math.min(100, Number(e.target.value) || 1)),
                    )
                  }
                  className="reps-input"
                />
                <div className="reps-presets">
                  {REP_PRESETS.map((n) => (
                    <button
                      key={n}
                      className={`reps-preset ${targetReps === n ? "active" : ""}`}
                      onClick={() => setTargetReps(n)}
                    >
                      {n}
                    </button>
                  ))}
                </div>
                <button className="start-btn" onClick={handleStart}>
                  Start ▶
                </button>
              </div>
            </div>
          )}

          {phase === "active" && (
            <div className="active-controls">
              <span className={`status-dot ${connected ? "live" : ""}`} />
              <span className="active-label">
                {connected ? "Live" : "Connecting…"} · {currentReps}/
                {targetReps} reps
              </span>
              <button className="stop-btn" onClick={handleStop}>
                Stop
              </button>
            </div>
          )}

          {phase === "complete" && (
            <div className="active-controls">
              <span className="complete-label">
                ✅ Target reached — {currentReps} reps done
              </span>
              <button className="start-btn" onClick={handleReset}>
                New Session
              </button>
            </div>
          )}
        </div>
      </div>

      {socketError && <div className="bicep-error">{socketError}</div>}
      {cameraError && <div className="bicep-error">{cameraError}</div>}

      <div className="bicep-body">
        <div className="bicep-camera-col">
          <BicepCamera
            active={phase === "active"}
            sendFrame={sendFrame}
            skeleton={skeleton}
            onError={setCameraError}
          />

          <div className="progress-track">
            <div
              className="progress-fill"
              style={{ width: `${progressPct}%` }}
            />
          </div>
          <div className="progress-caption">
            {currentReps} / {targetReps} reps
          </div>

          <div className="session-summary">
            <div className="session-summary-item good">
              <span className="k">Good</span>
              <span className="v">{sessionGood}</span>
            </div>
            <div className="session-summary-item flawed">
              <span className="k">Flawed</span>
              <span className="v">{sessionFlawed}</span>
            </div>
            <div className="session-summary-item">
              <span className="k">Elapsed</span>
              <span className="v">{elapsed.toFixed(0)}s</span>
            </div>
          </div>
        </div>

        <div className="bicep-stats-col">
          {phase === "setup" && (
            <div className="setup-hint">
              <p>
                Pick an arm mode and how many reps you want, then hit{" "}
                <strong>Start</strong>.
              </p>
              <p>
                The camera turns on, connects to the detector, counts your reps
                live, and disconnects automatically once you hit your target.
              </p>
            </div>
          )}

          {phase !== "setup" && armMode !== "both" && (
            <div className="single-arm-wrap">
              <ArmStatsPanel
                label={MODE_LABELS[armMode]}
                data={singleArmData}
              />

              {(lastCompletedRep.feedback || result.feedback) && (
                <div
                  className={`feedback-box ${lastCompletedRep.rep_form_quality ?? ""}`}
                >
                  <strong>Coach Feedback</strong>
                  <p>{lastCompletedRep.feedback ?? result.feedback}</p>
                </div>
              )}
            </div>
          )}

          {phase !== "setup" && armMode === "both" && (
            <div className="both-arm-wrap">
              <div className="sync-row">
                <span
                  className={`sync-badge ${result.sync_ok === false ? "bad" : "ok"}`}
                >
                  {result.sync_ok === false
                    ? "⚠️ Arms out of sync"
                    : "✅ Arms synced"}
                </span>
                <span className={`stage-badge ${result.stage ?? "down"}`}>
                  {(result.stage ?? "down").toUpperCase()}
                </span>
              </div>

              <div className="arm-columns">
                <ArmStatsPanel label="LEFT" data={result.left_arm} compact />
                <ArmStatsPanel label="RIGHT" data={result.right_arm} compact />
              </div>

              {(lastCompletedRep.feedback || result.feedback) && (
                <div
                  className={`feedback-box ${lastCompletedRep.rep_form_quality ?? ""}`}
                >
                  <strong>Coach Feedback</strong>
                  <p>{lastCompletedRep.feedback ?? result.feedback}</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default BicepPage;
