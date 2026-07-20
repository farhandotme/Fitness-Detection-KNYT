import { useEffect, useMemo, useState } from "react";
import useJabSocket from "../hooks/useJabSocket";
import JabCamera from "../conponents/JabCamera";
import JabStatsPanel from "../conponents/JabStatsPanel";
import "./JabPage.css";

// MediaPipe pose connections relevant to a jab: shoulders, arms, hips.
const POSE_CONNECTIONS: [number, number][] = [
  [11, 13],
  [13, 15],
  [12, 14],
  [14, 16],
  [11, 12],
  [23, 24],
  [11, 23],
  [12, 24],
];

const REP_PRESETS = [10, 15, 20, 30];
const SET_PRESETS = [1, 2, 3, 4, 5];
const REST_PRESETS = [15, 20, 30, 45];

type Phase = "setup" | "active" | "resting" | "complete";

interface SetSummary {
  setNumber: number;
  reps: number;
  leftCount: number;
  rightCount: number;
  elapsedTime: number;
}

function JabPage() {
  const [repsPerSet, setRepsPerSet] = useState(15);
  const [totalSets, setTotalSets] = useState(3);
  const [restSeconds, setRestSeconds] = useState(20);

  const [phase, setPhase] = useState<Phase>("setup");
  const [currentSet, setCurrentSet] = useState(1);
  const [restRemaining, setRestRemaining] = useState(0);
  const [setSummaries, setSetSummaries] = useState<SetSummary[]>([]);
  const [cameraError, setCameraError] = useState<string | null>(null);

  const {
    connected,
    result,
    lastCompletedPunch,
    sendFrame,
    start,
    stop,
    socketError,
  } = useJabSocket();

  const skeleton = result.landmarks?.length
    ? [{ points: result.landmarks, connections: POSE_CONNECTIONS }]
    : [];

  const currentReps = result.rep_count ?? 0;
  const progressPct = Math.min(
    100,
    (currentReps / Math.max(1, repsPerSet)) * 100,
  );

  // ---- advance a set once the BACKEND confirms this set's reps are done ----
  // `session_complete` is computed server-side (JabAnalyzer._is_complete).
  // The frontend never derives this itself from currentReps/repsPerSet.
  useEffect(() => {
    if (phase !== "active" || !result.session_complete) return;

    stop();

    const summary: SetSummary = {
      setNumber: currentSet,
      reps: currentReps,
      leftCount: result.left_count ?? 0,
      rightCount: result.right_count ?? 0,
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

  const sessionLeft = result.left_count ?? 0;
  const sessionRight = result.right_count ?? 0;
  const elapsed = result.elapsed_time ?? 0;

  const totals = useMemo(() => {
    return setSummaries.reduce(
      (acc, s) => ({
        reps: acc.reps + s.reps,
        left: acc.left + s.leftCount,
        right: acc.right + s.rightCount,
        time: acc.time + s.elapsedTime,
      }),
      { reps: 0, left: 0, right: 0, time: 0 },
    );
  }, [setSummaries]);

  const totalPlannedReps = repsPerSet * totalSets;

  return (
    <div className="jab-page">
      <div className="jab-header">
        <div className="jab-header-left">
          <h1 className="jab-title">Muay Thai Jab Trainer</h1>
        </div>

        <div className="jab-header-right">
          {phase === "active" && (
            <div className="active-controls">
              <span className={`status-dot ${connected ? "live" : ""}`} />
              <span className="active-label">
                Set {currentSet}/{totalSets} · {currentReps}/{repsPerSet} jabs
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

      {socketError && <div className="jab-error">{socketError}</div>}
      {cameraError && <div className="jab-error">{cameraError}</div>}

      <div className="jab-body">
        <div className="jab-camera-col">
          <JabCamera
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
                  ? `${currentReps} / ${repsPerSet} jabs`
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
                  <span className="k">Left</span>
                  <span className="v">{sessionLeft}</span>
                </div>
                <div className="session-summary-item flawed">
                  <span className="k">Right</span>
                  <span className="v">{sessionRight}</span>
                </div>
                <div className="session-summary-item">
                  <span className="k">Elapsed</span>
                  <span className="v">{elapsed.toFixed(0)}s</span>
                </div>
              </div>
            </>
          )}
        </div>

        <div className="jab-stats-col">
          {phase === "setup" && (
            <div className="session-builder">
              <div className="builder-row">
                <span className="builder-label">Jabs per set</span>
                <div className="builder-controls">
                  <input
                    type="number"
                    min={1}
                    max={200}
                    value={repsPerSet}
                    onChange={(e) =>
                      setRepsPerSet(
                        Math.max(1, Math.min(200, Number(e.target.value) || 1)),
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
                <strong>{totalPlannedReps} jabs total</strong>
              </div>

              <div className="jab-setup-tip">
                Stand facing the camera in a boxing stance: feet shoulder-width
                apart, hands up near your chin. Throw a jab by snapping your arm
                straight out and pulling it right back to guard — reps only
                count once a real jab (guard → full extension → guard) is
                confirmed, from either hand.
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
                    <span className="k">Jabs</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].reps}
                    </span>
                  </div>
                  <div className="arm-grid-item">
                    <span className="k">Left</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].leftCount}
                    </span>
                  </div>
                  <div className="arm-grid-item">
                    <span className="k">Right</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].rightCount}
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
              <JabStatsPanel data={result} />

              {(lastCompletedPunch.feedback || result.feedback) && (
                <div className="feedback-box">
                  <strong>Coach Feedback</strong>
                  <p>{lastCompletedPunch.feedback ?? result.feedback}</p>
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
                  <span className="k">Total jabs</span>
                  <span className="v">{totals.reps}</span>
                </div>
                <div className="session-summary-item good">
                  <span className="k">Left</span>
                  <span className="v">{totals.left}</span>
                </div>
                <div className="session-summary-item flawed">
                  <span className="k">Right</span>
                  <span className="v">{totals.right}</span>
                </div>
                <div className="session-summary-item">
                  <span className="k">Total time</span>
                  <span className="v">{totals.time.toFixed(0)}s</span>
                </div>
              </div>

              <div className="results-table">
                <div className="results-row results-head">
                  <span>Set</span>
                  <span>Jabs</span>
                  <span>Left</span>
                  <span>Right</span>
                  <span>Time</span>
                </div>
                {setSummaries.map((s) => (
                  <div key={s.setNumber} className="results-row">
                    <span>{s.setNumber}</span>
                    <span>{s.reps}</span>
                    <span className="good-text">{s.leftCount}</span>
                    <span className="flawed-text">{s.rightCount}</span>
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
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default JabPage;
