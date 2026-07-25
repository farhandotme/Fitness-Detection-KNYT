import { useEffect, useMemo, useState } from "react";
import useButtKicksSocket from "../hooks/useButtKicksSocket";
import ButtKicksCamera from "../conponents/ButtKicksCamera";
import ButtKicksStatsPanel from "../conponents/ButtKicksStatsPanel";
import "./ButtKicksPage.css";

const POSE_CONNECTIONS: [number, number][] = [
  [11, 12],
  [11, 23],
  [12, 24],
  [23, 24],
  [23, 25],
  [25, 27],
  [27, 29],
  [24, 26],
  [26, 28],
  [28, 30],
];

const REP_PRESETS = [10, 20, 30, 40];
const SET_PRESETS = [1, 2, 3, 4, 5];
const REST_PRESETS = [15, 20, 30, 45];

type Phase = "setup" | "active" | "resting" | "complete";

interface SetSummary {
  setNumber: number;
  reps: number;
  leftReps: number;
  rightReps: number;
  goodReps: number;
  flawedReps: number;
  elapsedTime: number;
}

function ButtKicksPage() {
  const [repsPerSet, setRepsPerSet] = useState(20);
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
  } = useButtKicksSocket();

  const skeleton = result.landmarks?.length
    ? [{ points: result.landmarks, connections: POSE_CONNECTIONS }]
    : [];

  const currentReps = result.rep_count ?? 0;
  const progressPct = Math.min(
    100,
    (currentReps / Math.max(1, repsPerSet)) * 100,
  );

  // ---- advance a set once the BACKEND confirms this set's reps are done ----
  // `session_complete` is computed server-side (ButtKicksAnalyzer._is_complete),
  // from the target_reps the backend itself was given when the socket opened.
  // We never derive this from currentReps/repsPerSet on the client.
  useEffect(() => {
    if (phase !== "active" || !result.session_complete) return;

    stop();

    const summary: SetSummary = {
      setNumber: currentSet,
      reps: currentReps,
      leftReps: result.left_reps ?? 0,
      rightReps: result.right_reps ?? 0,
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

  // ---- persist completion once the backend confirms the whole plan is done ----
  useEffect(() => {
    if (!result.exercise_complete) return;
    // TODO: wire this up to the real backend endpoint once it exists, e.g.
    //   POST /api/workouts/complete { exercise: "butt_kicks", repsPerSet, totalSets }
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

  const sessionGood = result.good_reps ?? 0;
  const sessionFlawed = result.flawed_reps ?? 0;
  const elapsed = result.elapsed_time ?? 0;

  const totals = useMemo(() => {
    return setSummaries.reduce(
      (acc, s) => ({
        reps: acc.reps + s.reps,
        left: acc.left + s.leftReps,
        right: acc.right + s.rightReps,
        good: acc.good + s.goodReps,
        flawed: acc.flawed + s.flawedReps,
        time: acc.time + s.elapsedTime,
      }),
      { reps: 0, left: 0, right: 0, good: 0, flawed: 0, time: 0 },
    );
  }, [setSummaries]);

  const totalPlannedReps = repsPerSet * totalSets;

  return (
    <div className="bk-page">
      <div className="bk-header">
        <div className="bk-header-left">
          <h1 className="bk-title">Butt Kicks Trainer</h1>
        </div>

        <div className="bk-header-right">
          {phase === "active" && (
            <div className="bk-active-controls">
              <span className={`bk-status-dot ${connected ? "live" : ""}`} />
              <span className="bk-active-label">
                Set {currentSet}/{totalSets} · {currentReps}/{repsPerSet} reps
              </span>
              <button className="bk-stop-btn" onClick={handleEndSession}>
                End Session
              </button>
            </div>
          )}

          {phase === "resting" && (
            <div className="bk-active-controls">
              <span className="bk-active-label">
                Resting — next up: Set {currentSet + 1}/{totalSets}
              </span>
              <button className="bk-stop-btn" onClick={handleEndSession}>
                End Session
              </button>
            </div>
          )}

          {phase === "complete" && (
            <div className="bk-active-controls">
              <span className="bk-complete-label">✅ Session complete</span>
              <button className="bk-start-btn" onClick={handleReset}>
                New Session
              </button>
            </div>
          )}
        </div>
      </div>

      {socketError && <div className="bk-error">{socketError}</div>}
      {cameraError && <div className="bk-error">{cameraError}</div>}

      <div className="bk-body">
        <div className="bk-camera-col">
          <ButtKicksCamera
            active={phase === "active"}
            sendFrame={sendFrame}
            skeleton={skeleton}
            onError={setCameraError}
          />

          {phase === "resting" && (
            <div className="bk-rest-overlay-caption">
              <span className="bk-rest-countdown">{restRemaining}s</span>
              <span>until Set {currentSet + 1} starts</span>
            </div>
          )}

          {(phase === "active" || phase === "resting") && (
            <>
              <div className="bk-progress-track">
                <div
                  className="bk-progress-fill"
                  style={{
                    width: `${phase === "active" ? progressPct : 100}%`,
                  }}
                />
              </div>
              <div className="bk-progress-caption">
                {phase === "active"
                  ? `${currentReps} / ${repsPerSet} reps`
                  : "Set complete — resting"}
              </div>

              <div className="bk-set-dots">
                {Array.from({ length: totalSets }, (_, i) => i + 1).map((n) => (
                  <span
                    key={n}
                    className={`bk-set-dot ${
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

              <div className="bk-session-summary">
                <div className="bk-session-summary-item">
                  <span className="k">Left</span>
                  <span className="v">{result.left_reps ?? 0}</span>
                </div>
                <div className="bk-session-summary-item">
                  <span className="k">Right</span>
                  <span className="v">{result.right_reps ?? 0}</span>
                </div>
                <div className="bk-session-summary-item good">
                  <span className="k">Good</span>
                  <span className="v">{sessionGood}</span>
                </div>
                <div className="bk-session-summary-item flawed">
                  <span className="k">Flawed</span>
                  <span className="v">{sessionFlawed}</span>
                </div>
                <div className="bk-session-summary-item">
                  <span className="k">Elapsed</span>
                  <span className="v">{elapsed.toFixed(0)}s</span>
                </div>
              </div>
            </>
          )}
        </div>

        <div className="bk-stats-col">
          {phase === "setup" && (
            <div className="bk-session-builder">
              <div className="bk-instruction-panel">
                <div className="bk-instruction-title">How to butt kick</div>
                <ul>
                  <li>Stand tall.</li>
                  <li>Kick your heels toward your glutes.</li>
                  <li>Alternate quickly.</li>
                  <li>Keep your chest up.</li>
                </ul>
                <p className="bk-instruction-note">
                  This is a fast cardio drill, not a static pose — go as quick
                  as you can while alternating legs. The tracker is built to
                  keep up.
                </p>
              </div>

              <div className="bk-builder-row">
                <span className="bk-builder-label">Reps per set</span>
                <div className="bk-builder-controls">
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
                    className="bk-reps-input"
                  />
                  <div className="bk-reps-presets">
                    {REP_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`bk-reps-preset ${repsPerSet === n ? "active" : ""}`}
                        onClick={() => setRepsPerSet(n)}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="bk-builder-row">
                <span className="bk-builder-label">Number of sets</span>
                <div className="bk-builder-controls">
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
                    className="bk-reps-input"
                  />
                  <div className="bk-reps-presets">
                    {SET_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`bk-reps-preset ${totalSets === n ? "active" : ""}`}
                        onClick={() => setTotalSets(n)}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="bk-builder-row">
                <span className="bk-builder-label">Rest between sets</span>
                <div className="bk-builder-controls">
                  <div className="bk-reps-presets">
                    {REST_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`bk-reps-preset ${restSeconds === n ? "active" : ""}`}
                        onClick={() => setRestSeconds(n)}
                      >
                        {n}s
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="bk-builder-total">
                {totalSets} × {repsPerSet} ={" "}
                <strong>{totalPlannedReps} reps total</strong>
              </div>

              <div className="bk-setup-tip">
                Stand where the camera can see your full lower body — both
                knees, both ankles, and at least part of your torso. Reps count
                from a clear heel-to-glute kick and don't require a pause at the
                top — go fast, the tracker favors counting every real kick over
                strict form.
              </div>

              <button className="bk-start-btn full-width" onClick={handleStart}>
                Start Session ▶
              </button>
            </div>
          )}

          {phase === "resting" && (
            <div className="bk-rest-panel">
              <div className="bk-rest-panel-title">
                Set {currentSet} complete 🎉
              </div>
              <div className="bk-rest-panel-big-countdown">{restRemaining}</div>
              <div className="bk-rest-panel-caption">seconds of rest left</div>

              {setSummaries[setSummaries.length - 1] && (
                <div className="bk-grid bk-rest-panel-grid">
                  <div className="bk-grid-item">
                    <span className="k">Reps</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].reps}
                    </span>
                  </div>
                  <div className="bk-grid-item">
                    <span className="k">Left / Right</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].leftReps} /{" "}
                      {setSummaries[setSummaries.length - 1].rightReps}
                    </span>
                  </div>
                  <div className="bk-grid-item">
                    <span className="k">Good</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].goodReps}
                    </span>
                  </div>
                  <div className="bk-grid-item">
                    <span className="k">Flawed</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].flawedReps}
                    </span>
                  </div>
                </div>
              )}

              <button className="bk-stop-btn" onClick={handleSkipRest}>
                Skip rest
              </button>
            </div>
          )}

          {phase === "active" && (
            <div className="bk-active-wrap">
              <ButtKicksStatsPanel data={result} />

              {(lastCompletedRep.feedback || result.feedback) && (
                <div
                  className={`bk-feedback-box ${lastCompletedRep.rep_form_quality ?? ""}`}
                >
                  <strong>Coach Feedback</strong>
                  <p>{lastCompletedRep.feedback ?? result.feedback}</p>
                </div>
              )}

              {!result.framing_ok && result.framing_message && (
                <div className="bk-feedback-box warn">
                  <strong>Framing</strong>
                  <p>{result.framing_message}</p>
                </div>
              )}
            </div>
          )}

          {phase === "complete" && (
            <div className="bk-results-panel">
              <div className="bk-results-totals">
                <div className="bk-session-summary-item">
                  <span className="k">Sets</span>
                  <span className="v">{setSummaries.length}</span>
                </div>
                <div className="bk-session-summary-item">
                  <span className="k">Total reps</span>
                  <span className="v">{totals.reps}</span>
                </div>
                <div className="bk-session-summary-item">
                  <span className="k">Left / Right</span>
                  <span className="v">
                    {totals.left} / {totals.right}
                  </span>
                </div>
                <div className="bk-session-summary-item good">
                  <span className="k">Good</span>
                  <span className="v">{totals.good}</span>
                </div>
                <div className="bk-session-summary-item flawed">
                  <span className="k">Flawed</span>
                  <span className="v">{totals.flawed}</span>
                </div>
                <div className="bk-session-summary-item">
                  <span className="k">Total time</span>
                  <span className="v">{totals.time.toFixed(0)}s</span>
                </div>
              </div>

              <div className="bk-results-table">
                <div className="bk-results-row bk-results-head">
                  <span>Set</span>
                  <span>Reps</span>
                  <span>L/R</span>
                  <span>Good</span>
                  <span>Flawed</span>
                  <span>Time</span>
                </div>
                {setSummaries.map((s) => (
                  <div key={s.setNumber} className="bk-results-row">
                    <span>{s.setNumber}</span>
                    <span>{s.reps}</span>
                    <span>
                      {s.leftReps}/{s.rightReps}
                    </span>
                    <span className="good-text">{s.goodReps}</span>
                    <span className="flawed-text">{s.flawedReps}</span>
                    <span>{s.elapsedTime.toFixed(0)}s</span>
                  </div>
                ))}
                {setSummaries.length === 0 && (
                  <div className="bk-results-row">
                    <span className="bk-empty-hint">
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

export default ButtKicksPage;
