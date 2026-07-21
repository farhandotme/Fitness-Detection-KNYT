import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import useTreePoseSocket from "../hooks/useTreePoseSocket";
import TreePoseCamera from "../conponents/TreePoseCamera";
import TreePoseStatsPanel from "../conponents/TreePoseStatsPanel";
import "./TreePosePage.css";

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
  [27, 29],
  [29, 31],
  [27, 31],
  [28, 30],
  [30, 32],
  [28, 32],
];

const HOLD_PRESETS = [15, 20, 30, 45];
const SET_PRESETS = [1, 2, 3, 4];
const REST_PRESETS = [15, 20, 30, 45];

type Phase = "setup" | "active" | "resting" | "complete";

interface SetSummary {
  setNumber: number;
  leftSeconds: number;
  rightSeconds: number;
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

function TreePosePage() {
  const navigate = useNavigate();

  const [holdTarget, setHoldTarget] = useState(20);
  const [totalSets, setTotalSets] = useState(2);
  const [restSeconds, setRestSeconds] = useState(20);

  const [phase, setPhase] = useState<Phase>("setup");
  const [currentSet, setCurrentSet] = useState(1);
  const [restRemaining, setRestRemaining] = useState(0);
  const [setSummaries, setSetSummaries] = useState<SetSummary[]>([]);
  const [cameraError, setCameraError] = useState<string | null>(null);

  const { connected, result, sendFrame, start, stop, socketError } =
    useTreePoseSocket();

  const skeleton = result.landmarks?.length
    ? [{ points: result.landmarks, connections: POSE_CONNECTIONS }]
    : [];

  const leftPct = Math.min(100, ((result.left_seconds ?? 0) / Math.max(1, holdTarget)) * 100);
  const rightPct = Math.min(100, ((result.right_seconds ?? 0) / Math.max(1, holdTarget)) * 100);

  // ---- advance a set once the BACKEND confirms both legs hit their target ----
  // `session_complete` is computed server-side (TreePoseAnalyzer._is_complete),
  // from the target_seconds the backend itself was given when the socket
  // opened. We never derive this from left/right seconds vs holdTarget here.
  useEffect(() => {
    if (phase !== "active" || !result.session_complete) return;

    stop();

    const summary: SetSummary = {
      setNumber: currentSet,
      leftSeconds: result.left_seconds ?? 0,
      rightSeconds: result.right_seconds ?? 0,
      bestStreak: result.best_streak_seconds ?? 0,
      breakCount: result.break_count ?? 0,
      goodSeconds: result.good_seconds ?? 0,
      flawedSeconds: result.flawed_seconds ?? 0,
    };
    setSetSummaries((prev) => [...prev, summary]);

    // exercise_complete is also backend-validated: true only once every
    // set in the plan hit its target on both legs. This is the boolean
    // that should trigger persisting "user completed this exercise".
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
    //   POST /api/workouts/complete { exercise: "tree-pose", holdTarget, totalSets }
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
        left: acc.left + s.leftSeconds,
        right: acc.right + s.rightSeconds,
        bestStreak: Math.max(acc.bestStreak, s.bestStreak),
        breaks: acc.breaks + s.breakCount,
        good: acc.good + s.goodSeconds,
        flawed: acc.flawed + s.flawedSeconds,
      }),
      { left: 0, right: 0, bestStreak: 0, breaks: 0, good: 0, flawed: 0 },
    );
  }, [setSummaries]);

  const totalPlannedSeconds = holdTarget * totalSets * 2; // both legs, per set

  return (
    <div className="tree-page">
      <div className="tree-header">
        <div className="tree-header-left">
          <button className="tree-back-btn" onClick={() => navigate("/exercises")}>
            ← Library
          </button>
          <h1 className="tree-title">Tree Pose Trainer</h1>
        </div>

        <div className="tree-header-right">
          {phase === "active" && (
            <div className="tree-active-controls">
              <span className={`tree-status-dot ${connected ? "live" : ""}`} />
              <span className="tree-active-label">
                Set {currentSet}/{totalSets} · L {formatSeconds(result.left_seconds ?? 0)} / R{" "}
                {formatSeconds(result.right_seconds ?? 0)} (target {formatSeconds(holdTarget)} each)
              </span>
              <button className="tree-stop-btn" onClick={handleEndSession}>
                End Session
              </button>
            </div>
          )}

          {phase === "resting" && (
            <div className="tree-active-controls">
              <span className="tree-active-label">
                Resting — next up: Set {currentSet + 1}/{totalSets}
              </span>
              <button className="tree-stop-btn" onClick={handleEndSession}>
                End Session
              </button>
            </div>
          )}

          {phase === "complete" && (
            <div className="tree-active-controls">
              <span className="tree-complete-label">✅ Session complete</span>
              <button className="tree-start-btn" onClick={handleReset}>
                New Session
              </button>
            </div>
          )}
        </div>
      </div>

      {socketError && <div className="tree-error">{socketError}</div>}
      {cameraError && <div className="tree-error">{cameraError}</div>}

      <div className="tree-body">
        <div className="tree-camera-col">
          <TreePoseCamera
            active={phase === "active"}
            sendFrame={sendFrame}
            skeleton={skeleton}
            onError={setCameraError}
          />

          {phase === "resting" && (
            <div className="tree-rest-overlay-caption">
              <span className="tree-rest-countdown">{restRemaining}s</span>
              <span>until Set {currentSet + 1} starts</span>
            </div>
          )}

          {(phase === "active" || phase === "resting") && (
            <>
              <div className="tree-dual-progress">
                <div className="tree-dual-progress-row">
                  <span className="tree-dual-progress-label">L</span>
                  <div className="tree-progress-track">
                    <div
                      className="tree-progress-fill tree-progress-fill--left"
                      style={{ width: `${phase === "active" ? leftPct : 100}%` }}
                    />
                  </div>
                </div>
                <div className="tree-dual-progress-row">
                  <span className="tree-dual-progress-label">R</span>
                  <div className="tree-progress-track">
                    <div
                      className="tree-progress-fill tree-progress-fill--right"
                      style={{ width: `${phase === "active" ? rightPct : 100}%` }}
                    />
                  </div>
                </div>
              </div>
              <div className="tree-progress-caption">
                {phase === "active"
                  ? `L ${formatSeconds(result.left_seconds ?? 0)} / R ${formatSeconds(result.right_seconds ?? 0)} held (target ${formatSeconds(holdTarget)} each)`
                  : "Set complete — resting"}
              </div>

              <div className="tree-set-dots">
                {Array.from({ length: totalSets }, (_, i) => i + 1).map((n) => (
                  <span
                    key={n}
                    className={`tree-set-dot ${
                      n < currentSet || (n === currentSet && phase === "resting")
                        ? "done"
                        : n === currentSet
                          ? "current"
                          : ""
                    }`}
                  />
                ))}
              </div>

              <div className="tree-session-summary">
                <div className="tree-summary-item good">
                  <span className="k">Good</span>
                  <span className="v">{formatSeconds(result.good_seconds ?? 0)}</span>
                </div>
                <div className="tree-summary-item flawed">
                  <span className="k">Flawed</span>
                  <span className="v">{formatSeconds(result.flawed_seconds ?? 0)}</span>
                </div>
                <div className="tree-summary-item">
                  <span className="k">Elapsed</span>
                  <span className="v">{elapsed.toFixed(0)}s</span>
                </div>
              </div>
            </>
          )}
        </div>

        <div className="tree-stats-col">
          {phase === "setup" && (
            // TODO(coach-assignment): once a coach/plan API exists, holdTarget
            // and totalSets should come from the user's assigned plan (fetched
            // here) and this picker should become read-only display, not
            // user-editable inputs. Whatever value is picked here is what
            // actually gets sent to the backend as target_seconds/target_sets —
            // and the backend (not this component) decides when it's been met.
            <div className="tree-session-builder">
              <div className="tree-builder-row">
                <span className="tree-builder-label">Hold time per leg</span>
                <div className="tree-builder-controls">
                  <input
                    type="number"
                    min={5}
                    max={600}
                    value={holdTarget}
                    onChange={(e) =>
                      setHoldTarget(Math.max(5, Math.min(600, Number(e.target.value) || 5)))
                    }
                    className="tree-reps-input"
                  />
                  <div className="tree-reps-presets">
                    {HOLD_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`tree-reps-preset ${holdTarget === n ? "active" : ""}`}
                        onClick={() => setHoldTarget(n)}
                      >
                        {n}s
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="tree-builder-row">
                <span className="tree-builder-label">Number of sets</span>
                <div className="tree-builder-controls">
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={totalSets}
                    onChange={(e) =>
                      setTotalSets(Math.max(1, Math.min(20, Number(e.target.value) || 1)))
                    }
                    className="tree-reps-input"
                  />
                  <div className="tree-reps-presets">
                    {SET_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`tree-reps-preset ${totalSets === n ? "active" : ""}`}
                        onClick={() => setTotalSets(n)}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="tree-builder-row">
                <span className="tree-builder-label">Rest between sets</span>
                <div className="tree-builder-controls">
                  <div className="tree-reps-presets">
                    {REST_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`tree-reps-preset ${restSeconds === n ? "active" : ""}`}
                        onClick={() => setRestSeconds(n)}
                      >
                        {n}s
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="tree-builder-total">
                {totalSets} × {holdTarget}s × 2 legs ={" "}
                <strong>{formatSeconds(totalPlannedSeconds)} total hold</strong>
              </div>

              <div className="tree-setup-tip">
                Stand facing the camera, full body in frame. Lift one foot and
                press it against your standing leg's calf or thigh, above knee
                height, and stand tall. Each leg is timed separately — a set
                only finishes once both legs have held for the full target
                time. The timer only runs while your form checks out, and it
                never loses progress you've already earned — if you break
                form it just pauses until you're back in position.
              </div>

              <button className="tree-start-btn full-width" onClick={handleStart}>
                Start Session ▶
              </button>
            </div>
          )}

          {phase === "resting" && (
            <div className="tree-rest-panel">
              <div className="tree-rest-panel-title">Set {currentSet} complete 🎉</div>
              <div className="tree-rest-panel-big-countdown">{restRemaining}</div>
              <div className="tree-rest-panel-caption">seconds of rest left</div>

              {setSummaries[setSummaries.length - 1] && (
                <div className="arm-grid tree-rest-panel-grid">
                  <div className="arm-grid-item">
                    <span className="k">Left held</span>
                    <span className="v">
                      {formatSeconds(setSummaries[setSummaries.length - 1].leftSeconds)}
                    </span>
                  </div>
                  <div className="arm-grid-item">
                    <span className="k">Right held</span>
                    <span className="v">
                      {formatSeconds(setSummaries[setSummaries.length - 1].rightSeconds)}
                    </span>
                  </div>
                  <div className="arm-grid-item">
                    <span className="k">Best streak</span>
                    <span className="v">
                      {formatSeconds(setSummaries[setSummaries.length - 1].bestStreak)}
                    </span>
                  </div>
                  <div className="arm-grid-item">
                    <span className="k">Breaks</span>
                    <span className="v">{setSummaries[setSummaries.length - 1].breakCount}</span>
                  </div>
                </div>
              )}

              <button className="tree-stop-btn" onClick={handleSkipRest}>
                Skip rest
              </button>
            </div>
          )}

          {phase === "active" && (
            <div className="tree-single-wrap">
              <TreePoseStatsPanel data={result} />

              {result.feedback && (
                <div
                  className={`feedback-box ${result.hold_quality ?? (result.hold_state === "broken" ? "needs_improvement" : "")}`}
                >
                  <strong>Coach Feedback</strong>
                  <p>{result.feedback}</p>
                </div>
              )}
            </div>
          )}

          {phase === "complete" && (
            <div className="tree-results-panel">
              <div className="tree-results-totals">
                <div className="tree-summary-item">
                  <span className="k">Sets</span>
                  <span className="v">{setSummaries.length}</span>
                </div>
                <div className="tree-summary-item">
                  <span className="k">Total left</span>
                  <span className="v">{formatSeconds(totals.left)}</span>
                </div>
                <div className="tree-summary-item">
                  <span className="k">Total right</span>
                  <span className="v">{formatSeconds(totals.right)}</span>
                </div>
                <div className="tree-summary-item">
                  <span className="k">Best streak</span>
                  <span className="v">{formatSeconds(totals.bestStreak)}</span>
                </div>
                <div className="tree-summary-item">
                  <span className="k">Total breaks</span>
                  <span className="v">{totals.breaks}</span>
                </div>
                <div className="tree-summary-item good">
                  <span className="k">Good</span>
                  <span className="v">{formatSeconds(totals.good)}</span>
                </div>
                <div className="tree-summary-item flawed">
                  <span className="k">Flawed</span>
                  <span className="v">{formatSeconds(totals.flawed)}</span>
                </div>
              </div>

              <div className="tree-results-table">
                <div className="tree-results-row tree-results-head">
                  <span>Set</span>
                  <span>Left</span>
                  <span>Right</span>
                  <span>Best</span>
                  <span>Breaks</span>
                </div>
                {setSummaries.map((s) => (
                  <div key={s.setNumber} className="tree-results-row">
                    <span>{s.setNumber}</span>
                    <span>{formatSeconds(s.leftSeconds)}</span>
                    <span>{formatSeconds(s.rightSeconds)}</span>
                    <span>{formatSeconds(s.bestStreak)}</span>
                    <span>{s.breakCount}</span>
                  </div>
                ))}
                {setSummaries.length === 0 && (
                  <div className="tree-results-row">
                    <span className="empty-hint">Session ended before any set finished.</span>
                  </div>
                )}
              </div>

              <button className="tree-start-btn full-width" onClick={() => navigate("/exercises")}>
                Back to Exercise Library
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default TreePosePage;
