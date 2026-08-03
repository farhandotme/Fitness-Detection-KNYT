import { useEffect, useMemo, useState } from "react";
import useBentOverRowSocket from "../hooks/useBentOverRowSocket";
import BentOverRowCamera from "../conponents/BentOverRowCamera";
import BentOverRowStatsPanel from "../conponents/BentOverRowStatsPanel";
import "./BentOverRowPage.css";

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

const REP_PRESETS = [8, 10, 12, 15];
const SET_PRESETS = [1, 2, 3, 4, 5];
const REST_PRESETS = [30, 45, 60, 90];

type Phase = "setup" | "active" | "resting" | "complete";

interface SetSummary {
  setNumber: number;
  reps: number;
  goodReps: number;
  flawedReps: number;
  elapsedTime: number;
}

function BentOverRowPage() {
  const [repsPerSet, setRepsPerSet] = useState(10);
  const [totalSets, setTotalSets] = useState(3);
  const [restSeconds, setRestSeconds] = useState(45);

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
  } = useBentOverRowSocket();

  const skeleton = result.landmarks?.length
    ? [{ points: result.landmarks, connections: POSE_CONNECTIONS }]
    : [];

  const currentReps = result.rep_count ?? 0;
  const progressPct = Math.min(
    100,
    (currentReps / Math.max(1, repsPerSet)) * 100,
  );

  // ---- advance a set once the BACKEND confirms this set's reps are done ----
  // `session_complete` is computed server-side (BentOverRowAnalyzer._is_complete),
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

  // ---- persist completion once the backend confirms the whole plan is done ----
  useEffect(() => {
    if (!result.exercise_complete) return;
    // TODO: wire this up to the real backend endpoint once it exists, e.g.
    //   POST /api/workouts/complete { exercise: "bent_over_row", repsPerSet, totalSets }
    // The frontend must only ever send what the backend already validated
    // here (exercise_complete === true) — it must not decide completion on
    // its own.
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
        good: acc.good + s.goodReps,
        flawed: acc.flawed + s.flawedReps,
        time: acc.time + s.elapsedTime,
      }),
      { reps: 0, good: 0, flawed: 0, time: 0 },
    );
  }, [setSummaries]);

  const totalPlannedReps = repsPerSet * totalSets;

  return (
    <div className="bor-page">
      <div className="bor-header">
        <div className="bor-header-left">
          <h1 className="bor-title">Bent-Over Row Trainer</h1>
          <p className="bor-subtitle">
            Hinge forward → pull dumbbells to your ribs → lower with control
          </p>
        </div>

        <div className="bor-header-right">
          {phase === "active" && (
            <div className="bor-active-controls">
              <span className={`bor-status-dot ${connected ? "live" : ""}`} />
              <span className="bor-active-label">
                Set {currentSet}/{totalSets} · {currentReps}/{repsPerSet} reps
              </span>
              <button className="bor-stop-btn" onClick={handleEndSession}>
                End Session
              </button>
            </div>
          )}

          {phase === "resting" && (
            <div className="bor-active-controls">
              <span className="bor-active-label">
                Resting — next up: Set {currentSet + 1}/{totalSets}
              </span>
              <button className="bor-stop-btn" onClick={handleEndSession}>
                End Session
              </button>
            </div>
          )}

          {phase === "complete" && (
            <div className="bor-active-controls">
              <span className="bor-complete-label">✅ Session complete</span>
              <button className="bor-start-btn" onClick={handleReset}>
                New Session
              </button>
            </div>
          )}
        </div>
      </div>

      {socketError && <div className="bor-error">{socketError}</div>}
      {cameraError && <div className="bor-error">{cameraError}</div>}

      <div className="bor-body">
        <div className="bor-camera-col">
          <BentOverRowCamera
            active={phase === "active"}
            sendFrame={sendFrame}
            skeleton={skeleton}
            onError={setCameraError}
          />

          {phase === "resting" && (
            <div className="bor-rest-overlay-caption">
              <span className="bor-rest-countdown">{restRemaining}s</span>
              <span>until Set {currentSet + 1} starts</span>
            </div>
          )}

          {(phase === "active" || phase === "resting") && (
            <>
              <div className="bor-progress-track">
                <div
                  className="bor-progress-fill"
                  style={{
                    width: `${phase === "active" ? progressPct : 100}%`,
                  }}
                />
              </div>
              <div className="bor-progress-caption">
                {phase === "active"
                  ? `${currentReps} / ${repsPerSet} reps`
                  : "Set complete — resting"}
              </div>

              <div className="bor-set-dots">
                {Array.from({ length: totalSets }, (_, i) => i + 1).map((n) => (
                  <span
                    key={n}
                    className={`bor-set-dot ${
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

              <div className="bor-session-summary">
                <div className="bor-session-summary-item good">
                  <span className="k">Good</span>
                  <span className="v">{sessionGood}</span>
                </div>
                <div className="bor-session-summary-item flawed">
                  <span className="k">Flawed</span>
                  <span className="v">{sessionFlawed}</span>
                </div>
                <div className="bor-session-summary-item">
                  <span className="k">Elapsed</span>
                  <span className="v">{elapsed.toFixed(0)}s</span>
                </div>
              </div>
            </>
          )}
        </div>

        <div className="bor-stats-col">
          {phase === "setup" && (
            // TODO(coach-assignment): once a coach/plan API exists,
            // repsPerSet and totalSets should come from the user's assigned
            // plan (fetched here) and this picker should become read-only
            // display, not user-editable inputs. Whatever value is picked
            // here is what actually gets sent to the backend as
            // target_reps/target_sets — and the backend (not this
            // component) decides when it's been met.
            <div className="bor-session-builder">
              <div className="bor-builder-row">
                <span className="bor-builder-label">Reps per set</span>
                <div className="bor-builder-controls">
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
                    className="bor-reps-input"
                  />
                  <div className="bor-reps-presets">
                    {REP_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`bor-reps-preset ${repsPerSet === n ? "active" : ""}`}
                        onClick={() => setRepsPerSet(n)}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="bor-builder-row">
                <span className="bor-builder-label">Number of sets</span>
                <div className="bor-builder-controls">
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
                    className="bor-reps-input"
                  />
                  <div className="bor-reps-presets">
                    {SET_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`bor-reps-preset ${totalSets === n ? "active" : ""}`}
                        onClick={() => setTotalSets(n)}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="bor-builder-row">
                <span className="bor-builder-label">Rest between sets</span>
                <div className="bor-builder-controls">
                  <div className="bor-reps-presets">
                    {REST_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`bor-reps-preset ${restSeconds === n ? "active" : ""}`}
                        onClick={() => setRestSeconds(n)}
                      >
                        {n}s
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="bor-builder-total">
                {totalSets} × {repsPerSet} ={" "}
                <strong>{totalPlannedReps} reps total</strong>
              </div>

              <div className="bor-setup-tip">
                Stand with feet hip-width apart, dumbbells in hand. Hinge
                forward at the hips (soft knees, flat back) until your torso is
                roughly a 45° angle — not standing tall, not bent all the way
                flat. Let the dumbbells hang straight down, then pull both
                elbows up and back toward your ribs, squeezing your shoulder
                blades together, and lower with control. Film from the side so
                your hinge and pull are both clearly visible.
              </div>

              <button
                className="bor-start-btn full-width"
                onClick={handleStart}
              >
                Start Session ▶
              </button>
            </div>
          )}

          {phase === "resting" && (
            <div className="bor-rest-panel">
              <div className="bor-rest-panel-title">
                Set {currentSet} complete 🎉
              </div>
              <div className="bor-rest-panel-big-countdown">
                {restRemaining}
              </div>
              <div className="bor-rest-panel-caption">seconds of rest left</div>

              {setSummaries[setSummaries.length - 1] && (
                <div className="arm-grid bor-rest-panel-grid">
                  <div className="arm-grid-item">
                    <span className="k">Reps</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].reps}
                    </span>
                  </div>
                  <div className="arm-grid-item">
                    <span className="k">Good</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].goodReps}
                    </span>
                  </div>
                  <div className="arm-grid-item">
                    <span className="k">Flawed</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].flawedReps}
                    </span>
                  </div>
                </div>
              )}

              <button className="bor-stop-btn" onClick={handleSkipRest}>
                Skip rest
              </button>
            </div>
          )}

          {phase === "active" && (
            <div className="bor-single-wrap">
              <BentOverRowStatsPanel data={result} />

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

          {phase === "complete" && (
            <div className="bor-results-panel">
              <div className="bor-results-totals">
                <div className="bor-session-summary-item">
                  <span className="k">Sets</span>
                  <span className="v">{setSummaries.length}</span>
                </div>
                <div className="bor-session-summary-item">
                  <span className="k">Total reps</span>
                  <span className="v">{totals.reps}</span>
                </div>
                <div className="bor-session-summary-item good">
                  <span className="k">Good</span>
                  <span className="v">{totals.good}</span>
                </div>
                <div className="bor-session-summary-item flawed">
                  <span className="k">Flawed</span>
                  <span className="v">{totals.flawed}</span>
                </div>
                <div className="bor-session-summary-item">
                  <span className="k">Total time</span>
                  <span className="v">{totals.time.toFixed(0)}s</span>
                </div>
              </div>

              <div className="bor-results-table">
                <div className="bor-results-row bor-results-head">
                  <span>Set</span>
                  <span>Reps</span>
                  <span>Good</span>
                  <span>Flawed</span>
                  <span>Time</span>
                </div>
                {setSummaries.map((s) => (
                  <div key={s.setNumber} className="bor-results-row">
                    <span>{s.setNumber}</span>
                    <span>{s.reps}</span>
                    <span className="good-text">{s.goodReps}</span>
                    <span className="flawed-text">{s.flawedReps}</span>
                    <span>{s.elapsedTime.toFixed(0)}s</span>
                  </div>
                ))}
                {setSummaries.length === 0 && (
                  <div className="bor-results-row">
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

export default BentOverRowPage;
