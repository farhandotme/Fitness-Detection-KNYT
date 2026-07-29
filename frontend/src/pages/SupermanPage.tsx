import { useEffect, useMemo, useState } from "react";
import useSupermanSocket from "../hooks/useSupermanSocket";
import SupermanCamera from "../conponents/SupermanCamera";
import SupermanStatsPanel from "../conponents/SupermanStatsPanel";
import "./SupermanPage.css";

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
const SET_PRESETS = [1, 2, 3, 4];
const REST_PRESETS = [15, 20, 30, 45];

type Phase = "setup" | "active" | "resting" | "complete";

interface SetSummary {
  setNumber: number;
  holdSeconds: number;
  bestStreak: number;
  breakCount: number;
  goodSeconds: number;
  flawedSeconds: number;
}

function formatSeconds(s: number): string {
  const total = Math.max(0, s);
  const m = Math.floor(total / 60);
  const sec = total - m * 60;
  if (m > 0) return `${m}:${sec.toFixed(0).padStart(2, "0")}`;
  return `${sec.toFixed(1)}s`;
}

function SupermanPage() {
  const [holdTarget, setHoldTarget] = useState(20);
  const [totalSets, setTotalSets] = useState(3);
  const [restSeconds, setRestSeconds] = useState(20);

  const [phase, setPhase] = useState<Phase>("setup");
  const [currentSet, setCurrentSet] = useState(1);
  const [restRemaining, setRestRemaining] = useState(0);
  const [setSummaries, setSetSummaries] = useState<SetSummary[]>([]);
  const [cameraError, setCameraError] = useState<string | null>(null);

  const { connected, result, sendFrame, start, stop, socketError } =
    useSupermanSocket();

  const skeleton = result.landmarks?.length
    ? [{ points: result.landmarks, connections: POSE_CONNECTIONS }]
    : [];

  const currentHold = result.hold_seconds ?? 0;
  const progressPct = Math.min(
    100,
    (currentHold / Math.max(1, holdTarget)) * 100,
  );

  // ---- advance a set once the BACKEND confirms this set's hold time is met ----
  // `session_complete` is computed server-side (SupermanAnalyzer._is_complete),
  // from the target_seconds the backend itself was given when the socket
  // opened. We never derive this from currentHold/holdTarget on the client.
  useEffect(() => {
    if (phase !== "active" || !result.session_complete) return;

    stop();

    const summary: SetSummary = {
      setNumber: currentSet,
      holdSeconds: result.hold_seconds ?? 0,
      bestStreak: result.best_streak_seconds ?? 0,
      breakCount: result.break_count ?? 0,
      goodSeconds: result.good_seconds ?? 0,
      flawedSeconds: result.flawed_seconds ?? 0,
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
    // TODO: wire this up to the real backend endpoint once it exists, e.g.
    //   POST /api/workouts/complete { exercise: "superman", holdTarget, totalSets }
    // The frontend must only ever send what the backend already validated
    // here (exercise_complete === true) — it must not decide completion on
    // its own.
    console.log("Superman exercise completed (backend-validated).");
  }, [result.exercise_complete]);

  // ---- rest countdown between sets, then auto-start the next one ----
  useEffect(() => {
    if (phase !== "resting") return;

    if (restRemaining <= 0) {
      const nextSet = currentSet + 1;
      setCurrentSet(nextSet);
      setPhase("active");
      start({
        targetSeconds: holdTarget,
        targetSets: totalSets,
        setNumber: nextSet,
      });
      return;
    }

    const timer = window.setTimeout(() => setRestRemaining((r) => r - 1), 1000);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, restRemaining, start, currentSet, holdTarget, totalSets]);

  function handleStart() {
    setCameraError(null);
    setSetSummaries([]);
    setCurrentSet(1);
    setPhase("active");
    start({ targetSeconds: holdTarget, targetSets: totalSets, setNumber: 1 });
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

  const elapsed = result.elapsed_time ?? 0;

  const totals = useMemo(() => {
    return setSummaries.reduce(
      (acc, s) => ({
        hold: acc.hold + s.holdSeconds,
        bestStreak: Math.max(acc.bestStreak, s.bestStreak),
        breaks: acc.breaks + s.breakCount,
        good: acc.good + s.goodSeconds,
        flawed: acc.flawed + s.flawedSeconds,
      }),
      { hold: 0, bestStreak: 0, breaks: 0, good: 0, flawed: 0 },
    );
  }, [setSummaries]);

  const totalPlannedSeconds = holdTarget * totalSets;

  return (
    <div className="superman-page">
      <div className="superman-header">
        <div className="superman-header-left">
          <h1 className="superman-title">Superman Hold Trainer</h1>
        </div>

        <div className="superman-header-right">
          {phase === "active" && (
            <div className="superman-active-controls">
              <span
                className={`superman-status-dot ${connected ? "live" : ""}`}
              />
              <span className="superman-active-label">
                Set {currentSet}/{totalSets} · {formatSeconds(currentHold)} /{" "}
                {formatSeconds(holdTarget)}
              </span>
              <button className="superman-stop-btn" onClick={handleEndSession}>
                End Session
              </button>
            </div>
          )}

          {phase === "resting" && (
            <div className="superman-active-controls">
              <span className="superman-active-label">
                Resting — next up: Set {currentSet + 1}/{totalSets}
              </span>
              <button className="superman-stop-btn" onClick={handleEndSession}>
                End Session
              </button>
            </div>
          )}

          {phase === "complete" && (
            <div className="superman-active-controls">
              <span className="superman-complete-label">
                ✅ Session complete
              </span>
              <button className="superman-start-btn" onClick={handleReset}>
                New Session
              </button>
            </div>
          )}
        </div>
      </div>

      {socketError && <div className="superman-error">{socketError}</div>}
      {cameraError && <div className="superman-error">{cameraError}</div>}

      <div className="superman-body">
        <div className="superman-camera-col">
          <SupermanCamera
            active={phase === "active"}
            sendFrame={sendFrame}
            skeleton={skeleton}
            onError={setCameraError}
          />

          {phase === "resting" && (
            <div className="superman-rest-overlay-caption">
              <span className="superman-rest-countdown">{restRemaining}s</span>
              <span>until Set {currentSet + 1} starts</span>
            </div>
          )}

          {(phase === "active" || phase === "resting") && (
            <>
              <div className="superman-progress-track">
                <div
                  className="superman-progress-fill"
                  style={{
                    width: `${phase === "active" ? progressPct : 100}%`,
                  }}
                />
              </div>
              <div className="superman-progress-caption">
                {phase === "active"
                  ? `${formatSeconds(currentHold)} / ${formatSeconds(holdTarget)} held`
                  : "Set complete — resting"}
              </div>

              <div className="superman-set-dots">
                {Array.from({ length: totalSets }, (_, i) => i + 1).map((n) => (
                  <span
                    key={n}
                    className={`superman-set-dot ${
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

              <div className="superman-session-summary">
                <div className="superman-session-summary-item good">
                  <span className="k">Good</span>
                  <span className="v">
                    {formatSeconds(result.good_seconds ?? 0)}
                  </span>
                </div>
                <div className="superman-session-summary-item flawed">
                  <span className="k">Flawed</span>
                  <span className="v">
                    {formatSeconds(result.flawed_seconds ?? 0)}
                  </span>
                </div>
                <div className="superman-session-summary-item">
                  <span className="k">Elapsed</span>
                  <span className="v">{elapsed.toFixed(0)}s</span>
                </div>
              </div>
            </>
          )}
        </div>

        <div className="superman-stats-col">
          {phase === "setup" && (
            // TODO(coach-assignment): once a coach/plan API exists, holdTarget
            // and totalSets should come from the user's assigned plan and this
            // picker should become read-only. Whatever's picked here is what
            // actually gets sent to the backend as target_seconds/target_sets —
            // the backend (not this component) decides when it's been met.
            <div className="superman-session-builder">
              <div className="superman-builder-row">
                <span className="superman-builder-label">
                  Hold time per set
                </span>
                <div className="superman-builder-controls">
                  <input
                    type="number"
                    min={5}
                    max={600}
                    value={holdTarget}
                    onChange={(e) =>
                      setHoldTarget(
                        Math.max(5, Math.min(600, Number(e.target.value) || 5)),
                      )
                    }
                    className="superman-reps-input"
                  />
                  <div className="superman-reps-presets">
                    {HOLD_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`superman-reps-preset ${holdTarget === n ? "active" : ""}`}
                        onClick={() => setHoldTarget(n)}
                      >
                        {n}s
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="superman-builder-row">
                <span className="superman-builder-label">Number of sets</span>
                <div className="superman-builder-controls">
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
                    className="superman-reps-input"
                  />
                  <div className="superman-reps-presets">
                    {SET_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`superman-reps-preset ${totalSets === n ? "active" : ""}`}
                        onClick={() => setTotalSets(n)}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="superman-builder-row">
                <span className="superman-builder-label">
                  Rest between sets
                </span>
                <div className="superman-builder-controls">
                  <div className="superman-reps-presets">
                    {REST_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`superman-reps-preset ${restSeconds === n ? "active" : ""}`}
                        onClick={() => setRestSeconds(n)}
                      >
                        {n}s
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="superman-builder-total">
                {totalSets} × {holdTarget}s ={" "}
                <strong>{formatSeconds(totalPlannedSeconds)} total hold</strong>
              </div>

              <div className="superman-setup-tip">
                Lie face-down on the floor, arms extended straight overhead.
                Lift your chest, arms, and legs off the floor together — hips
                stay down and act as the pivot — and hold. The timer only runs
                while your form checks out, and it never loses progress you've
                already earned — if you break form it just pauses until you're
                back in position. Camera must be positioned to your{" "}
                <strong>side</strong>, low to the floor, with your whole body in
                frame.
              </div>

              <button
                className="superman-start-btn full-width"
                onClick={handleStart}
              >
                Start Session ▶
              </button>
            </div>
          )}

          {phase === "resting" && (
            <div className="superman-rest-panel">
              <div className="superman-rest-panel-title">
                Set {currentSet} complete 🎉
              </div>
              <div className="superman-rest-panel-big-countdown">
                {restRemaining}
              </div>
              <div className="superman-rest-panel-caption">
                seconds of rest left
              </div>

              {setSummaries[setSummaries.length - 1] && (
                <div className="superman-arm-grid superman-rest-panel-grid">
                  <div className="superman-arm-grid-item">
                    <span className="k">Held</span>
                    <span className="v">
                      {formatSeconds(
                        setSummaries[setSummaries.length - 1].holdSeconds,
                      )}
                    </span>
                  </div>
                  <div className="superman-arm-grid-item">
                    <span className="k">Best streak</span>
                    <span className="v">
                      {formatSeconds(
                        setSummaries[setSummaries.length - 1].bestStreak,
                      )}
                    </span>
                  </div>
                  <div className="superman-arm-grid-item">
                    <span className="k">Breaks</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].breakCount}
                    </span>
                  </div>
                </div>
              )}

              <button className="superman-stop-btn" onClick={handleSkipRest}>
                Skip rest
              </button>
            </div>
          )}

          {phase === "active" && (
            <div className="superman-single-arm-wrap">
              <SupermanStatsPanel data={result} />

              {result.feedback && (
                <div
                  className={`superman-feedback-box ${
                    result.hold_quality ??
                    (result.hold_state === "broken" ? "needs_improvement" : "")
                  }`}
                >
                  <strong>Coach Feedback</strong>
                  <p>{result.feedback}</p>
                </div>
              )}
            </div>
          )}

          {phase === "complete" && (
            <div className="superman-results-panel">
              <div className="superman-results-totals">
                <div className="superman-session-summary-item">
                  <span className="k">Sets</span>
                  <span className="v">{setSummaries.length}</span>
                </div>
                <div className="superman-session-summary-item">
                  <span className="k">Total held</span>
                  <span className="v">{formatSeconds(totals.hold)}</span>
                </div>
                <div className="superman-session-summary-item">
                  <span className="k">Best streak</span>
                  <span className="v">{formatSeconds(totals.bestStreak)}</span>
                </div>
                <div className="superman-session-summary-item">
                  <span className="k">Total breaks</span>
                  <span className="v">{totals.breaks}</span>
                </div>
                <div className="superman-session-summary-item good">
                  <span className="k">Good</span>
                  <span className="v">{formatSeconds(totals.good)}</span>
                </div>
                <div className="superman-session-summary-item flawed">
                  <span className="k">Flawed</span>
                  <span className="v">{formatSeconds(totals.flawed)}</span>
                </div>
              </div>

              <div className="superman-results-table">
                <div className="superman-results-row superman-results-head">
                  <span>Set</span>
                  <span>Held</span>
                  <span>Best</span>
                  <span>Breaks</span>
                  <span>Good</span>
                </div>
                {setSummaries.map((s) => (
                  <div key={s.setNumber} className="superman-results-row">
                    <span>{s.setNumber}</span>
                    <span>{formatSeconds(s.holdSeconds)}</span>
                    <span>{formatSeconds(s.bestStreak)}</span>
                    <span>{s.breakCount}</span>
                    <span className="good-text">
                      {formatSeconds(s.goodSeconds)}
                    </span>
                  </div>
                ))}
                {setSummaries.length === 0 && (
                  <div className="superman-results-row">
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

export default SupermanPage;
