import { useEffect, useMemo, useState } from "react";
import useHinduPushupSocket from "../hooks/useHinduPushupSocket";
import HinduPushupCamera from "../conponents/HinduPushupCamera";
import HinduPushupStatsPanel from "../conponents/HinduPushupStatsPanel";
import "./HinduPushupPage.css";

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

const REP_PRESETS = [5, 8, 10, 15];
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

function HinduPushupPage() {
  const [repsPerSet, setRepsPerSet] = useState(8);
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
  } = useHinduPushupSocket();

  const skeleton = result.landmarks?.length
    ? [{ points: result.landmarks, connections: POSE_CONNECTIONS }]
    : [];

  const currentReps = result.rep_count ?? 0;
  const progressPct = Math.min(100, (currentReps / Math.max(1, repsPerSet)) * 100);

  // ---- advance a set once the BACKEND confirms this set's reps are done ----
  // `session_complete` is computed server-side (HinduPushupAnalyzer._is_complete)
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

    if (result.exercise_complete) {
      setPhase("complete");
    } else {
      setRestRemaining(restSeconds);
      setPhase("resting");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, result.session_complete, currentSet, totalSets, restSeconds, result, stop]);

  // ---- persist completion once the backend confirms the whole plan is done ----
  useEffect(() => {
    if (!result.exercise_complete) return;
    // TODO: wire this up to the real backend endpoint once it exists, e.g.
    //   POST /api/workouts/complete { exercise: "hindu_pushup", repsPerSet, totalSets }
    // The frontend must only ever send what the backend already validated
    // here (exercise_complete === true) — it must not decide completion on
    // its own.
    console.log("Hindu push-up exercise completed (backend-validated).");
  }, [result.exercise_complete]);

  // ---- rest countdown between sets, then auto-start the next one ----
  useEffect(() => {
    if (phase !== "resting") return;

    if (restRemaining <= 0) {
      const nextSet = currentSet + 1;
      setCurrentSet(nextSet);
      setPhase("active");
      start({ targetReps: repsPerSet, targetSets: totalSets, setNumber: nextSet });
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
        good: acc.good + s.goodReps,
        flawed: acc.flawed + s.flawedReps,
        time: acc.time + s.elapsedTime,
      }),
      { reps: 0, good: 0, flawed: 0, time: 0 },
    );
  }, [setSummaries]);

  const totalPlannedReps = repsPerSet * totalSets;

  return (
    <div className="hindu-page">
      <div className="hindu-header">
        <div className="hindu-header-left">
          <h1 className="hindu-title">Hindu Push-up Trainer</h1>
        </div>

        <div className="hindu-header-right">
          {phase === "active" && (
            <div className="hindu-active-controls">
              <span className={`hindu-status-dot ${connected ? "live" : ""}`} />
              <span className="hindu-active-label">
                Set {currentSet}/{totalSets} · {currentReps}/{repsPerSet} reps
              </span>
              <button className="hindu-stop-btn" onClick={handleEndSession}>
                End Session
              </button>
            </div>
          )}

          {phase === "resting" && (
            <div className="hindu-active-controls">
              <span className="hindu-active-label">
                Resting — next up: Set {currentSet + 1}/{totalSets}
              </span>
              <button className="hindu-stop-btn" onClick={handleEndSession}>
                End Session
              </button>
            </div>
          )}

          {phase === "complete" && (
            <div className="hindu-active-controls">
              <span className="hindu-complete-label">✅ Session complete</span>
              <button className="hindu-start-btn" onClick={handleReset}>
                New Session
              </button>
            </div>
          )}
        </div>
      </div>

      {socketError && <div className="hindu-error">{socketError}</div>}
      {cameraError && <div className="hindu-error">{cameraError}</div>}

      <div className="hindu-body">
        <div className="hindu-camera-col">
          <HinduPushupCamera
            active={phase === "active"}
            sendFrame={sendFrame}
            skeleton={skeleton}
            onError={setCameraError}
          />

          {phase === "resting" && (
            <div className="hindu-rest-overlay-caption">
              <span className="hindu-rest-countdown">{restRemaining}s</span>
              <span>until Set {currentSet + 1} starts</span>
            </div>
          )}

          {(phase === "active" || phase === "resting") && (
            <>
              <div className="hindu-progress-track">
                <div
                  className="hindu-progress-fill"
                  style={{ width: `${phase === "active" ? progressPct : 100}%` }}
                />
              </div>
              <div className="hindu-progress-caption">
                {phase === "active"
                  ? `${currentReps} / ${repsPerSet} reps`
                  : "Set complete — resting"}
              </div>

              <div className="hindu-set-dots">
                {Array.from({ length: totalSets }, (_, i) => i + 1).map((n) => (
                  <span
                    key={n}
                    className={`hindu-set-dot ${
                      n < currentSet || (n === currentSet && phase === "resting")
                        ? "done"
                        : n === currentSet
                          ? "current"
                          : ""
                    }`}
                  />
                ))}
              </div>

              <div className="hindu-session-summary">
                <div className="hindu-session-summary-item good">
                  <span className="k">Good</span>
                  <span className="v">{sessionGood}</span>
                </div>
                <div className="hindu-session-summary-item flawed">
                  <span className="k">Flawed</span>
                  <span className="v">{sessionFlawed}</span>
                </div>
                <div className="hindu-session-summary-item">
                  <span className="k">Elapsed</span>
                  <span className="v">{elapsed.toFixed(0)}s</span>
                </div>
              </div>
            </>
          )}
        </div>

        <div className="hindu-stats-col">
          {phase === "setup" && (
            // TODO(coach-assignment): once a coach/plan API exists, repsPerSet
            // and totalSets should come from the user's assigned plan and this
            // picker should become read-only. Whatever's picked here is what
            // actually gets sent to the backend as target_reps/target_sets —
            // the backend (not this component) decides when it's been met.
            <div className="hindu-session-builder">
              <div className="hindu-builder-row">
                <span className="hindu-builder-label">Reps per set</span>
                <div className="hindu-builder-controls">
                  <input
                    type="number"
                    min={1}
                    max={100}
                    value={repsPerSet}
                    onChange={(e) =>
                      setRepsPerSet(Math.max(1, Math.min(100, Number(e.target.value) || 1)))
                    }
                    className="hindu-reps-input"
                  />
                  <div className="hindu-reps-presets">
                    {REP_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`hindu-reps-preset ${repsPerSet === n ? "active" : ""}`}
                        onClick={() => setRepsPerSet(n)}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="hindu-builder-row">
                <span className="hindu-builder-label">Number of sets</span>
                <div className="hindu-builder-controls">
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={totalSets}
                    onChange={(e) =>
                      setTotalSets(Math.max(1, Math.min(20, Number(e.target.value) || 1)))
                    }
                    className="hindu-reps-input"
                  />
                  <div className="hindu-reps-presets">
                    {SET_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`hindu-reps-preset ${totalSets === n ? "active" : ""}`}
                        onClick={() => setTotalSets(n)}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="hindu-builder-row">
                <span className="hindu-builder-label">Rest between sets</span>
                <div className="hindu-builder-controls">
                  <div className="hindu-reps-presets">
                    {REST_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`hindu-reps-preset ${restSeconds === n ? "active" : ""}`}
                        onClick={() => setRestSeconds(n)}
                      >
                        {n}s
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="hindu-builder-total">
                {totalSets} × {repsPerSet} = <strong>{totalPlannedReps} reps total</strong>
              </div>

              <div className="hindu-setup-tip">
                Start in Downward Dog: hands and feet on the floor, hips
                pushed up high, arms straight. Dive forward and down, skim
                low over the floor, then sweep up into Cobra — hips low,
                chest and head lifted, arms straight again. Reverse back to
                Downward Dog to complete one rep. Camera must be positioned
                to your <strong>side</strong> — a front-on view can't track
                the arc.
              </div>

              <button className="hindu-start-btn full-width" onClick={handleStart}>
                Start Session ▶
              </button>
            </div>
          )}

          {phase === "resting" && (
            <div className="hindu-rest-panel">
              <div className="hindu-rest-panel-title">Set {currentSet} complete 🎉</div>
              <div className="hindu-rest-panel-big-countdown">{restRemaining}</div>
              <div className="hindu-rest-panel-caption">seconds of rest left</div>

              {setSummaries[setSummaries.length - 1] && (
                <div className="hindu-arm-grid hindu-rest-panel-grid">
                  <div className="hindu-arm-grid-item">
                    <span className="k">Reps</span>
                    <span className="v">{setSummaries[setSummaries.length - 1].reps}</span>
                  </div>
                  <div className="hindu-arm-grid-item">
                    <span className="k">Good</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].goodReps}
                    </span>
                  </div>
                  <div className="hindu-arm-grid-item">
                    <span className="k">Flawed</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].flawedReps}
                    </span>
                  </div>
                </div>
              )}

              <button className="hindu-stop-btn" onClick={handleSkipRest}>
                Skip rest
              </button>
            </div>
          )}

          {phase === "active" && (
            <div className="hindu-single-arm-wrap">
              <HinduPushupStatsPanel data={result} />

              {(lastCompletedRep.feedback || result.feedback) && (
                <div
                  className={`hindu-feedback-box ${lastCompletedRep.rep_form_quality ?? ""}`}
                >
                  <strong>Coach Feedback</strong>
                  <p>{lastCompletedRep.feedback ?? result.feedback}</p>
                </div>
              )}
            </div>
          )}

          {phase === "complete" && (
            <div className="hindu-results-panel">
              <div className="hindu-results-totals">
                <div className="hindu-session-summary-item">
                  <span className="k">Sets</span>
                  <span className="v">{setSummaries.length}</span>
                </div>
                <div className="hindu-session-summary-item">
                  <span className="k">Total reps</span>
                  <span className="v">{totals.reps}</span>
                </div>
                <div className="hindu-session-summary-item good">
                  <span className="k">Good</span>
                  <span className="v">{totals.good}</span>
                </div>
                <div className="hindu-session-summary-item flawed">
                  <span className="k">Flawed</span>
                  <span className="v">{totals.flawed}</span>
                </div>
                <div className="hindu-session-summary-item">
                  <span className="k">Total time</span>
                  <span className="v">{totals.time.toFixed(0)}s</span>
                </div>
              </div>

              <div className="hindu-results-table">
                <div className="hindu-results-row hindu-results-head">
                  <span>Set</span>
                  <span>Reps</span>
                  <span>Good</span>
                  <span>Flawed</span>
                  <span>Time</span>
                </div>
                {setSummaries.map((s) => (
                  <div key={s.setNumber} className="hindu-results-row">
                    <span>{s.setNumber}</span>
                    <span>{s.reps}</span>
                    <span className="good-text">{s.goodReps}</span>
                    <span className="flawed-text">{s.flawedReps}</span>
                    <span>{s.elapsedTime.toFixed(0)}s</span>
                  </div>
                ))}
                {setSummaries.length === 0 && (
                  <div className="hindu-results-row">
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

export default HinduPushupPage;
