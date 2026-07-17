import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import useMuayThaiJabSocket from "../hooks/useMuayThaiJabSocket";
import MuayThaiJabCamera from "../conponents/MuayThaiJabCamera";
import MuayThaiJabStatsPanel from "../conponents/MuayThaiJabStatsPanel";
import "./BicepPage.css";
import "./MuayThaiJabPage.css";

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

// A jab drill is trained in timed rounds, not a fixed rep target — this
// matches how the backend actually runs today too: `/ws/jab` always opens
// with target_reps=None, so `session_complete` never resolves server-side.
// The round clock below is the thing that actually ends a round.
const ROUND_PRESETS = [
  { label: "1:00", seconds: 60 },
  { label: "2:00", seconds: 120 },
  { label: "3:00", seconds: 180 },
  { label: "5:00", seconds: 300 },
];
const ROUNDS_COUNT_PRESETS = [1, 3, 5, 8, 12];
const REST_PRESETS = [30, 45, 60, 90];

const LOW_TIME_WARNING_S = 10;

type Phase = "setup" | "round" | "resting" | "complete";

interface RoundSummary {
  roundNumber: number;
  jabs: number;
  goodReps: number;
  flawedReps: number;
  partialReps: number;
  rejectedNoGuard: number;
  elapsedTime: number;
}

function formatClock(totalSeconds: number) {
  const s = Math.max(0, Math.round(totalSeconds));
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${rem.toString().padStart(2, "0")}`;
}

function MuayThaiJabPage() {
  const navigate = useNavigate();

  const [roundSeconds, setRoundSeconds] = useState(120);
  const [totalRounds, setTotalRounds] = useState(3);
  const [restSeconds, setRestSeconds] = useState(60);

  const [phase, setPhase] = useState<Phase>("setup");
  const [currentRound, setCurrentRound] = useState(1);
  const [roundRemaining, setRoundRemaining] = useState(0);
  const [restRemaining, setRestRemaining] = useState(0);
  const [roundSummaries, setRoundSummaries] = useState<RoundSummary[]>([]);
  const [cameraError, setCameraError] = useState<string | null>(null);

  const { connected, result, lastCompletedRep, sendFrame, start, stop, socketError } =
    useMuayThaiJabSocket();

  const skeleton = result.landmarks?.length
    ? [{ points: result.landmarks, connections: POSE_CONNECTIONS }]
    : [];

  function finishRound() {
    stop();
    const summary: RoundSummary = {
      roundNumber: currentRound,
      jabs: result.rep_count ?? 0,
      goodReps: result.good_reps ?? 0,
      flawedReps: result.flawed_reps ?? 0,
      partialReps: result.partial_rep_count ?? 0,
      rejectedNoGuard: result.not_counted_no_guard ?? 0,
      elapsedTime: result.elapsed_time ?? 0,
    };
    setRoundSummaries((prev) => [...prev, summary]);

    if (currentRound >= totalRounds) {
      setPhase("complete");
    } else {
      setRestRemaining(restSeconds);
      setPhase("resting");
    }
  }

  // ---- round countdown: this — not any backend signal — ends a round ----
  useEffect(() => {
    if (phase !== "round") return;

    if (roundRemaining <= 0) {
      finishRound();
      return;
    }

    const timer = window.setTimeout(() => setRoundRemaining((r) => r - 1), 1000);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, roundRemaining]);

  // ---- rest countdown between rounds, then auto-start the next one ----
  useEffect(() => {
    if (phase !== "resting") return;

    if (restRemaining <= 0) {
      const nextRound = currentRound + 1;
      setCurrentRound(nextRound);
      setRoundRemaining(roundSeconds);
      setPhase("round");
      start();
      return;
    }

    const timer = window.setTimeout(() => setRestRemaining((r) => r - 1), 1000);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, restRemaining, start, currentRound, roundSeconds]);

  function handleStart() {
    setCameraError(null);
    setRoundSummaries([]);
    setCurrentRound(1);
    setRoundRemaining(roundSeconds);
    setPhase("round");
    start();
  }

  function handleSkipRest() {
    setRestRemaining(0);
  }

  function handleEndRoundEarly() {
    finishRound();
  }

  function handleEndSession() {
    stop();
    setPhase("complete");
  }

  function handleReset() {
    stop();
    setCameraError(null);
    setRoundSummaries([]);
    setCurrentRound(1);
    setPhase("setup");
  }

  const currentJabs = result.rep_count ?? 0;
  const roundElapsedPct =
    roundSeconds > 0
      ? Math.min(100, ((roundSeconds - roundRemaining) / roundSeconds) * 100)
      : 0;
  const timeCritical = phase === "round" && roundRemaining <= LOW_TIME_WARNING_S;

  const totals = useMemo(() => {
    return roundSummaries.reduce(
      (acc, r) => ({
        jabs: acc.jabs + r.jabs,
        good: acc.good + r.goodReps,
        flawed: acc.flawed + r.flawedReps,
        partial: acc.partial + r.partialReps,
        rejected: acc.rejected + r.rejectedNoGuard,
        time: acc.time + r.elapsedTime,
      }),
      { jabs: 0, good: 0, flawed: 0, partial: 0, rejected: 0, time: 0 },
    );
  }, [roundSummaries]);

  const latestRoundSummary = roundSummaries[roundSummaries.length - 1];

  return (
    <div className="bicep-page muaythaijab-page">
      <div className="bicep-header">
        <div className="bicep-header-left">
          <button
            className="muaythaijab-back-btn"
            onClick={() => navigate("/exercises")}
          >
            ← Library
          </button>
          <h1 className="bicep-title">Muay Thai Jab Trainer</h1>
        </div>

        <div className="bicep-header-right">
          {phase === "round" && (
            <div className="active-controls">
              <span className={`status-dot ${connected ? "live" : ""}`} />
              <span className="active-label">
                Round {currentRound}/{totalRounds} ·{" "}
                <span className={timeCritical ? "muaythaijab-time-critical" : ""}>
                  {formatClock(roundRemaining)}
                </span>
              </span>
              <button className="stop-btn" onClick={handleEndRoundEarly}>
                End Round
              </button>
            </div>
          )}

          {phase === "resting" && (
            <div className="active-controls">
              <span className="active-label">
                Resting — next up: Round {currentRound + 1}/{totalRounds}
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
          <MuayThaiJabCamera
            active={phase === "round"}
            sendFrame={sendFrame}
            skeleton={skeleton}
            onError={setCameraError}
          />

          {phase === "resting" && (
            <div className="rest-overlay-caption">
              <span className="rest-countdown">{restRemaining}s</span>
              <span>until Round {currentRound + 1} starts</span>
            </div>
          )}

          {phase === "round" && (
            <>
              <div
                className={`progress-track ${timeCritical ? "muaythaijab-progress-critical" : ""}`}
              >
                <div
                  className="progress-fill"
                  style={{ width: `${roundElapsedPct}%` }}
                />
              </div>
              <div className="progress-caption">
                {formatClock(roundRemaining)} left in round {currentRound} ·{" "}
                {currentJabs} jab{currentJabs === 1 ? "" : "s"} thrown
              </div>

              <div className="set-dots">
                {Array.from({ length: totalRounds }, (_, i) => i + 1).map((n) => (
                  <span
                    key={n}
                    className={`set-dot ${
                      n < currentRound ? "done" : n === currentRound ? "current" : ""
                    }`}
                  />
                ))}
              </div>

              <div className="session-summary">
                <div className="session-summary-item good">
                  <span className="k">Good</span>
                  <span className="v">{result.good_reps ?? 0}</span>
                </div>
                <div className="session-summary-item flawed">
                  <span className="k">Flawed</span>
                  <span className="v">{result.flawed_reps ?? 0}</span>
                </div>
                <div className="session-summary-item">
                  <span className="k">Rejected</span>
                  <span className="v">{result.not_counted_no_guard ?? 0}</span>
                </div>
              </div>
            </>
          )}
        </div>

        <div className="bicep-stats-col">
          {phase === "setup" && (
            <div className="session-builder">
              <div className="builder-row">
                <span className="builder-label">Round length</span>
                <div className="builder-controls">
                  <div className="reps-presets">
                    {ROUND_PRESETS.map((p) => (
                      <button
                        key={p.seconds}
                        className={`reps-preset ${roundSeconds === p.seconds ? "active" : ""}`}
                        onClick={() => setRoundSeconds(p.seconds)}
                      >
                        {p.label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="builder-row">
                <span className="builder-label">Number of rounds</span>
                <div className="builder-controls">
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={totalRounds}
                    onChange={(e) =>
                      setTotalRounds(
                        Math.max(1, Math.min(20, Number(e.target.value) || 1)),
                      )
                    }
                    className="reps-input"
                  />
                  <div className="reps-presets">
                    {ROUNDS_COUNT_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`reps-preset ${totalRounds === n ? "active" : ""}`}
                        onClick={() => setTotalRounds(n)}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="builder-row">
                <span className="builder-label">Rest between rounds</span>
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
                {totalRounds} × {formatClock(roundSeconds)} ={" "}
                <strong>{formatClock(totalRounds * roundSeconds)} of work</strong>
              </div>

              <div className="muaythaijab-setup-tip">
                Stand in your guard — fists up, protecting your face — turned
                slightly (not squared on) toward the camera, with room out in
                front to fully extend a punch. Hold still for a second at the
                start of each round to calibrate. A jab only counts if it
                genuinely launches from guard and snaps straight back to it —
                reaching from anywhere else won't count, no matter how far
                your arm extends.
              </div>

              <button className="start-btn full-width" onClick={handleStart}>
                Start Round 1 ▶
              </button>
            </div>
          )}

          {phase === "resting" && (
            <div className="rest-panel">
              <div className="rest-panel-title">
                Round {currentRound} complete 🥊
              </div>
              <div className="rest-panel-big-countdown">{restRemaining}</div>
              <div className="rest-panel-caption">seconds of rest left</div>

              {latestRoundSummary && (
                <div className="arm-grid rest-panel-grid">
                  <div className="arm-grid-item">
                    <span className="k">Jabs</span>
                    <span className="v">{latestRoundSummary.jabs}</span>
                  </div>
                  <div className="arm-grid-item">
                    <span className="k">Good</span>
                    <span className="v">{latestRoundSummary.goodReps}</span>
                  </div>
                  <div className="arm-grid-item">
                    <span className="k">Flawed</span>
                    <span className="v">{latestRoundSummary.flawedReps}</span>
                  </div>
                  <div className="arm-grid-item">
                    <span className="k">Rejected</span>
                    <span className="v">{latestRoundSummary.rejectedNoGuard}</span>
                  </div>
                </div>
              )}

              <button className="stop-btn" onClick={handleSkipRest}>
                Skip rest
              </button>
            </div>
          )}

          {phase === "round" && (
            <div className="single-arm-wrap">
              <MuayThaiJabStatsPanel data={result} />

              {(lastCompletedRep.feedback || result.feedback) && (
                <div
                  className={`feedback-box ${lastCompletedRep.rep_classification ?? lastCompletedRep.rep_form_quality ?? ""}`}
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
                  <span className="k">Rounds</span>
                  <span className="v">{roundSummaries.length}</span>
                </div>
                <div className="session-summary-item">
                  <span className="k">Total jabs</span>
                  <span className="v">{totals.jabs}</span>
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
                  <span className="k">Half jabs</span>
                  <span className="v">{totals.partial}</span>
                </div>
                <div className="session-summary-item">
                  <span className="k">Rejected</span>
                  <span className="v">{totals.rejected}</span>
                </div>
              </div>

              <div className="results-table">
                <div className="results-row results-head">
                  <span>Round</span>
                  <span>Jabs</span>
                  <span>Good</span>
                  <span>Flawed</span>
                  <span>Rejected</span>
                </div>
                {roundSummaries.map((r) => (
                  <div key={r.roundNumber} className="results-row">
                    <span>{r.roundNumber}</span>
                    <span>{r.jabs}</span>
                    <span className="good-text">{r.goodReps}</span>
                    <span className="flawed-text">{r.flawedReps}</span>
                    <span>{r.rejectedNoGuard}</span>
                  </div>
                ))}
                {roundSummaries.length === 0 && (
                  <div className="results-row">
                    <span className="empty-hint">
                      Session ended before any round finished.
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

export default MuayThaiJabPage;
