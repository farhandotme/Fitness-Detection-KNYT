import { useEffect, useMemo, useState } from "react";
import useCalfRaiseSocket from "../hooks/useCalfRaiseSocket";
import CalfRaiseCamera from "../conponents/CalfRaiseCamera";
import CalfRaiseStatsPanel from "../conponents/CalfRaiseStatsPanel";
import "./CalfRaisePage.css";

// Same 33-point BlazePose topology as the other pages' overlays.
const POSE_CONNECTIONS: [number, number][] = [
  [11, 12],
  [23, 24],
  [11, 23],
  [12, 24],
  [23, 25],
  [25, 27],
  [24, 26],
  [26, 28],
  [27, 29],
  [29, 31],
  [27, 31],
  [28, 30],
  [30, 32],
  [28, 32],
];

const REP_PRESETS = [10, 15, 20, 25];
const SET_PRESETS = [1, 2, 3, 4, 5];
const REST_PRESETS = [15, 20, 30, 45];

type Phase = "setup" | "active" | "resting" | "complete";

interface SetSummary {
  setNumber: number;
  reps: number;
  goodReps: number;
  flawedReps: number;
  elapsedTime: number;
}

function CalfRaisePage() {
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
    lastCompletedRep,
    sendFrame,
    start,
    stop,
    socketError,
  } = useCalfRaiseSocket();

  const skeleton = result.landmarks?.length
    ? [{ points: result.landmarks, connections: POSE_CONNECTIONS }]
    : [];

  const currentReps = result.rep_count ?? 0;
  const progressPct = Math.min(
    100,
    (currentReps / Math.max(1, repsPerSet)) * 100,
  );

  // ---- advance a set once the BACKEND confirms this set's reps are done ----
  // `session_complete` is computed server-side (CalfRaiseAnalyzer._is_complete),
  // from the target_reps the backend itself was given when the socket opened.
  // We never derive this from currentReps/repsPerSet on the client.
  useEffect(() => {
    if (phase !== "active" || !result.session_complete) return;

    stop();

    const summary: SetSummary = {
      setNumber: currentSet,
      reps: currentReps,
      goodReps: result.good_reps ?? 0,
      flawedReps: result.flawed_reps ?? 0,
      elapsedTime: result.elapsed_time ?? 0,
    };
    setSetSummaries((prev) => [...prev, summary]);

    // exercise_complete is also backend-validated: true only once every
    // set in the plan hit its target.
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

  const totals = useMemo(() => {
    return setSummaries.reduce(
      (acc, s) => ({
        reps: acc.reps + s.reps,
        good: acc.good + s.goodReps,
        flawed: acc.flawed + s.flawedReps,
        time: acc.time + s.elapsedTime,
      }),
      { reps: 0, good: 0, flawed: 0, time: 0 },
    );
  }, [setSummaries]);

  const totalPlannedReps = repsPerSet * totalSets;

  return (
    <div className="calf-page">
      <div className="calf-header">
        <h1 className="calf-title">Calf Raise Trainer</h1>

        {phase === "active" && (
          <div className="calf-active-controls">
            <span className={`calf-status-dot ${connected ? "live" : ""}`} />
            <span className="calf-active-label">
              Set {currentSet}/{totalSets} · {currentReps}/{repsPerSet} reps
            </span>
            <button className="calf-stop-btn" onClick={handleEndSession}>
              End Session
            </button>
          </div>
        )}

        {phase === "resting" && (
          <div className="calf-active-controls">
            <span className="calf-active-label">
              Resting — next up: Set {currentSet + 1}/{totalSets}
            </span>
            <button className="calf-stop-btn" onClick={handleEndSession}>
              End Session
            </button>
          </div>
        )}

        {phase === "complete" && (
          <div className="calf-active-controls">
            <span className="calf-complete-label">✅ Session complete</span>
            <button className="calf-start-btn" onClick={handleReset}>
              New Session
            </button>
          </div>
        )}
      </div>

      {socketError && <div className="calf-error">{socketError}</div>}
      {cameraError && <div className="calf-error">{cameraError}</div>}

      <div className="calf-body">
        <div className="calf-camera-col">
          <CalfRaiseCamera
            active={phase === "active"}
            sendFrame={sendFrame}
            skeleton={skeleton}
            onError={setCameraError}
          />

          {phase === "resting" && (
            <div className="calf-rest-overlay-caption">
              <span className="calf-rest-countdown">{restRemaining}s</span>
              <span>until Set {currentSet + 1} starts</span>
              <button className="calf-skip-rest-btn" onClick={handleSkipRest}>
                Skip rest
              </button>
            </div>
          )}

          {(phase === "active" || phase === "resting") && (
            <>
              <div className="calf-progress-track">
                <div
                  className="calf-progress-fill"
                  style={{
                    width: `${phase === "active" ? progressPct : 100}%`,
                  }}
                />
              </div>
              <div className="calf-progress-caption">
                {phase === "active"
                  ? `${currentReps} / ${repsPerSet} reps`
                  : "Set complete — resting"}
              </div>
            </>
          )}

          {lastCompletedRep.feedback && phase === "active" && (
            <div className="calf-feedback-box">{lastCompletedRep.feedback}</div>
          )}

          {phase === "setup" && (
            <p className="calf-setup-tip">
              Stand facing the camera, far enough back that your head and
              both feet are in frame. Keep your legs straight and rise onto
              your toes — squatting or bouncing won't be counted.
            </p>
          )}
        </div>

        <div className="calf-panel-col">
          {phase === "setup" && (
            <div className="calf-session-builder">
              <h2>Session plan</h2>

              <label>Reps per set</label>
              <div className="calf-preset-row">
                {REP_PRESETS.map((n) => (
                  <button
                    key={n}
                    className={repsPerSet === n ? "selected" : ""}
                    onClick={() => setRepsPerSet(n)}
                  >
                    {n}
                  </button>
                ))}
              </div>

              <label>Sets</label>
              <div className="calf-preset-row">
                {SET_PRESETS.map((n) => (
                  <button
                    key={n}
                    className={totalSets === n ? "selected" : ""}
                    onClick={() => setTotalSets(n)}
                  >
                    {n}
                  </button>
                ))}
              </div>

              <label>Rest between sets</label>
              <div className="calf-preset-row">
                {REST_PRESETS.map((n) => (
                  <button
                    key={n}
                    className={restSeconds === n ? "selected" : ""}
                    onClick={() => setRestSeconds(n)}
                  >
                    {n}s
                  </button>
                ))}
              </div>

              <p className="calf-plan-summary">
                {totalSets} × {repsPerSet} reps ({totalPlannedReps} total)
              </p>

              <button className="calf-start-btn calf-start-btn-lg" onClick={handleStart}>
                Start
              </button>
            </div>
          )}

          {(phase === "active" || phase === "resting") && (
            <CalfRaiseStatsPanel data={result} />
          )}

          {phase === "complete" && (
            <div className="calf-results-panel">
              <h2>Session summary</h2>
              <div className="calf-results-total">
                {totals.reps} reps · {totals.good} good · {totals.flawed}{" "}
                flawed
              </div>
              <table className="calf-results-table">
                <thead>
                  <tr>
                    <th>Set</th>
                    <th>Reps</th>
                    <th>Good</th>
                    <th>Flawed</th>
                    <th>Time</th>
                  </tr>
                </thead>
                <tbody>
                  {setSummaries.map((s) => (
                    <tr key={s.setNumber}>
                      <td>{s.setNumber}</td>
                      <td>{s.reps}</td>
                      <td>{s.goodReps}</td>
                      <td>{s.flawedReps}</td>
                      <td>{s.elapsedTime.toFixed(1)}s</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default CalfRaisePage;
