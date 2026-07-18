import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import useBridgeHoldSocket from "../hooks/useBridgeHoldSocket";
import BridgeHoldCamera from "../conponents/BridgeHoldCamera";
import BridgeHoldStatsPanel from "../conponents/BridgeHoldStatsPanel";
import "./BicepPage.css";
import "./BridgeHoldPage.css";

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

const HOLD_PRESETS = [20, 30, 45, 60];
const SET_PRESETS = [1, 2, 3, 4, 5];
const REST_PRESETS = [20, 30, 45, 60];

type Phase = "setup" | "active" | "resting" | "complete";

interface SetSummary {
  setNumber: number;
  holdSeconds: number;
  goodSeconds: number;
  flawedSeconds: number;
  breakCount: number;
  bestStreak: number;
  avgFormScore: number | null;
}

function formatSeconds(s: number): string {
  return s >= 60
    ? `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`
    : s.toFixed(1);
}

function BridgeHoldPage() {
  const navigate = useNavigate();

  const [targetSeconds, setTargetSeconds] = useState(30);
  const [totalSets, setTotalSets] = useState(3);
  const [restSeconds, setRestSeconds] = useState(30);

  const [phase, setPhase] = useState<Phase>("setup");
  const [currentSet, setCurrentSet] = useState(1);
  const [restRemaining, setRestRemaining] = useState(0);
  const [setSummaries, setSetSummaries] = useState<SetSummary[]>([]);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [justReached, setJustReached] = useState(false);

  const { connected, result, sendFrame, start, stop, socketError } =
    useBridgeHoldSocket();

  const skeleton = result.landmarks?.length
    ? [{ points: result.landmarks, connections: POSE_CONNECTIONS }]
    : [];

  const holdSeconds = result.hold_seconds ?? 0;
  const progressPct = Math.min(
    100,
    (holdSeconds / Math.max(1, targetSeconds)) * 100,
  );

  // ---- brief "target reached" flash, driven by the backend's own
  // edge-triggered flag — never re-derived from hold_seconds locally ----
  useEffect(() => {
    if (!result.target_reached) return;
    setJustReached(true);
    const timer = window.setTimeout(() => setJustReached(false), 1600);
    return () => window.clearTimeout(timer);
  }, [result.target_reached]);

  // ---- advance a set once the BACKEND confirms this set's hold time is met ----
  // `session_complete` is computed server-side
  // (BridgeHoldAnalyzer._is_complete), from the target_seconds the backend
  // itself was given when the socket opened. We never derive this from
  // hold_seconds/targetSeconds on the client — same rule as every rep-based
  // exercise in this codebase, just with a duration standing in for reps.
  useEffect(() => {
    if (phase !== "active" || !result.session_complete) return;

    stop();

    const summary: SetSummary = {
      setNumber: currentSet,
      holdSeconds: result.hold_seconds ?? 0,
      goodSeconds: result.good_seconds ?? 0,
      flawedSeconds: result.flawed_seconds ?? 0,
      breakCount: result.break_count ?? 0,
      bestStreak: result.best_streak_seconds ?? 0,
      avgFormScore: result.avg_form_score ?? null,
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
    //   POST /api/workouts/complete { exercise: "bridge_hold", targetSeconds, totalSets }
    // That endpoint is what should write the "user completed this exercise"
    // record to MongoDB. The frontend must only ever send what the backend
    // already validated here (exercise_complete === true) — it must not
    // decide completion on its own.
    console.log("Exercise completed (backend-validated) — ready to persist to DB.");
  }, [result.exercise_complete]);

  // ---- rest countdown between sets, then auto-start the next one ----
  useEffect(() => {
    if (phase !== "resting") return;

    if (restRemaining <= 0) {
      const nextSet = currentSet + 1;
      setCurrentSet(nextSet);
      setPhase("active");
      start({ targetSeconds, targetSets: totalSets, setNumber: nextSet });
      return;
    }

    const timer = window.setTimeout(() => setRestRemaining((r) => r - 1), 1000);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, restRemaining, start, currentSet, targetSeconds, totalSets]);

  function handleStart() {
    setCameraError(null);
    setSetSummaries([]);
    setCurrentSet(1);
    setPhase("active");
    start({ targetSeconds, targetSets: totalSets, setNumber: 1 });
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
        hold: acc.hold + s.holdSeconds,
        good: acc.good + s.goodSeconds,
        flawed: acc.flawed + s.flawedSeconds,
        breaks: acc.breaks + s.breakCount,
        bestStreak: Math.max(acc.bestStreak, s.bestStreak),
      }),
      { hold: 0, good: 0, flawed: 0, breaks: 0, bestStreak: 0 },
    );
  }, [setSummaries]);

  return (
    <div className="bicep-page bh-page">
      <div className="bicep-header">
        <div className="bicep-header-left">
          <button className="bh-back-btn" onClick={() => navigate("/exercises")}>
            ← Library
          </button>
          <h1 className="bicep-title">Glute Bridge Hold</h1>
        </div>

        <div className="bicep-header-right">
          {phase === "active" && (
            <div className="active-controls">
              <span className={`status-dot ${connected ? "live" : ""}`} />
              <span className="active-label">
                Set {currentSet}/{totalSets} · {formatSeconds(holdSeconds)}/
                {targetSeconds}s
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
          <BridgeHoldCamera
            active={phase === "active"}
            sendFrame={sendFrame}
            skeleton={skeleton}
            onError={setCameraError}
          />

          {justReached && (
            <div className="bh-reached-flash">🎉 Target reached!</div>
          )}

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
                  ? `${formatSeconds(holdSeconds)} / ${targetSeconds}s held`
                  : "Set complete"}
              </div>

              <div className="set-dots">
                {Array.from({ length: totalSets }, (_, i) => i + 1).map((n) => (
                  <span
                    key={n}
                    className={`set-dot ${
                      n < currentSet || (n === currentSet && phase === "resting")
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
                  <span className="v">{formatSeconds(result.good_seconds ?? 0)}s</span>
                </div>
                <div className="session-summary-item flawed">
                  <span className="k">Flawed</span>
                  <span className="v">{formatSeconds(result.flawed_seconds ?? 0)}s</span>
                </div>
                <div className="session-summary-item">
                  <span className="k">Breaks</span>
                  <span className="v">{result.break_count ?? 0}</span>
                </div>
              </div>
            </>
          )}
        </div>

        <div className="bicep-stats-col">
          {phase === "setup" && (
            // TODO(coach-assignment): once a coach/plan API exists,
            // targetSeconds and totalSets should come from the user's
            // assigned plan (fetched here) and this picker should become
            // read-only display, not user-editable inputs. Whatever value
            // is picked here is what actually gets sent to the backend as
            // target_seconds/target_sets — and the backend (not this
            // component) decides when it's been met.
            <div className="session-builder">
              <div className="builder-row">
                <span className="builder-label">Hold time per set</span>
                <div className="builder-controls">
                  <input
                    type="number"
                    min={5}
                    max={1800}
                    value={targetSeconds}
                    onChange={(e) =>
                      setTargetSeconds(
                        Math.max(5, Math.min(1800, Number(e.target.value) || 5)),
                      )
                    }
                    className="reps-input"
                  />
                  <div className="reps-presets">
                    {HOLD_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`reps-preset ${targetSeconds === n ? "active" : ""}`}
                        onClick={() => setTargetSeconds(n)}
                      >
                        {n}s
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
                {totalSets} × {targetSeconds}s ={" "}
                <strong>{totalSets * targetSeconds}s total hold time</strong>
              </div>

              <div className="squat-setup-tip">
                Lie on your back, side-on to the camera, knees bent and feet
                flat. Hold still in the bridge for a second once you lift so
                the timer can lock onto your alignment — the clock only runs
                while your form checks out, and pauses (not resets) if it
                breaks.
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
                    <span className="k">Held</span>
                    <span className="v">
                      {formatSeconds(setSummaries[setSummaries.length - 1].holdSeconds)}s
                    </span>
                  </div>
                  <div className="arm-grid-item">
                    <span className="k">Best streak</span>
                    <span className="v">
                      {formatSeconds(setSummaries[setSummaries.length - 1].bestStreak)}s
                    </span>
                  </div>
                  <div className="arm-grid-item">
                    <span className="k">Breaks</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].breakCount}
                    </span>
                  </div>
                  <div className="arm-grid-item">
                    <span className="k">Avg form</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].avgFormScore ?? "—"}
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
              <BridgeHoldStatsPanel data={result} targetSeconds={targetSeconds} />

              {result.feedback && (
                <div
                  className={`feedback-box ${
                    result.is_holding
                      ? (result.hold_quality ?? "")
                      : "needs_improvement"
                  }`}
                >
                  <strong>Coach Feedback</strong>
                  <p>{result.feedback}</p>
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
                  <span className="k">Total held</span>
                  <span className="v">{formatSeconds(totals.hold)}s</span>
                </div>
                <div className="session-summary-item good">
                  <span className="k">Good</span>
                  <span className="v">{formatSeconds(totals.good)}s</span>
                </div>
                <div className="session-summary-item flawed">
                  <span className="k">Flawed</span>
                  <span className="v">{formatSeconds(totals.flawed)}s</span>
                </div>
                <div className="session-summary-item">
                  <span className="k">Breaks</span>
                  <span className="v">{totals.breaks}</span>
                </div>
                <div className="session-summary-item">
                  <span className="k">Best streak</span>
                  <span className="v">{formatSeconds(totals.bestStreak)}s</span>
                </div>
              </div>

              <div className="results-table">
                <div className="results-row results-head">
                  <span>Set</span>
                  <span>Held</span>
                  <span>Breaks</span>
                  <span>Best streak</span>
                  <span>Avg form</span>
                </div>
                {setSummaries.map((s) => (
                  <div key={s.setNumber} className="results-row">
                    <span>{s.setNumber}</span>
                    <span>{formatSeconds(s.holdSeconds)}s</span>
                    <span>{s.breakCount}</span>
                    <span>{formatSeconds(s.bestStreak)}s</span>
                    <span>{s.avgFormScore ?? "—"}</span>
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

export default BridgeHoldPage;
