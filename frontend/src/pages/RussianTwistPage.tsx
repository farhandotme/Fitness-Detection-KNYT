import { useEffect, useMemo, useState } from "react";
import useRussianTwistSocket from "../hooks/useRussianTwistSocket";
import RussianTwistCamera from "../conponents/RussianTwistCamera";
import RussianTwistStatsPanel from "../conponents/RussianTwistStatsPanel";
import "./RussianTwistPage.css";

const POSE_CONNECTIONS: [number, number][] = [
  [11, 12], // shoulder line
  [23, 24], // hip line
  [11, 23],
  [12, 24],
  [23, 25],
  [25, 27],
  [24, 26],
  [26, 28],
];

const REP_PRESETS = [10, 16, 20, 30];
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

function RussianTwistPage() {
  const [repsPerSet, setRepsPerSet] = useState(20);
  const [totalSets, setTotalSets] = useState(3);
  const [restSeconds, setRestSeconds] = useState(20);

  const [phase, setPhase] = useState<Phase>("setup");
  const [currentSet, setCurrentSet] = useState(1);
  const [restRemaining, setRestRemaining] = useState(0);
  const [setSummaries, setSetSummaries] = useState<SetSummary[]>([]);
  const [cameraError, setCameraError] = useState<string | null>(null);

  const { connected, result, lastEvent, sendFrame, start, stop, socketError } =
    useRussianTwistSocket();

  const skeleton = result.landmarks?.length
    ? [{ points: result.landmarks, connections: POSE_CONNECTIONS }]
    : [];

  const currentReps = result.rep_count ?? 0;
  const progressPct = Math.min(
    100,
    (currentReps / Math.max(1, repsPerSet)) * 100,
  );

  // ---- advance a set once the BACKEND confirms this set's reps are done ----
  // `session_complete` is computed server-side (RussianTwistAnalyzer._is_complete),
  // from the target_reps the backend itself was given when the socket opened.
  // We never derive this from currentReps/repsPerSet on the client.
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

    // exercise_complete is also backend-validated: true only once every
    // set in the plan hit its target. This is the boolean that should
    // trigger persisting "user completed this exercise" to the database.
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

  // ---- persist completion once the backend confirms the whole plan is done ----
  useEffect(() => {
    if (!result.exercise_complete) return;
    // TODO: wire this up to the real backend endpoint once it exists, e.g.
    //   POST /api/workouts/complete { exercise: "russian_twist", repsPerSet, totalSets }
    // That endpoint is what should write the "user completed this exercise"
    // record to MongoDB. The frontend must only ever send what the backend
    // already validated here (exercise_complete === true) — it must not
    // decide completion on its own.
    console.log(
      "Exercise completed (backend-validated) — ready to persist to DB.",
    );
  }, [result.exercise_complete]);

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
    <div className="rtwist-page">
      <div className="rtwist-header">
        <div className="rtwist-header-left">
          <h1 className="rtwist-title">Russian Twist Trainer</h1>
        </div>

        <div className="rtwist-header-right">
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

      {socketError && <div className="rtwist-error">{socketError}</div>}
      {cameraError && <div className="rtwist-error">{cameraError}</div>}

      <div className="rtwist-body">
        <div className="rtwist-camera-col">
          <RussianTwistCamera
            active={phase === "active"}
            sendFrame={sendFrame}
            skeleton={skeleton}
            onError={setCameraError}
          />

          {phase === "active" && (
            <>
              <div className="rtwist-progress-track">
                <div
                  className="rtwist-progress-fill"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
              <div className="rtwist-summary-row">
                <div className="session-summary-item">
                  <span className="k">Left</span>
                  <span className="v">{sessionLeft}</span>
                </div>
                <div className="session-summary-item">
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

        <div className="rtwist-stats-col">
          {phase === "setup" && (
            // TODO(coach-assignment): once a coach/plan API exists, repsPerSet
            // and totalSets should come from the user's assigned plan (fetched
            // here) and this picker should become read-only display, not
            // user-editable inputs. Whatever value is picked here is what
            // actually gets sent to the backend as target_reps/target_sets —
            // and the backend (not this component) decides when it's been met.
            <div className="session-builder">
              <div className="builder-row">
                <span className="builder-label">Reps per set (left+right)</span>
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
                <strong>{totalPlannedReps} reps total</strong>
              </div>

              <div className="rtwist-setup-tip">
                Sit on the floor or a mat, lean back slightly, bend your knees,
                and face the camera. Rotate your torso side to side — each rep
                only counts once you rotate clearly to one side, pass back
                through center, then rotate to the other side.
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
              <RussianTwistStatsPanel data={result} />

              {(lastEvent.feedback || result.feedback) && (
                <div
                  className={`feedback-box ${lastEvent.wasFullRep ? "good" : ""}`}
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
                <div className="session-summary-item">
                  <span className="k">Left</span>
                  <span className="v">{totals.left}</span>
                </div>
                <div className="session-summary-item">
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
                  <span>Reps</span>
                  <span>Left</span>
                  <span>Right</span>
                  <span>Time</span>
                </div>
                {setSummaries.map((s) => (
                  <div key={s.setNumber} className="results-row">
                    <span>{s.setNumber}</span>
                    <span>{s.reps}</span>
                    <span>{s.leftCount}</span>
                    <span>{s.rightCount}</span>
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

export default RussianTwistPage;
