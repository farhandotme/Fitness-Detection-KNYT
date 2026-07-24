import { useEffect, useMemo, useState } from "react";
import "./windMillRotationStretchPage.css";
import useWindmillSocket from "../hooks/useWindMillRotationStretch";
import WindmillCamera from "../conponents/windMillRotationStretchCamera";
import WindmillStatsPanel from "../conponents/windMillRotationStretchStatsPanel";

// Full-body skeleton (adds legs/hips vs. an upper-body-only overlay, since
// stance width matters for this exercise).
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

const REP_PRESETS = [6, 10, 12, 16];
const SET_PRESETS = [1, 2, 3, 4];
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

function WindmillPage() {
  const [repsPerSet, setRepsPerSet] = useState(10);
  const [totalSets, setTotalSets] = useState(2);
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
  } = useWindmillSocket();

  const skeleton = result.landmarks?.length
    ? [{ points: result.landmarks, connections: POSE_CONNECTIONS }]
    : [];

  const currentReps = result.rep_count ?? 0;
  const progressPct = Math.min(
    100,
    (currentReps / Math.max(1, repsPerSet)) * 100,
  );

  // ---- advance a set once the BACKEND confirms this set's reps are done ----
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
    <div className="windmill-page">
      <div className="windmill-header">
        <div className="windmill-header-left">
          <h1 className="windmill-title">Windmill Rotation Stretch</h1>
        </div>

        <div className="windmill-header-right">
          {phase === "active" && (
            <div className="windmill-active-controls">
              <span
                className={`windmill-status-dot ${connected ? "is-live" : ""}`}
              />
              <span className="windmill-active-label">
                Set {currentSet}/{totalSets} · {currentReps}/{repsPerSet} reps
              </span>
              <button className="windmill-stop-btn" onClick={handleEndSession}>
                End Session
              </button>
            </div>
          )}
        </div>
      </div>

      {socketError && (
        <div className="windmill-error-banner">{socketError}</div>
      )}
      {cameraError && (
        <div className="windmill-error-banner">{cameraError}</div>
      )}

      {phase === "setup" && (
        <div className="windmill-setup">
          <div className="windmill-setup-card">
            <h2>Set your plan</h2>

            <div className="windmill-preset-group">
              <label>Reps per set</label>
              <div className="windmill-preset-row">
                {REP_PRESETS.map((v) => (
                  <button
                    key={v}
                    className={
                      repsPerSet === v
                        ? "windmill-preset-btn is-active"
                        : "windmill-preset-btn"
                    }
                    onClick={() => setRepsPerSet(v)}
                  >
                    {v}
                  </button>
                ))}
              </div>
            </div>

            <div className="windmill-preset-group">
              <label>Sets</label>
              <div className="windmill-preset-row">
                {SET_PRESETS.map((v) => (
                  <button
                    key={v}
                    className={
                      totalSets === v
                        ? "windmill-preset-btn is-active"
                        : "windmill-preset-btn"
                    }
                    onClick={() => setTotalSets(v)}
                  >
                    {v}
                  </button>
                ))}
              </div>
            </div>

            <div className="windmill-preset-group">
              <label>Rest between sets (sec)</label>
              <div className="windmill-preset-row">
                {REST_PRESETS.map((v) => (
                  <button
                    key={v}
                    className={
                      restSeconds === v
                        ? "windmill-preset-btn is-active"
                        : "windmill-preset-btn"
                    }
                    onClick={() => setRestSeconds(v)}
                  >
                    {v}
                  </button>
                ))}
              </div>
            </div>

            <p className="windmill-setup-hint">
              Stand facing the camera, feet planted wider than your shoulders,
              arms out to the sides at shoulder height. Hinge sideways so one
              hand reaches toward your opposite foot while the other reaches
              straight up overhead, then return to the tall position and switch
              sides. Each full down-and-up counts as one rep, on either arm.
            </p>

            <button className="windmill-start-btn" onClick={handleStart}>
              Start
            </button>
          </div>
        </div>
      )}

      {(phase === "active" || phase === "resting") && (
        <div className="windmill-active-layout">
          <div className="windmill-camera-col">
            <WindmillCamera
              active={phase === "active"}
              sendFrame={sendFrame}
              skeleton={skeleton}
              onError={setCameraError}
            />
            <div className="windmill-progress-bar">
              <div
                className="windmill-progress-fill"
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>

          <div className="windmill-stats-col">
            {phase === "resting" ? (
              <div className="windmill-rest-card">
                <h2>Rest</h2>
                <div className="windmill-rest-timer">{restRemaining}s</div>
                <p>
                  Set {currentSet - 1} done — {currentReps} reps (
                  {result.left_reps ?? 0} left / {result.right_reps ?? 0} right)
                </p>
                <button className="windmill-start-btn" onClick={handleSkipRest}>
                  Skip Rest
                </button>
              </div>
            ) : (
              <WindmillStatsPanel
                result={result}
                lastCompletedRep={lastCompletedRep}
                repsPerSet={repsPerSet}
              />
            )}
          </div>
        </div>
      )}

      {phase === "complete" && (
        <div className="windmill-setup">
          <div className="windmill-setup-card">
            <h2>Session complete 🎉</h2>
            <div className="windmill-stat-row windmill-stat-row--primary">
              <div className="windmill-stat">
                <span className="windmill-stat-label">Total reps</span>
                <span className="windmill-stat-value">
                  {totals.reps}
                  <span className="windmill-stat-of">/{totalPlannedReps}</span>
                </span>
              </div>
              <div className="windmill-stat">
                <span className="windmill-stat-label">Left / Right</span>
                <span className="windmill-stat-value">
                  {totals.left} / {totals.right}
                </span>
              </div>
              <div className="windmill-stat">
                <span className="windmill-stat-label">Good form</span>
                <span className="windmill-stat-value windmill-stat-value--good">
                  {totals.good}
                </span>
              </div>
            </div>

            {setSummaries.map((s) => (
              <div key={s.setNumber} className="windmill-set-summary-row">
                Set {s.setNumber}: {s.reps} reps (L{s.leftReps}/R{s.rightReps})
                — {s.goodReps} good, {s.flawedReps} flawed —{" "}
                {s.elapsedTime.toFixed(1)}s
              </div>
            ))}

            <button className="windmill-start-btn" onClick={handleReset}>
              Do Another Session
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default WindmillPage;
