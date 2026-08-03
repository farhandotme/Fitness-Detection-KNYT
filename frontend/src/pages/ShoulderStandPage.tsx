import { useEffect, useMemo, useState } from "react";
import useShoulderStandSocket from "../hooks/useShoulderStandSocket";
import ShoulderStandCamera from "../conponents/ShoulderStandCamera";
import ShoulderStandStatsPanel from "../conponents/ShoulderStandStatsPanel";
import "../pages/BicepPage.css";
import "./ShoulderStandPage.css";

// Shoulders, hips, and both full legs — the "candle" alignment check
// this exercise is built around needs the full ankle-hip-shoulder chain
// visible, not just the torso.
const POSE_CONNECTIONS: [number, number][] = [
  [11, 12], // shoulder-shoulder
  [23, 24], // hip-hip
  [11, 23], // left shoulder-hip
  [12, 24], // right shoulder-hip
  [23, 25], // left hip-knee
  [25, 27], // left knee-ankle
  [24, 26], // right hip-knee
  [26, 28], // right knee-ankle
];

const HOLD_PRESETS = [15, 30, 45, 60];
const SET_PRESETS = [1, 2, 3];
const REST_PRESETS = [20, 30, 45];

type Phase = "setup" | "active" | "resting" | "complete";

interface SetSummary {
  setNumber: number;
  holdTime: number;
  bestHoldTime: number;
  interruptions: number;
  targetReached: boolean;
}

function formatTime(seconds: number): string {
  const s = Math.max(0, seconds);
  const m = Math.floor(s / 60);
  const rem = Math.round(s % 60);
  return m > 0 ? `${m}:${String(rem).padStart(2, "0")}` : `${s.toFixed(0)}s`;
}

function ShoulderStandPage() {
  const [targetHoldSeconds, setTargetHoldSeconds] = useState(30);
  const [totalSets, setTotalSets] = useState(2);
  const [restSeconds, setRestSeconds] = useState(30);

  const [phase, setPhase] = useState<Phase>("setup");
  const [currentSet, setCurrentSet] = useState(1);
  const [restRemaining, setRestRemaining] = useState(0);
  const [setSummaries, setSetSummaries] = useState<SetSummary[]>([]);
  const [cameraError, setCameraError] = useState<string | null>(null);

  const { connected, result, sendFrame, start, stop, socketError } =
    useShoulderStandSocket();

  const skeleton = result.landmarks?.length
    ? [{ points: result.landmarks, connections: POSE_CONNECTIONS }]
    : [];

  function startSet(setNumber: number) {
    setCurrentSet(setNumber);
    setPhase("active");
    start({
      targetHoldSeconds,
      targetSets: totalSets,
      setNumber,
    });
  }

  // ---- advance a set once the BACKEND confirms the hold target is met ----
  // `session_complete` is computed server-side (ShoulderStandAnalyzer),
  // from the target_hold_seconds the backend itself was given when the
  // socket opened. We never derive this from the client's own hold_time.
  useEffect(() => {
    if (phase !== "active" || !result.session_complete) return;

    stop();

    const summary: SetSummary = {
      setNumber: currentSet,
      holdTime: result.hold_time ?? 0,
      bestHoldTime: result.best_hold_time ?? 0,
      interruptions: result.interruption_count ?? 0,
      targetReached: true,
    };
    setSetSummaries((prev) => [...prev, summary]);

    if (result.exercise_complete) {
      setPhase("complete");
    } else {
      setRestRemaining(restSeconds);
      setPhase("resting");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, result.session_complete, currentSet, restSeconds, result, stop]);

  // ---- persist completion once the backend confirms the whole plan is done ----
  useEffect(() => {
    if (!result.exercise_complete) return;
    // TODO: wire this up to the real backend endpoint once it exists, e.g.
    //   POST /api/workouts/complete { exercise: "shoulder-stand", targetHoldSeconds, totalSets }
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
      startSet(currentSet + 1);
      return;
    }

    const timer = window.setTimeout(() => setRestRemaining((r) => r - 1), 1000);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, restRemaining]);

  function handleStart() {
    setCameraError(null);
    setSetSummaries([]);
    startSet(1);
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
        holdTime: acc.holdTime + s.holdTime,
        interruptions: acc.interruptions + s.interruptions,
        setsCompleted: acc.setsCompleted + (s.targetReached ? 1 : 0),
      }),
      { holdTime: 0, interruptions: 0, setsCompleted: 0 },
    );
  }, [setSummaries]);

  return (
    <div className="bicep-page sstand-page">
      <div className="bicep-header">
        <div className="bicep-header-left">
          <h1 className="bicep-title">Shoulder Stand Trainer</h1>
        </div>

        <div className="bicep-header-right">
          {phase === "active" && (
            <div className="active-controls">
              <span className={`status-dot ${connected ? "live" : ""}`} />
              <span className="active-label">
                Set {currentSet}/{totalSets} ·{" "}
                {formatTime(result.hold_time ?? 0)}/
                {formatTime(targetHoldSeconds)}
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
          <ShoulderStandCamera
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
          )}
        </div>

        <div className="bicep-stats-col">
          {phase === "setup" && (
            // TODO(coach-assignment): once a coach/plan API exists, these
            // values should come from the user's assigned plan (fetched
            // here) and this picker should become read-only display, not
            // user-editable inputs. Whatever's picked here is what actually
            // gets sent to the backend as target_hold_seconds/target_sets —
            // and the backend (not this component) decides when it's met.
            <div className="session-builder">
              <div className="builder-row">
                <span className="builder-label">Hold target</span>
                <div className="builder-controls">
                  <input
                    type="number"
                    min={5}
                    max={600}
                    value={targetHoldSeconds}
                    onChange={(e) =>
                      setTargetHoldSeconds(
                        Math.max(5, Math.min(600, Number(e.target.value) || 5)),
                      )
                    }
                    className="reps-input"
                  />
                  <div className="reps-presets">
                    {HOLD_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`reps-preset ${targetHoldSeconds === n ? "active" : ""}`}
                        onClick={() => setTargetHoldSeconds(n)}
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
                    max={10}
                    value={totalSets}
                    onChange={(e) =>
                      setTotalSets(
                        Math.max(1, Math.min(10, Number(e.target.value) || 1)),
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
                {totalSets} × {targetHoldSeconds}s ={" "}
                <strong>
                  {formatTime(totalSets * targetHoldSeconds)} total hold
                </strong>
              </div>

              <div className="sstand-setup-tip">
                Lie on your back, then lift your hips and legs straight up
                overhead until your body forms one straight line from shoulders
                to feet, hands supporting your lower back. Timing only counts
                while your form is correct — camera filmed from the side, full
                body in frame.
              </div>

              <div className="sstand-warning">
                ⚠️ This is an inversion — it puts weight through your neck and
                shoulders. This tool checks body alignment only; it cannot
                verify your neck position. Keep your chin gently tucked and your
                weight on your shoulders, not your neck. Stop immediately if you
                feel any neck strain, and learn this pose from a qualified
                teacher first if you're new to it.
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
                    <span className="k">Hold time</span>
                    <span className="v">
                      {formatTime(
                        setSummaries[setSummaries.length - 1].holdTime,
                      )}
                    </span>
                  </div>
                  <div className="arm-grid-item">
                    <span className="k">Interruptions</span>
                    <span className="v">
                      {setSummaries[setSummaries.length - 1].interruptions}
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
              <ShoulderStandStatsPanel data={result} />

              {result.feedback && (
                <div
                  className={`feedback-box ${result.form_ok ? "good" : "needs_improvement"}`}
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
                  <span className="k">Sets completed</span>
                  <span className="v">{totals.setsCompleted}</span>
                </div>
                <div className="session-summary-item good">
                  <span className="k">Total hold time</span>
                  <span className="v">{formatTime(totals.holdTime)}</span>
                </div>
                <div className="session-summary-item">
                  <span className="k">Interruptions</span>
                  <span className="v">{totals.interruptions}</span>
                </div>
              </div>

              <div className="results-table">
                <div className="results-row results-head">
                  <span>Set</span>
                  <span>Hold time</span>
                  <span>Interruptions</span>
                </div>
                {setSummaries.map((s) => (
                  <div key={s.setNumber} className="results-row">
                    <span>{s.setNumber}</span>
                    <span>{formatTime(s.holdTime)}</span>
                    <span>{s.interruptions}</span>
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

export default ShoulderStandPage;
