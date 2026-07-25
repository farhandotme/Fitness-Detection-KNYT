import { useEffect, useMemo, useState } from "react";
import useFlutterKicksSocket from "../hooks/useFlutterKicksSocket";
import "./FlutterKicksPage.css";
import FlutterKicksCamera from "../conponents/FlutterKIcksCamera";
import FlutterKicksStatsPanel from "../conponents/FlutterKickStatsPanel";

// MediaPipe pose connections relevant to the torso + both legs.
const POSE_CONNECTIONS: [number, number][] = [
  [11, 12], // shoulders
  [23, 24], // hips
  [11, 23], // left shoulder -> hip
  [12, 24], // right shoulder -> hip
  [23, 25], // left hip -> knee
  [25, 27], // left knee -> ankle
  [24, 26], // right hip -> knee
  [26, 28], // right knee -> ankle
];

const REP_PRESETS = [10, 20, 30, 40];
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

function FlutterKicksPage() {
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
  } = useFlutterKicksSocket();

  const skeleton = result.landmarks?.length
    ? [{ points: result.landmarks, connections: POSE_CONNECTIONS }]
    : [];

  const currentReps = result.rep_count ?? 0;
  const progressPct = Math.min(
    100,
    (currentReps / Math.max(1, repsPerSet)) * 100,
  );

  // ---- advance a set once the BACKEND confirms this set's reps are done ----
  // `session_complete` is computed server-side (FlutterKicksAnalyzer._is_complete),
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
    //   POST /api/workouts/complete { exercise: "flutter_kicks", repsPerSet, totalSets }
    // The frontend must only ever send what the backend already validated
    // here (exercise_complete === true) — it must not decide completion
    // on its own.
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
    <div className="flutter-page">
      <div className="flutter-header">
        <div className="flutter-header-left">
          <h1 className="flutter-title">Flutter Kicks Trainer</h1>
          <p className="flutter-subtitle">
            Each counted rep is one confirmed leg swap — start with either leg,
            then alternate continuously.
          </p>
        </div>

        <div className="flutter-header-right">
          {phase === "active" && (
            <div className="flutter-active-controls">
              <span
                className={`flutter-status-dot ${connected ? "live" : ""}`}
              />
              <span className="flutter-active-label">
                Set {currentSet}/{totalSets} · {currentReps}/{repsPerSet} reps
              </span>
              <button className="flutter-stop-btn" onClick={handleEndSession}>
                End Session
              </button>
            </div>
          )}

          {phase === "resting" && (
            <div className="flutter-active-controls">
              <span className="flutter-active-label">
                Resting — next up: Set {currentSet + 1}/{totalSets}
              </span>
              <button className="flutter-stop-btn" onClick={handleEndSession}>
                End Session
              </button>
            </div>
          )}

          {phase === "complete" && (
            <div className="flutter-active-controls">
              <span className="flutter-complete-label">
                ✅ Session complete
              </span>
              <button className="flutter-start-btn" onClick={handleReset}>
                New Session
              </button>
            </div>
          )}
        </div>
      </div>

      {socketError && <div className="flutter-error">{socketError}</div>}
      {cameraError && <div className="flutter-error">{cameraError}</div>}

      <div className="flutter-body">
        <div className="flutter-camera-col">
          <FlutterKicksCamera
            active={phase === "active"}
            sendFrame={sendFrame}
            skeleton={skeleton}
            onError={setCameraError}
          />

          {phase === "resting" && (
            <div className="flutter-rest-overlay-caption">
              <span className="flutter-rest-countdown">{restRemaining}s</span>
              <span>until Set {currentSet + 1} starts</span>
            </div>
          )}

          {(phase === "active" || phase === "resting") && (
            <>
              <div className="flutter-progress-track">
                <div
                  className="flutter-progress-fill"
                  style={{
                    width: `${phase === "active" ? progressPct : 100}%`,
                  }}
                />
              </div>
              <div className="flutter-progress-caption">
                {phase === "active"
                  ? `${currentReps} / ${repsPerSet} reps`
                  : "Set complete — resting"}
              </div>

              <div className="flutter-set-dots">
                {Array.from({ length: totalSets }, (_, i) => i + 1).map((n) => (
                  <span
                    key={n}
                    className={`flutter-set-dot ${
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

              <div className="flutter-session-summary">
                <div className="flutter-session-summary-item good">
                  <span className="k">Good</span>
                  <span className="v">{sessionGood}</span>
                </div>
                <div className="flutter-session-summary-item flawed">
                  <span className="k">Flawed</span>
                  <span className="v">{sessionFlawed}</span>
                </div>
                <div className="flutter-session-summary-item">
                  <span className="k">Elapsed</span>
                  <span className="v">{elapsed.toFixed(0)}s</span>
                </div>
              </div>
            </>
          )}
        </div>

        <div className="flutter-stats-col">
          {phase === "setup" && (
            <div className="flutter-session-builder">
              <div className="flutter-builder-row">
                <span className="flutter-builder-label">Reps per set</span>
                <div className="flutter-builder-controls">
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
                    className="flutter-reps-input"
                  />
                  <div className="flutter-reps-presets">
                    {REP_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`flutter-reps-preset ${repsPerSet === n ? "active" : ""}`}
                        onClick={() => setRepsPerSet(n)}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="flutter-builder-row">
                <span className="flutter-builder-label">Number of sets</span>
                <div className="flutter-builder-controls">
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
                    className="flutter-reps-input"
                  />
                  <div className="flutter-reps-presets">
                    {SET_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`flutter-reps-preset ${totalSets === n ? "active" : ""}`}
                        onClick={() => setTotalSets(n)}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="flutter-builder-row">
                <span className="flutter-builder-label">Rest between sets</span>
                <div className="flutter-builder-controls">
                  <div className="flutter-reps-presets">
                    {REST_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`flutter-reps-preset ${restSeconds === n ? "active" : ""}`}
                        onClick={() => setRestSeconds(n)}
                      >
                        {n}s
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="flutter-builder-total">
                {totalSets} × {repsPerSet} ={" "}
                <strong>{totalPlannedReps} reps total</strong>
              </div>

              <div className="flutter-setup-tip">
                Lie flat on your back on the floor, filmed from the side so your
                torso and both legs are clearly visible. Keep your legs fairly
                straight, extend one leg down near (not touching) the floor
                while the other lifts, then swap — continuously, alternating
                sides. A rep only counts once a real lying position is confirmed
                and the legs genuinely swap sides.
              </div>

              <button
                className="flutter-start-btn full-width"
                onClick={handleStart}
              >
                Start Session ▶
              </button>
            </div>
          )}

          {phase === "resting" && (
            <div className="flutter-rest-panel">
              <div className="flutter-rest-panel-title">
                Set {currentSet} complete 🎉
              </div>
              <div className="flutter-rest-panel-big-countdown">
                {restRemaining}
              </div>
              <div className="flutter-rest-panel-caption">
                seconds of rest left
              </div>

              {setSummaries[setSummaries.length - 1] && (
                <div className="flutter-grid flutter-rest-panel-grid">
                  <div className="flutter-grid-item">
                    <span className="k">Reps</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].reps}
                    </span>
                  </div>
                  <div className="flutter-grid-item">
                    <span className="k">Good</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].goodReps}
                    </span>
                  </div>
                  <div className="flutter-grid-item">
                    <span className="k">Flawed</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].flawedReps}
                    </span>
                  </div>
                </div>
              )}

              <button className="flutter-stop-btn" onClick={handleSkipRest}>
                Skip rest
              </button>
            </div>
          )}

          {phase === "active" && (
            <div className="flutter-single-wrap">
              <FlutterKicksStatsPanel
                data={result}
                lastCompletedRep={lastCompletedRep}
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

          {phase === "complete" && (
            <div className="flutter-results-panel">
              <div className="flutter-results-totals">
                <div className="flutter-session-summary-item">
                  <span className="k">Sets</span>
                  <span className="v">{setSummaries.length}</span>
                </div>
                <div className="flutter-session-summary-item">
                  <span className="k">Total reps</span>
                  <span className="v">{totals.reps}</span>
                </div>
                <div className="flutter-session-summary-item good">
                  <span className="k">Good</span>
                  <span className="v">{totals.good}</span>
                </div>
                <div className="flutter-session-summary-item flawed">
                  <span className="k">Flawed</span>
                  <span className="v">{totals.flawed}</span>
                </div>
                <div className="flutter-session-summary-item">
                  <span className="k">Total time</span>
                  <span className="v">{totals.time.toFixed(0)}s</span>
                </div>
              </div>

              <div className="flutter-results-table">
                <div className="flutter-results-row flutter-results-head">
                  <span>Set</span>
                  <span>Reps</span>
                  <span>Good</span>
                  <span>Flawed</span>
                  <span>Time</span>
                </div>
                {setSummaries.map((s) => (
                  <div key={s.setNumber} className="flutter-results-row">
                    <span>{s.setNumber}</span>
                    <span>{s.reps}</span>
                    <span className="good-text">{s.goodReps}</span>
                    <span className="flawed-text">{s.flawedReps}</span>
                    <span>{s.elapsedTime.toFixed(0)}s</span>
                  </div>
                ))}
                {setSummaries.length === 0 && (
                  <div className="flutter-results-row">
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

export default FlutterKicksPage;
