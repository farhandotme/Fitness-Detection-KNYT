import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import useArmCirclesSocket from "../hooks/useArmCirclesSocket";
import ArmCirclesCamera from "../conponents/ArmCirclesCamera";
import ArmCirclesStatsPanel from "../conponents/ArmCirclesStatsPanel";
import "./BicepPage.css";
import "./ArmCirclesPage.css";

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

const REP_PRESETS = [8, 10, 15, 20];
const SET_PRESETS = [1, 2, 3, 4];
const REST_PRESETS = [15, 20, 30, 45];

type Phase = "setup" | "active" | "resting" | "complete";

interface SetSummary {
  setNumber: number;
  rounds: number;
  goodReps: number;
  flawedReps: number;
  leftArmRounds: number;
  rightArmRounds: number;
  elapsedTime: number;
}

function ArmCirclesPage() {
  const navigate = useNavigate();

  const [roundsPerSet, setRoundsPerSet] = useState(10);
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
  } = useArmCirclesSocket();

  const skeleton = result.landmarks?.length
    ? [{ points: result.landmarks, connections: POSE_CONNECTIONS }]
    : [];

  const currentRounds = result.rep_count ?? 0;
  const progressPct = Math.min(
    100,
    (currentRounds / Math.max(1, roundsPerSet)) * 100,
  );

  // ---- advance a set once the BACKEND confirms this set's rounds are done ----
  // `session_complete` is computed server-side (ArmCirclesAnalyzer._is_complete),
  // from the target_reps the backend itself was given when the socket opened.
  // We never derive this from currentRounds/roundsPerSet on the client.
  useEffect(() => {
    if (phase !== "active" || !result.session_complete) return;

    stop();

    const summary: SetSummary = {
      setNumber: currentSet,
      rounds: currentRounds,
      goodReps: result.good_reps ?? 0,
      flawedReps: result.flawed_reps ?? 0,
      leftArmRounds: result.left_arm_rounds ?? 0,
      rightArmRounds: result.right_arm_rounds ?? 0,
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
    //   POST /api/workouts/complete { exercise: "arm-circles", roundsPerSet, totalSets }
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
        targetReps: roundsPerSet,
        targetSets: totalSets,
        setNumber: nextSet,
      });
      return;
    }

    const timer = window.setTimeout(() => setRestRemaining((r) => r - 1), 1000);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, restRemaining, start, currentSet, roundsPerSet, totalSets]);

  function handleStart() {
    setCameraError(null);
    setSetSummaries([]);
    setCurrentSet(1);
    setPhase("active");
    start({ targetReps: roundsPerSet, targetSets: totalSets, setNumber: 1 });
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
        rounds: acc.rounds + s.rounds,
        good: acc.good + s.goodReps,
        flawed: acc.flawed + s.flawedReps,
        left: acc.left + s.leftArmRounds,
        right: acc.right + s.rightArmRounds,
        time: acc.time + s.elapsedTime,
      }),
      { rounds: 0, good: 0, flawed: 0, left: 0, right: 0, time: 0 },
    );
  }, [setSummaries]);

  const totalPlannedRounds = roundsPerSet * totalSets;

  return (
    <div className="bicep-page arm-circles-page">
      <div className="bicep-header">
        <div className="bicep-header-left">
          <button
            className="arm-circles-back-btn"
            onClick={() => navigate("/exercises")}
          >
            ← Library
          </button>
          <h1 className="bicep-title">Arm Circles Trainer</h1>
        </div>

        <div className="bicep-header-right">
          {phase === "active" && (
            <div className="active-controls">
              <span className={`status-dot ${connected ? "live" : ""}`} />
              <span className="active-label">
                Set {currentSet}/{totalSets} · {currentRounds}/{roundsPerSet}{" "}
                rounds
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
          <ArmCirclesCamera
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
                  ? `${currentRounds} / ${roundsPerSet} rounds`
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
            </>
          )}
        </div>

        <div className="bicep-stats-col">
          {phase === "setup" && (
            // TODO(coach-assignment): once a coach/plan API exists,
            // roundsPerSet and totalSets should come from the user's
            // assigned plan (fetched here) and this picker should become
            // read-only display, not user-editable inputs. Whatever value
            // is picked here is what actually gets sent to the backend as
            // target_reps/target_sets — and the backend (not this
            // component) decides when it's been met.
            <div className="session-builder">
              <div className="builder-row">
                <span className="builder-label">Rounds per set</span>
                <div className="builder-controls">
                  <input
                    type="number"
                    min={1}
                    max={100}
                    value={roundsPerSet}
                    onChange={(e) =>
                      setRoundsPerSet(
                        Math.max(1, Math.min(100, Number(e.target.value) || 1)),
                      )
                    }
                    className="reps-input"
                  />
                  <div className="reps-presets">
                    {REP_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`reps-preset ${roundsPerSet === n ? "active" : ""}`}
                        onClick={() => setRoundsPerSet(n)}
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
                {totalSets} × {roundsPerSet} ={" "}
                <strong>{totalPlannedRounds} rounds total</strong>
              </div>

              <div className="arm-circles-setup-tip">
                Stand facing the camera, arms out to your sides, and circle
                both arms together — either direction. A round only counts
                once your arm has swept a genuine full circle, arm reasonably
                extended the whole way; small wobbles or a bent elbow won't
                falsely add a round, and a real completed circle is never
                missed. The counter shown is for both arms moving together —
                each arm's own total is tracked separately too.
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
                    <span className="k">Rounds</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].rounds}
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
                  <div className="arm-grid-item">
                    <span className="k">Left / Right</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].leftArmRounds} /{" "}
                      {setSummaries[setSummaries.length - 1].rightArmRounds}
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
              <ArmCirclesStatsPanel data={result} />

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
            <div className="results-panel">
              <div className="results-totals">
                <div className="session-summary-item">
                  <span className="k">Sets</span>
                  <span className="v">{setSummaries.length}</span>
                </div>
                <div className="session-summary-item">
                  <span className="k">Total rounds</span>
                  <span className="v">{totals.rounds}</span>
                </div>
                <div className="session-summary-item good">
                  <span className="k">Good</span>
                  <span className="v">{totals.good}</span>
                </div>
                <div className="session-summary-item flawed">
                  <span className="k">Flawed</span>
                  <span className="v">{totals.flawed}</span>
                </div>
                <div className="session-summary-item">
                  <span className="k">Left / Right</span>
                  <span className="v">
                    {totals.left} / {totals.right}
                  </span>
                </div>
                <div className="session-summary-item">
                  <span className="k">Total time</span>
                  <span className="v">{totals.time.toFixed(0)}s</span>
                </div>
              </div>

              <div className="results-table">
                <div className="results-row results-head">
                  <span>Set</span>
                  <span>Rounds</span>
                  <span>Good</span>
                  <span>Flawed</span>
                  <span>L/R</span>
                </div>
                {setSummaries.map((s) => (
                  <div key={s.setNumber} className="results-row">
                    <span>{s.setNumber}</span>
                    <span>{s.rounds}</span>
                    <span className="good-text">{s.goodReps}</span>
                    <span className="flawed-text">{s.flawedReps}</span>
                    <span>
                      {s.leftArmRounds}/{s.rightArmRounds}
                    </span>
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

export default ArmCirclesPage;
