import { useEffect, useMemo, useState } from "react";
import useSingleLegSquatSocket, {
  type SquatMode,
  type SquatSide,
} from "../hooks/useSingleLegSquatSocket";
import SingleLegSquatCamera from "../conponents/SingleLegSquatCamera";
import SingleLegSquatStatsPanel from "../conponents/SingleLegSquatStatsPanel";
import "../pages/BicepPage.css";
import "./SingleLegSquatPage.css";

// Shoulders, hips, both full legs, and both feet — the free leg needs to
// stay visible for the "touched down" / hop checks, not just the stance leg.
const POSE_CONNECTIONS: [number, number][] = [
  [11, 12], // shoulder-shoulder
  [23, 24], // hip-hip
  [11, 23], // left shoulder-hip
  [12, 24], // right shoulder-hip
  [23, 25], // left hip-knee
  [25, 27], // left knee-ankle
  [27, 31], // left ankle-foot index
  [24, 26], // right hip-knee
  [26, 28], // right knee-ankle
  [28, 32], // right ankle-foot index
];

const REP_PRESETS = [5, 8, 10, 12];
const SET_PRESETS = [1, 2, 3];
const REST_PRESETS = [15, 20, 30, 45];

const MODE_INFO: Record<SquatMode, { label: string; blurb: string }> = {
  assisted: {
    label: "Assisted",
    blurb:
      "Shallow, balance-friendly depth. Light touch support (wall, chair, doorframe) is fine.",
  },
  standard: {
    label: "Standard",
    blurb: "A normal single-leg squat depth — no support, moderate bend.",
  },
  deep: {
    label: "Deep / pistol-style",
    blurb:
      "Full depth, unassisted. Balance and mobility matter a lot here — go slowly.",
  },
};

type Phase =
  | "setup"
  | "active"
  | "resting"
  | "switch_side"
  | "complete";

interface SetSummary {
  side: SquatSide;
  setNumber: number;
  reps: number;
  goodReps: number;
  flawedReps: number;
  elapsedTime: number;
}

function SingleLegSquatPage() {
  const [repsPerSet, setRepsPerSet] = useState(8);
  const [setsPerSide, setSetsPerSide] = useState(2);
  const [restSeconds, setRestSeconds] = useState(20);
  const [mode, setMode] = useState<SquatMode>("standard");

  const [phase, setPhase] = useState<Phase>("setup");
  const [activeSide, setActiveSide] = useState<SquatSide>("left");
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
  } = useSingleLegSquatSocket();

  const skeleton = result.landmarks?.length
    ? [{ points: result.landmarks, connections: POSE_CONNECTIONS }]
    : [];

  const currentReps = result.rep_count ?? 0;
  const progressPct = Math.min(
    100,
    (currentReps / Math.max(1, repsPerSet)) * 100,
  );

  function startSide(side: SquatSide, setNumber: number) {
    setActiveSide(side);
    setCurrentSet(setNumber);
    setPhase("active");
    start({
      targetReps: repsPerSet,
      targetSets: setsPerSide,
      setNumber,
      side,
      mode,
    });
  }

  // ---- advance once the BACKEND confirms this set's reps are done ----
  // `session_complete` / `exercise_complete` are computed server-side
  // (SingleLegSquatAnalyzer / SingleLegSquatSession) from the target_reps
  // and target_sets the backend itself was given when the socket opened.
  // We never derive this from currentReps/repsPerSet on the client.
  useEffect(() => {
    if (phase !== "active" || !result.session_complete) return;

    stop();

    const summary: SetSummary = {
      side: activeSide,
      setNumber: currentSet,
      reps: currentReps,
      goodReps: result.good_reps ?? 0,
      flawedReps: result.flawed_reps ?? 0,
      elapsedTime: result.elapsed_time ?? 0,
    };
    setSetSummaries((prev) => [...prev, summary]);

    // exercise_complete is backend-validated: true once every set on THIS
    // side hit its target. On the left side that means "switch to right";
    // on the right side it means the whole session is done.
    if (result.exercise_complete) {
      if (activeSide === "left") {
        setPhase("switch_side");
      } else {
        setPhase("complete");
      }
    } else {
      setRestRemaining(restSeconds);
      setPhase("resting");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, result.session_complete, activeSide, currentSet, restSeconds, result, stop]);

  // ---- persist completion once the backend confirms the whole plan is done ----
  useEffect(() => {
    if (phase !== "complete") return;
    // TODO: wire this up to the real backend endpoint once it exists, e.g.
    //   POST /api/workouts/complete { exercise: "single-leg-squat", repsPerSet, setsPerSide, mode }
    // That endpoint is what should write the "user completed this exercise"
    // record to MongoDB. The frontend must only ever send what the backend
    // already validated (both sides' exercise_complete === true) — it must
    // not decide completion on its own.
    console.log(
      "Both sides complete (backend-validated) — ready to persist to DB.",
    );
  }, [phase]);

  // ---- rest countdown between sets, then auto-start the next one ----
  useEffect(() => {
    if (phase !== "resting") return;

    if (restRemaining <= 0) {
      startSide(activeSide, currentSet + 1);
      return;
    }

    const timer = window.setTimeout(() => setRestRemaining((r) => r - 1), 1000);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, restRemaining]);

  function handleStart() {
    setCameraError(null);
    setSetSummaries([]);
    startSide("left", 1);
  }

  function handleSwitchSideConfirmed() {
    startSide("right", 1);
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
    setActiveSide("left");
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

  const leftSummaries = setSummaries.filter((s) => s.side === "left");
  const rightSummaries = setSummaries.filter((s) => s.side === "right");
  const totalPlannedReps = repsPerSet * setsPerSide * 2;

  return (
    <div className="bicep-page squat-page">
      <div className="bicep-header">
        <div className="bicep-header-left">
          <h1 className="bicep-title">Single Leg Squat Trainer</h1>
        </div>

        <div className="bicep-header-right">
          {phase === "active" && (
            <div className="active-controls">
              <span className={`status-dot ${connected ? "live" : ""}`} />
              <span className="active-label">
                {activeSide === "left" ? "Left" : "Right"} · Set {currentSet}/
                {setsPerSide} · {currentReps}/{repsPerSet} reps
              </span>
              <button className="stop-btn" onClick={handleEndSession}>
                End Session
              </button>
            </div>
          )}

          {phase === "resting" && (
            <div className="active-controls">
              <span className="active-label">
                Resting — next: {activeSide === "left" ? "Left" : "Right"} set{" "}
                {currentSet + 1}/{setsPerSide}
              </span>
              <button className="stop-btn" onClick={handleEndSession}>
                End Session
              </button>
            </div>
          )}

          {phase === "switch_side" && (
            <div className="active-controls">
              <span className="active-label">Left leg done — switch sides</span>
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
          <SingleLegSquatCamera
            active={phase === "active"}
            sendFrame={sendFrame}
            skeleton={skeleton}
            onError={setCameraError}
          />

          {phase === "resting" && (
            <div className="rest-overlay-caption">
              <span className="rest-countdown">{restRemaining}s</span>
              <span>
                until {activeSide === "left" ? "Left" : "Right"} set{" "}
                {currentSet + 1}
              </span>
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
                  ? `${currentReps} / ${repsPerSet} reps`
                  : "Set complete — resting"}
              </div>

              <div className="set-dots">
                {Array.from({ length: setsPerSide }, (_, i) => i + 1).map(
                  (n) => (
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
                  ),
                )}
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
            // TODO(coach-assignment): once a coach/plan API exists, these
            // values should come from the user's assigned plan (fetched
            // here) and this picker should become read-only display, not
            // user-editable inputs. Whatever's picked here is what actually
            // gets sent to the backend as target_reps/target_sets/mode —
            // and the backend (not this component) decides when it's met.
            <div className="session-builder">
              <div className="builder-row">
                <span className="builder-label">Reps per set (per side)</span>
                <div className="builder-controls">
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
                    className="reps-input"
                  />
                  <div className="reps-presets">
                    {REP_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`reps-preset ${repsPerSet === n ? "active" : ""}`}
                        onClick={() => setRepsPerSet(n)}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="builder-row">
                <span className="builder-label">Sets per side</span>
                <div className="builder-controls">
                  <input
                    type="number"
                    min={1}
                    max={10}
                    value={setsPerSide}
                    onChange={(e) =>
                      setSetsPerSide(
                        Math.max(1, Math.min(10, Number(e.target.value) || 1)),
                      )
                    }
                    className="reps-input"
                  />
                  <div className="reps-presets">
                    {SET_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`reps-preset ${setsPerSide === n ? "active" : ""}`}
                        onClick={() => setSetsPerSide(n)}
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

              <div className="builder-row">
                <span className="builder-label">Progression</span>
                <div className="builder-controls">
                  <div className="reps-presets">
                    {(Object.keys(MODE_INFO) as SquatMode[]).map((m) => (
                      <button
                        key={m}
                        className={`reps-preset ${mode === m ? "active" : ""}`}
                        onClick={() => setMode(m)}
                      >
                        {MODE_INFO[m].label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="squat-mode-blurb">{MODE_INFO[mode].blurb}</div>
              {mode === "deep" && (
                <div className="squat-warning">
                  ⚠️ This is an advanced progression — balance and hip/ankle
                  mobility matter a lot here. Have something nearby to hold
                  if you need it.
                </div>
              )}

              <div className="builder-total">
                Left {setsPerSide} × {repsPerSet}, then right {setsPerSide} ×{" "}
                {repsPerSet} = <strong>{totalPlannedReps} reps total</strong>
              </div>

              <div className="squat-setup-tip">
                Stand on one leg with the other leg lifted and controlled in
                front of you. Sit back and down on the standing leg, keep
                the knee tracking over your foot, then push back up to
                standing — you'll do all your sets on the left leg first,
                then switch to the right. Camera should be front-facing (or
                slightly angled) with your whole body in frame.
              </div>

              <button className="start-btn full-width" onClick={handleStart}>
                Start Session ▶
              </button>
            </div>
          )}

          {phase === "resting" && (
            <div className="rest-panel">
              <div className="rest-panel-title">
                {activeSide === "left" ? "Left" : "Right"} set {currentSet}{" "}
                complete 🎉
              </div>
              <div className="rest-panel-big-countdown">{restRemaining}</div>
              <div className="rest-panel-caption">seconds of rest left</div>

              {setSummaries[setSummaries.length - 1] && (
                <div className="arm-grid rest-panel-grid">
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

              <button className="stop-btn" onClick={handleSkipRest}>
                Skip rest
              </button>
            </div>
          )}

          {phase === "switch_side" && (
            <div className="rest-panel">
              <div className="rest-panel-title">Left leg complete 🎉</div>
              <div className="squat-setup-tip">
                Great work — now switch and stand on your right leg for the
                same {setsPerSide} × {repsPerSet}.
              </div>
              <button className="start-btn full-width" onClick={handleSwitchSideConfirmed}>
                Start Right Leg ▶
              </button>
            </div>
          )}

          {phase === "active" && (
            <div className="single-arm-wrap">
              <SingleLegSquatStatsPanel data={result} />

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
                  <span className="k">Total reps</span>
                  <span className="v">{totals.reps}</span>
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
                  <span className="k">Total time</span>
                  <span className="v">{totals.time.toFixed(0)}s</span>
                </div>
              </div>

              <div className="results-table">
                <div className="results-row results-head">
                  <span>Side</span>
                  <span>Set</span>
                  <span>Reps</span>
                  <span>Good</span>
                  <span>Flawed</span>
                </div>
                {[...leftSummaries, ...rightSummaries].map((s) => (
                  <div key={`${s.side}-${s.setNumber}`} className="results-row">
                    <span>{s.side === "left" ? "Left" : "Right"}</span>
                    <span>{s.setNumber}</span>
                    <span>{s.reps}</span>
                    <span className="good-text">{s.goodReps}</span>
                    <span className="flawed-text">{s.flawedReps}</span>
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

export default SingleLegSquatPage;
