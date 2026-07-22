import { useEffect, useMemo, useState } from "react";
import useChairPoseSocket from "../hooks/useChairPoseSocket";
import ChairPoseCamera from "../conponents/ChairPoseCamera";
import ChairPoseStatsPanel from "../conponents/ChairPoseStatsPanel";
import "./ChairPosePage.css";

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

const HOLD_PRESETS = [15, 20, 30, 45];
const SET_PRESETS = [1, 2, 3, 4, 5];
const REST_PRESETS = [15, 20, 30, 45];

type Phase = "setup" | "active" | "resting" | "complete";

interface SetSummary {
  setNumber: number;
  holdSeconds: number;
  goodSeconds: number;
  flawedSeconds: number;
  breakCount: number;
  bestStreakSeconds: number;
  avgFormScore: number | null;
  elapsedTime: number;
}

function ChairPosePage() {
  const [holdSecondsTarget, setHoldSecondsTarget] = useState(20);
  const [totalSets, setTotalSets] = useState(3);
  const [restSeconds, setRestSeconds] = useState(20);

  const [phase, setPhase] = useState<Phase>("setup");
  const [currentSet, setCurrentSet] = useState(1);
  const [restRemaining, setRestRemaining] = useState(0);
  const [setSummaries, setSetSummaries] = useState<SetSummary[]>([]);
  const [cameraError, setCameraError] = useState<string | null>(null);

  const { connected, result, sendFrame, start, stop, socketError } =
    useChairPoseSocket();

  const skeleton = result.landmarks?.length
    ? [{ points: result.landmarks, connections: POSE_CONNECTIONS }]
    : [];

  const currentHoldSeconds = result.hold_seconds ?? 0;
  const progressPct = Math.min(
    100,
    (currentHoldSeconds / Math.max(1, holdSecondsTarget)) * 100,
  );

  // ---- advance a set once the BACKEND confirms this set's hold target is met ----
  // `session_complete` is computed server-side (ChairPoseAnalyzer._is_complete),
  // from the target_seconds the backend itself was given when the socket
  // opened. We never derive this from currentHoldSeconds/holdSecondsTarget
  // on the client.
  useEffect(() => {
    if (phase !== "active" || !result.session_complete) return;

    stop();

    const summary: SetSummary = {
      setNumber: currentSet,
      holdSeconds: currentHoldSeconds,
      goodSeconds: result.good_seconds ?? 0,
      flawedSeconds: result.flawed_seconds ?? 0,
      breakCount: result.break_count ?? 0,
      bestStreakSeconds: result.best_streak_seconds ?? 0,
      avgFormScore: result.avg_form_score ?? null,
      elapsedTime: result.elapsed_time ?? 0,
    };
    setSetSummaries((prev) => [...prev, summary]);

    // exercise_complete is also backend-validated: true only once every
    // set in the plan hit its hold target. This is the boolean that should
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
        targetSeconds: holdSecondsTarget,
        targetSets: totalSets,
        setNumber: nextSet,
      });
      return;
    }

    const timer = window.setTimeout(() => setRestRemaining((r) => r - 1), 1000);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, restRemaining, start, currentSet, holdSecondsTarget, totalSets]);

  function handleStart() {
    setCameraError(null);
    setSetSummaries([]);
    setCurrentSet(1);
    setPhase("active");
    start({
      targetSeconds: holdSecondsTarget,
      targetSets: totalSets,
      setNumber: 1,
    });
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

  const sessionGoodSeconds = result.good_seconds ?? 0;
  const sessionFlawedSeconds = result.flawed_seconds ?? 0;
  const elapsed = result.elapsed_time ?? 0;

  const totals = useMemo(() => {
    return setSummaries.reduce(
      (acc, s) => ({
        hold: acc.hold + s.holdSeconds,
        good: acc.good + s.goodSeconds,
        flawed: acc.flawed + s.flawedSeconds,
        breaks: acc.breaks + s.breakCount,
        time: acc.time + s.elapsedTime,
      }),
      { hold: 0, good: 0, flawed: 0, breaks: 0, time: 0 },
    );
  }, [setSummaries]);

  const totalPlannedSeconds = holdSecondsTarget * totalSets;

  return (
    <div className="chair-page">
      <div className="chair-header">
        <div className="chair-header-left">
          <h1 className="chair-title">Chair Pose (Utkatasana) Trainer</h1>
        </div>

        <div className="chair-header-right">
          {phase === "active" && (
            <div className="chair-active-controls">
              <span className={`chair-status-dot ${connected ? "live" : ""}`} />
              <span className="chair-active-label">
                Set {currentSet}/{totalSets} · {currentHoldSeconds.toFixed(0)}/
                {holdSecondsTarget}s
              </span>
              <button className="chair-stop-btn" onClick={handleEndSession}>
                End Session
              </button>
            </div>
          )}

          {phase === "resting" && (
            <div className="chair-active-controls">
              <span className="chair-active-label">
                Resting — next up: Set {currentSet + 1}/{totalSets}
              </span>
              <button className="chair-stop-btn" onClick={handleEndSession}>
                End Session
              </button>
            </div>
          )}

          {phase === "complete" && (
            <div className="chair-active-controls">
              <span className="chair-complete-label">✅ Session complete</span>
              <button className="chair-start-btn" onClick={handleReset}>
                New Session
              </button>
            </div>
          )}
        </div>
      </div>

      {socketError && <div className="chair-error">{socketError}</div>}
      {cameraError && <div className="chair-error">{cameraError}</div>}

      <div className="chair-body">
        <div className="chair-camera-col">
          <ChairPoseCamera
            active={phase === "active"}
            sendFrame={sendFrame}
            skeleton={skeleton}
            onError={setCameraError}
          />

          {phase === "resting" && (
            <div className="chair-rest-overlay-caption">
              <span className="chair-rest-countdown">{restRemaining}s</span>
              <span>until Set {currentSet + 1} starts</span>
            </div>
          )}

          {(phase === "active" || phase === "resting") && (
            <>
              <div className="chair-progress-track">
                <div
                  className="chair-progress-fill"
                  style={{
                    width: `${phase === "active" ? progressPct : 100}%`,
                  }}
                />
              </div>
              <div className="chair-progress-caption">
                {phase === "active"
                  ? `${currentHoldSeconds.toFixed(0)}s / ${holdSecondsTarget}s held`
                  : "Set complete — resting"}
              </div>

              <div className="chair-set-dots">
                {Array.from({ length: totalSets }, (_, i) => i + 1).map((n) => (
                  <span
                    key={n}
                    className={`chair-set-dot ${
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

              <div className="chair-session-summary">
                <div className="chair-session-summary-item good">
                  <span className="k">Good hold</span>
                  <span className="v">{sessionGoodSeconds.toFixed(0)}s</span>
                </div>
                <div className="chair-session-summary-item flawed">
                  <span className="k">Flawed hold</span>
                  <span className="v">{sessionFlawedSeconds.toFixed(0)}s</span>
                </div>
                <div className="chair-session-summary-item">
                  <span className="k">Elapsed</span>
                  <span className="v">{elapsed.toFixed(0)}s</span>
                </div>
              </div>
            </>
          )}
        </div>

        <div className="chair-stats-col">
          {phase === "setup" && (
            <div className="chair-session-builder">
              <div className="chair-builder-row">
                <span className="chair-builder-label">
                  Hold per set (seconds)
                </span>
                <div className="chair-builder-controls">
                  <input
                    type="number"
                    min={5}
                    max={600}
                    value={holdSecondsTarget}
                    onChange={(e) =>
                      setHoldSecondsTarget(
                        Math.max(5, Math.min(600, Number(e.target.value) || 5)),
                      )
                    }
                    className="chair-reps-input"
                  />
                  <div className="chair-reps-presets">
                    {HOLD_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`chair-reps-preset ${holdSecondsTarget === n ? "active" : ""}`}
                        onClick={() => setHoldSecondsTarget(n)}
                      >
                        {n}s
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="chair-builder-row">
                <span className="chair-builder-label">Number of sets</span>
                <div className="chair-builder-controls">
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
                    className="chair-reps-input"
                  />
                  <div className="chair-reps-presets">
                    {SET_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`chair-reps-preset ${totalSets === n ? "active" : ""}`}
                        onClick={() => setTotalSets(n)}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="chair-builder-row">
                <span className="chair-builder-label">Rest between sets</span>
                <div className="chair-builder-controls">
                  <div className="chair-reps-presets">
                    {REST_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`chair-reps-preset ${restSeconds === n ? "active" : ""}`}
                        onClick={() => setRestSeconds(n)}
                      >
                        {n}s
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="chair-builder-total">
                {totalSets} × {holdSecondsTarget}s ={" "}
                <strong>{totalPlannedSeconds}s total hold time</strong>
              </div>

              <div className="chair-setup-tip">
                Stand side-on to the camera, feet hip-width apart. Lower into
                Chair Pose (knees bent, hips back, arms overhead or palms
                together at your chest) and hold — the timer runs only while
                your form is valid, pauses the instant it breaks, and picks back
                up the moment you're back in position.
              </div>

              <button
                className="chair-start-btn full-width"
                onClick={handleStart}
              >
                Start Session ▶
              </button>
            </div>
          )}

          {phase === "resting" && (
            <div className="chair-rest-panel">
              <div className="chair-rest-panel-title">
                Set {currentSet} complete 🎉
              </div>
              <div className="chair-rest-panel-big-countdown">
                {restRemaining}
              </div>
              <div className="chair-rest-panel-caption">
                seconds of rest left
              </div>

              {setSummaries[setSummaries.length - 1] && (
                <div className="chair-grid chair-rest-panel-grid">
                  <div className="chair-grid-item">
                    <span className="k">Held</span>
                    <span className="v">
                      {setSummaries[
                        setSummaries.length - 1
                      ].holdSeconds.toFixed(0)}
                      s
                    </span>
                  </div>
                  <div className="chair-grid-item">
                    <span className="k">Best streak</span>
                    <span className="v">
                      {setSummaries[
                        setSummaries.length - 1
                      ].bestStreakSeconds.toFixed(0)}
                      s
                    </span>
                  </div>
                  <div className="chair-grid-item">
                    <span className="k">Breaks</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].breakCount}
                    </span>
                  </div>
                </div>
              )}

              <button className="chair-stop-btn" onClick={handleSkipRest}>
                Skip rest
              </button>
            </div>
          )}

          {phase === "active" && (
            <div className="chair-single-wrap">
              <ChairPoseStatsPanel data={result} />

              {result.feedback && (
                <div className="chair-feedback-box">
                  <strong>Coach Feedback</strong>
                  <p>{result.feedback}</p>
                </div>
              )}
            </div>
          )}

          {phase === "complete" && (
            <div className="chair-results-panel">
              <div className="chair-results-totals">
                <div className="chair-session-summary-item">
                  <span className="k">Sets</span>
                  <span className="v">{setSummaries.length}</span>
                </div>
                <div className="chair-session-summary-item">
                  <span className="k">Total held</span>
                  <span className="v">{totals.hold.toFixed(0)}s</span>
                </div>
                <div className="chair-session-summary-item good">
                  <span className="k">Good</span>
                  <span className="v">{totals.good.toFixed(0)}s</span>
                </div>
                <div className="chair-session-summary-item flawed">
                  <span className="k">Flawed</span>
                  <span className="v">{totals.flawed.toFixed(0)}s</span>
                </div>
                <div className="chair-session-summary-item">
                  <span className="k">Breaks</span>
                  <span className="v">{totals.breaks}</span>
                </div>
                <div className="chair-session-summary-item">
                  <span className="k">Total time</span>
                  <span className="v">{totals.time.toFixed(0)}s</span>
                </div>
              </div>

              <div className="chair-results-table">
                <div className="chair-results-row chair-results-head">
                  <span>Set</span>
                  <span>Held</span>
                  <span>Best streak</span>
                  <span>Breaks</span>
                  <span>Avg form</span>
                </div>
                {setSummaries.map((s) => (
                  <div key={s.setNumber} className="chair-results-row">
                    <span>{s.setNumber}</span>
                    <span>{s.holdSeconds.toFixed(0)}s</span>
                    <span>{s.bestStreakSeconds.toFixed(0)}s</span>
                    <span>{s.breakCount}</span>
                    <span>{s.avgFormScore != null ? s.avgFormScore : "—"}</span>
                  </div>
                ))}
                {setSummaries.length === 0 && (
                  <div className="chair-results-row">
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

export default ChairPosePage;
