import { useEffect, useMemo, useState } from "react";
import useSidePlankSocket from "../hooks/useSidePlankSocket";
import SidePlankCamera from "../conponents/SidePlankCamera";
import SidePlankStatsPanel from "../conponents/SidePlankStatsPanel";
import "./BicepPage.css";
import "./SidePlankPage.css";

// Side-on skeleton — only the supporting-side limbs are meaningfully
// tracked (the analyzer picks one active side), but drawing both sides
// keeps the overlay useful while the person is still getting into position.
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
const SET_PRESETS = [1, 2, 3, 4];
const REST_PRESETS = [20, 30, 45, 60];

type Phase = "setup" | "active" | "resting" | "complete";

interface SetSummary {
  setNumber: number;
  holdSeconds: number;
  goodSeconds: number;
  flawedSeconds: number;
  bestStreak: number;
  breakCount: number;
  avgFormScore: number | null;
}

function SidePlankPage() {
  const [targetSeconds, setTargetSeconds] = useState(30);
  const [totalSets, setTotalSets] = useState(3);
  const [restSeconds, setRestSeconds] = useState(30);

  const [phase, setPhase] = useState<Phase>("setup");
  const [currentSet, setCurrentSet] = useState(1);
  const [restRemaining, setRestRemaining] = useState(0);
  const [setSummaries, setSetSummaries] = useState<SetSummary[]>([]);
  const [cameraError, setCameraError] = useState<string | null>(null);

  const { connected, result, lastEvent, sendFrame, start, stop, socketError } =
    useSidePlankSocket();

  const skeleton = result.landmarks?.length
    ? [{ points: result.landmarks, connections: POSE_CONNECTIONS }]
    : [];

  const currentHold = result.hold_seconds ?? 0;
  const progressPct = Math.min(100, (currentHold / Math.max(1, targetSeconds)) * 100);

  // ---- advance a set to completion once the target hold time is hit ----
  useEffect(() => {
    if (phase !== "active" || currentHold < targetSeconds) return;

    stop();

    const summary: SetSummary = {
      setNumber: currentSet,
      holdSeconds: currentHold,
      goodSeconds: result.good_seconds ?? 0,
      flawedSeconds: result.flawed_seconds ?? 0,
      bestStreak: result.best_streak_seconds ?? 0,
      breakCount: result.break_count ?? 0,
      avgFormScore: result.avg_form_score ?? null,
    };
    setSetSummaries((prev) => [...prev, summary]);

    if (currentSet >= totalSets) {
      setPhase("complete");
    } else {
      setRestRemaining(restSeconds);
      setPhase("resting");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, currentHold, targetSeconds, currentSet, totalSets, restSeconds, result, stop]);

  // ---- rest countdown between sets, then auto-start the next one ----
  useEffect(() => {
    if (phase !== "resting") return;

    if (restRemaining <= 0) {
      setCurrentSet((s) => s + 1);
      setPhase("active");
      start();
      return;
    }

    const timer = window.setTimeout(() => setRestRemaining((r) => r - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [phase, restRemaining, start]);

  function handleStart() {
    setCameraError(null);
    setSetSummaries([]);
    setCurrentSet(1);
    setPhase("active");
    start();
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
        bestStreak: Math.max(acc.bestStreak, s.bestStreak),
      }),
      { hold: 0, good: 0, flawed: 0, breaks: 0, bestStreak: 0 },
    );
  }, [setSummaries]);

  const totalPlannedSeconds = targetSeconds * totalSets;

  return (
    <div className="bicep-page sideplank-page">
      <div className="bicep-header">
        <div className="bicep-header-left">
          <h1 className="bicep-title">Side Plank Trainer</h1>
        </div>

        <div className="bicep-header-right">
          {phase === "active" && (
            <div className="active-controls">
              <span className={`status-dot ${connected ? "live" : ""}`} />
              <span className="active-label">
                Set {currentSet}/{totalSets} · {currentHold.toFixed(0)}/{targetSeconds}s
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
          <SidePlankCamera
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
                  style={{ width: `${phase === "active" ? progressPct : 100}%` }}
                />
              </div>
              <div className="progress-caption">
                {phase === "active"
                  ? `${currentHold.toFixed(0)} / ${targetSeconds}s held`
                  : "Set complete — resting"}
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
                  <span className="k">Good time</span>
                  <span className="v">{sessionGoodSeconds.toFixed(0)}s</span>
                </div>
                <div className="session-summary-item flawed">
                  <span className="k">Flawed time</span>
                  <span className="v">{sessionFlawedSeconds.toFixed(0)}s</span>
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
            <div className="session-builder">
              <div className="builder-row">
                <span className="builder-label">Hold target per set</span>
                <div className="builder-controls">
                  <input
                    type="number"
                    min={5}
                    max={300}
                    value={targetSeconds}
                    onChange={(e) =>
                      setTargetSeconds(
                        Math.max(5, Math.min(300, Number(e.target.value) || 5)),
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
                <span className="builder-label">Number of sets (one side each — alternate!)</span>
                <div className="builder-controls">
                  <input
                    type="number"
                    min={1}
                    max={10}
                    value={totalSets}
                    onChange={(e) =>
                      setTotalSets(Math.max(1, Math.min(10, Number(e.target.value) || 1)))
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
                <strong>{totalPlannedSeconds}s total hold time</strong>
              </div>

              <div className="squat-setup-tip">
                Lie on your side, propped up on your forearm with your elbow
                under your shoulder, legs stacked and straight, and lift your
                hips so your body forms a straight line from head to feet.
                Position the camera to your side, far enough back that your
                whole body fits in frame. The timer only runs while your form
                holds — it pauses automatically if you break position, and
                picks back up the moment you do.
              </div>

              <button className="start-btn full-width" onClick={handleStart}>
                Start Session ▶
              </button>
            </div>
          )}

          {phase === "resting" && (
            <div className="rest-panel">
              <div className="rest-panel-title">Set {currentSet} complete 🎉</div>
              <div className="rest-panel-big-countdown">{restRemaining}</div>
              <div className="rest-panel-caption">seconds of rest left</div>

              {setSummaries[setSummaries.length - 1] && (
                <div className="arm-grid rest-panel-grid">
                  <div className="arm-grid-item">
                    <span className="k">Held</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].holdSeconds.toFixed(0)}s
                    </span>
                  </div>
                  <div className="arm-grid-item">
                    <span className="k">Best streak</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].bestStreak.toFixed(0)}s
                    </span>
                  </div>
                  <div className="arm-grid-item">
                    <span className="k">Breaks</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].breakCount}
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
              <SidePlankStatsPanel data={result} />

              {(lastEvent.feedback || result.feedback) && (
                <div
                  className={`feedback-box ${
                    lastEvent.kind === "break" ? "needs_improvement" : (result.hold_quality ?? "")
                  }`}
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
                  <span className="k">Total hold</span>
                  <span className="v">{totals.hold.toFixed(0)}s</span>
                </div>
                <div className="session-summary-item good">
                  <span className="k">Good time</span>
                  <span className="v">{totals.good.toFixed(0)}s</span>
                </div>
                <div className="session-summary-item flawed">
                  <span className="k">Flawed time</span>
                  <span className="v">{totals.flawed.toFixed(0)}s</span>
                </div>
                <div className="session-summary-item">
                  <span className="k">Best streak</span>
                  <span className="v">{totals.bestStreak.toFixed(0)}s</span>
                </div>
              </div>

              <div className="results-table">
                <div className="results-row results-head">
                  <span>Set</span>
                  <span>Held</span>
                  <span>Best streak</span>
                  <span>Breaks</span>
                  <span>Avg score</span>
                </div>
                {setSummaries.map((s) => (
                  <div key={s.setNumber} className="results-row">
                    <span>{s.setNumber}</span>
                    <span>{s.holdSeconds.toFixed(0)}s</span>
                    <span className="good-text">{s.bestStreak.toFixed(0)}s</span>
                    <span className="flawed-text">{s.breakCount}</span>
                    <span>{s.avgFormScore != null ? s.avgFormScore : "—"}</span>
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

export default SidePlankPage;
