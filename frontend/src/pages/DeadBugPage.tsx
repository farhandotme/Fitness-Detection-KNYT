import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import useDeadBugSocket from "../hooks/useDeadBugSocket";
import DeadBugCamera from "../conponents/DeadBugCamera";
import DeadBugStatsPanel from "../conponents/DeadBugStatsPanel";
import "../pages/BicepPage.css";
import "../pages/PlankHoldPage.css"; // reuses plank-viewfinder look — same lying-down framing
import "./DeadBugPage.css";

// MediaPipe pose connections relevant to a dead bug: torso + both arms +
// both legs, so the whole contralateral movement is visible.
const POSE_CONNECTIONS: [number, number][] = [
  [11, 12],
  [11, 13],
  [13, 15],
  [12, 14],
  [14, 16],
  [11, 23],
  [12, 24],
  [23, 24],
  [23, 25],
  [25, 27],
  [24, 26],
  [26, 28],
];

const REP_PRESETS = [6, 8, 10, 12];
const SET_PRESETS = [1, 2, 3, 4];
const REST_PRESETS = [20, 30, 45, 60];

type Phase = "setup" | "active" | "resting" | "complete";

interface SetSummary {
  setNumber: number;
  reps: number;
  rightArmLeftLeg: number;
  leftArmRightLeg: number;
  elapsedTime: number;
}

function DeadBugPage() {
  const navigate = useNavigate();

  const [repsPerSet, setRepsPerSet] = useState(8);
  const [totalSets, setTotalSets] = useState(3);
  const [restSeconds, setRestSeconds] = useState(30);

  const [phase, setPhase] = useState<Phase>("setup");
  const [currentSet, setCurrentSet] = useState(1);
  const [restRemaining, setRestRemaining] = useState(0);
  const [setSummaries, setSetSummaries] = useState<SetSummary[]>([]);
  const [cameraError, setCameraError] = useState<string | null>(null);

  const {
    connected,
    result,
    lastEvent,
    sendFrame,
    start,
    stop,
    socketError,
  } = useDeadBugSocket();

  const skeleton = result.landmarks?.length
    ? [{ points: result.landmarks, connections: POSE_CONNECTIONS }]
    : [];

  const currentReps = result.rep_count ?? 0;
  const progressPct = Math.min(
    100,
    (currentReps / Math.max(1, repsPerSet)) * 100,
  );

  // ---- advance a set once the BACKEND confirms this set's reps are done ----
  // `session_complete` is computed server-side (DeadBugAnalyzer._is_complete).
  // The frontend never derives this itself from currentReps/repsPerSet.
  useEffect(() => {
    if (phase !== "active" || !result.session_complete) return;

    stop();

    const summary: SetSummary = {
      setNumber: currentSet,
      reps: currentReps,
      rightArmLeftLeg: result.right_arm_left_leg_count ?? 0,
      leftArmRightLeg: result.left_arm_right_leg_count ?? 0,
      elapsedTime: result.elapsed_time ?? 0,
    };
    setSetSummaries((prev) => [...prev, summary]);

    if (result.exercise_complete) {
      setPhase("complete");
    } else {
      setRestRemaining(restSeconds);
      setPhase("resting");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    phase,
    result.session_complete,
    currentSet,
    totalSets,
    restSeconds,
    result,
    stop,
  ]);

  // ---- rest countdown between sets, then auto-start the next one ----
  useEffect(() => {
    if (phase !== "resting") return;

    if (restRemaining <= 0) {
      const nextSet = currentSet + 1;
      setCurrentSet(nextSet);
      setPhase("active");
      start({
        targetReps: repsPerSet,
        targetSets: totalSets,
        setNumber: nextSet,
      });
      return;
    }

    const timer = window.setTimeout(() => setRestRemaining((r) => r - 1), 1000);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, restRemaining, start, currentSet, repsPerSet, totalSets]);

  function handleStart() {
    setCameraError(null);
    setSetSummaries([]);
    setCurrentSet(1);
    setPhase("active");
    start({ targetReps: repsPerSet, targetSets: totalSets, setNumber: 1 });
  }

  function handleSkipRest() {
    setRestRemaining(0);
  }

  function handleEndSession() {
    stop();
    setPhase("complete");
  }

  function handleReset() {
    stop();
    setCameraError(null);
    setSetSummaries([]);
    setCurrentSet(1);
    setPhase("setup");
  }

  const elapsed = result.elapsed_time ?? 0;

  const totals = useMemo(() => {
    return setSummaries.reduce(
      (acc, s) => ({
        reps: acc.reps + s.reps,
        rl: acc.rl + s.rightArmLeftLeg,
        lr: acc.lr + s.leftArmRightLeg,
        time: acc.time + s.elapsedTime,
      }),
      { reps: 0, rl: 0, lr: 0, time: 0 },
    );
  }, [setSummaries]);

  const totalPlannedReps = repsPerSet * totalSets;

  return (
    // Same shared shell as the other exercises ("bicep-page ...") plus
    // PlankHoldPage.css's lying-down look (this page uses "plank-page"
    // too, since dead bug shares the same camera/panel framing).
    <div className="bicep-page plank-page dead-bug-page">
      <div className="bicep-header">
        <div className="bicep-header-left">
          <button
            className="plank-back-btn"
            onClick={() => navigate("/exercises")}
          >
            ← Library
          </button>
          <h1 className="bicep-title">Dead Bug Trainer</h1>
        </div>

        <div className="bicep-header-right">
          {phase === "active" && (
            <div className="active-controls">
              <span className={`status-dot ${connected ? "live" : ""}`} />
              <span className="active-label">
                Set {currentSet}/{totalSets} · {currentReps}/{repsPerSet} reps
              </span>
              <button className="stop-btn" onClick={handleEndSession}>
                End Session
              </button>
            </div>
          )}

          {phase === "resting" && (
            <div className="active-controls">
              <span className="active-label">
                Resting — next up: Set {currentSet + 1}/{totalSets}
              </span>
              <button className="stop-btn" onClick={handleEndSession}>
                End Session
              </button>
            </div>
          )}

          {phase === "complete" && (
            <div className="active-controls">
              <span className="complete-label">✅ Session complete</span>
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
          <DeadBugCamera
            active={phase === "active"}
            sendFrame={sendFrame}
            skeleton={skeleton}
            onError={setCameraError}
          />

          {phase === "resting" && (
            <div className="rest-overlay-caption">
              <span className="rest-countdown">{restRemaining}s</span>
              <span>until Set {currentSet + 1} starts</span>
            </div>
          )}

          {(phase === "active" || phase === "resting") && (
            <>
              <div className="progress-track">
                <div
                  className="progress-fill"
                  style={{
                    width: `${phase === "active" ? progressPct : 100}%`,
                  }}
                />
              </div>
              <div className="progress-caption">
                {phase === "active"
                  ? `${currentReps} / ${repsPerSet} reps`
                  : "Set complete — resting"}
              </div>

              <div className="set-dots">
                {Array.from({ length: totalSets }, (_, i) => i + 1).map((n) => (
                  <span
                    key={n}
                    className={`set-dot ${
                      n < currentSet ||
                      (n === currentSet && phase === "resting")
                        ? "done"
                        : n === currentSet
                          ? "current"
                          : ""
                    }`}
                  />
                ))}
              </div>

              <div className="session-summary">
                <div className="session-summary-item good">
                  <span className="k">R-arm/L-leg</span>
                  <span className="v">
                    {result.right_arm_left_leg_count ?? 0}
                  </span>
                </div>
                <div className="session-summary-item flawed">
                  <span className="k">L-arm/R-leg</span>
                  <span className="v">
                    {result.left_arm_right_leg_count ?? 0}
                  </span>
                </div>
                <div className="session-summary-item">
                  <span className="k">Elapsed</span>
                  <span className="v">{elapsed.toFixed(0)}s</span>
                </div>
              </div>
            </>
          )}
        </div>

        <div className="bicep-stats-col">
          {phase === "setup" && (
            <div className="session-builder">
              <div className="builder-row">
                <span className="builder-label">Reps per set</span>
                <div className="builder-controls">
                  <input
                    type="number"
                    min={1}
                    max={100}
                    value={repsPerSet}
                    onChange={(e) =>
                      setRepsPerSet(
                        Math.max(1, Math.min(100, Number(e.target.value) || 1)),
                      )
                    }
                    className="reps-input"
                  />
                  <div className="reps-presets">
                    {REP_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`reps-preset ${repsPerSet === n ? "active" : ""}`}
                        onClick={() => setRepsPerSet(n)}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="builder-row">
                <span className="builder-label">Number of sets</span>
                <div className="builder-controls">
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={totalSets}
                    onChange={(e) =>
                      setTotalSets(
                        Math.max(1, Math.min(20, Number(e.target.value) || 1)),
                      )
                    }
                    className="reps-input"
                  />
                  <div className="reps-presets">
                    {SET_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`reps-preset ${totalSets === n ? "active" : ""}`}
                        onClick={() => setTotalSets(n)}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="builder-row">
                <span className="builder-label">Rest between sets</span>
                <div className="builder-controls">
                  <div className="reps-presets">
                    {REST_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`reps-preset ${restSeconds === n ? "active" : ""}`}
                        onClick={() => setRestSeconds(n)}
                      >
                        {n}s
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="builder-total">
                {totalSets} × {repsPerSet} ={" "}
                <strong>{totalPlannedReps} reps total</strong>
              </div>

              <div className="plank-setup-tip">
                Lie on your back, sideways to the camera: knees stacked over
                hips, arms reaching straight up (tabletop). Reach one arm
                overhead and the <strong>opposite</strong> leg straight out
                together, keeping your lower back flat on the floor, then
                return to tabletop and switch sides. A rep only counts when
                the right arm + left leg (or left arm + right leg) move
                together, at a controlled pace, without your hips shifting —
                moving just one limb, both same-side limbs, all four limbs
                at once, or letting your back arch won't count.
              </div>

              <button className="start-btn full-width" onClick={handleStart}>
                Start Session ▶
              </button>
            </div>
          )}

          {phase === "resting" && (
            <div className="rest-panel">
              <div className="rest-panel-title">
                Set {currentSet} complete 🎉
              </div>
              <div className="rest-panel-big-countdown">{restRemaining}</div>
              <div className="rest-panel-caption">seconds of rest left</div>

              {setSummaries[setSummaries.length - 1] && (
                <div className="arm-grid rest-panel-grid">
                  <div className="arm-grid-item">
                    <span className="k">Reps</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].reps}
                    </span>
                  </div>
                  <div className="arm-grid-item">
                    <span className="k">R-arm/L-leg</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].rightArmLeftLeg}
                    </span>
                  </div>
                  <div className="arm-grid-item">
                    <span className="k">L-arm/R-leg</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].leftArmRightLeg}
                    </span>
                  </div>
                </div>
              )}

              <button className="stop-btn" onClick={handleSkipRest}>
                Skip rest
              </button>
            </div>
          )}

          {phase === "active" && (
            <div className="single-arm-wrap">
              <DeadBugStatsPanel data={result} />

              {(lastEvent.feedback || result.feedback) && (
                <div
                  className={`feedback-box ${lastEvent.kind === "invalid" ? "needs_improvement" : ""}`}
                >
                  <strong>Coach Feedback</strong>
                  <p>{lastEvent.feedback ?? result.feedback}</p>
                </div>
              )}
            </div>
          )}

          {phase === "complete" && (
            <div className="results-panel">
              <div className="results-totals">
                <div className="session-summary-item">
                  <span className="k">Sets</span>
                  <span className="v">{setSummaries.length}</span>
                </div>
                <div className="session-summary-item">
                  <span className="k">Total reps</span>
                  <span className="v">{totals.reps}</span>
                </div>
                <div className="session-summary-item good">
                  <span className="k">R-arm/L-leg</span>
                  <span className="v">{totals.rl}</span>
                </div>
                <div className="session-summary-item flawed">
                  <span className="k">L-arm/R-leg</span>
                  <span className="v">{totals.lr}</span>
                </div>
                <div className="session-summary-item">
                  <span className="k">Total time</span>
                  <span className="v">{totals.time.toFixed(0)}s</span>
                </div>
              </div>

              <div className="results-table">
                <div className="results-row results-head">
                  <span>Set</span>
                  <span>Reps</span>
                  <span>R/L</span>
                  <span>L/R</span>
                  <span>Time</span>
                </div>
                {setSummaries.map((s) => (
                  <div key={s.setNumber} className="results-row">
                    <span>{s.setNumber}</span>
                    <span>{s.reps}</span>
                    <span className="good-text">{s.rightArmLeftLeg}</span>
                    <span className="flawed-text">{s.leftArmRightLeg}</span>
                    <span>{s.elapsedTime.toFixed(0)}s</span>
                  </div>
                ))}
                {setSummaries.length === 0 && (
                  <div className="results-row">
                    <span className="empty-hint">
                      Session ended before any set finished.
                    </span>
                  </div>
                )}
              </div>

              <button
                className="start-btn full-width"
                onClick={() => navigate("/exercises")}
              >
                Back to Exercise Library
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default DeadBugPage;
