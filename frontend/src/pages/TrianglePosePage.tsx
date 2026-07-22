import { useEffect, useMemo, useState } from "react";
import useTrianglePoseSocket from "../hooks/useTrianglePoseSocket";
import TrianglePoseCamera from "../conponents/TrianglePoseCamera";
import TrianglePoseStatsPanel from "../conponents/TrianglePoseStatsPanel";
import "./TrianglePosePage.css";

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
const REST_PRESETS = [15, 20, 30, 45];

type Phase = "setup" | "active" | "resting" | "complete";
type Side = "left" | "right";

interface SideSummary {
  setNumber: number;
  side: Side;
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

function sideForSet(setNumber: number): Side {
  return setNumber % 2 === 1 ? "left" : "right";
}

function TrianglePosePage() {
  const [holdTarget, setHoldTarget] = useState(20);
  const [restSeconds, setRestSeconds] = useState(20);
  const totalSets = 2; // one hold per side — left, then right

  const [phase, setPhase] = useState<Phase>("setup");
  const [currentSet, setCurrentSet] = useState(1);
  const [restRemaining, setRestRemaining] = useState(0);
  const [sideSummaries, setSideSummaries] = useState<SideSummary[]>([]);
  const [cameraError, setCameraError] = useState<string | null>(null);

  const { connected, result, sendFrame, start, stop, socketError } =
    useTrianglePoseSocket();

  const skeleton = result.landmarks?.length
    ? [{ points: result.landmarks, connections: POSE_CONNECTIONS }]
    : [];

  const currentHold = result.hold_seconds ?? 0;
  const progressPct = Math.min(100, (currentHold / Math.max(1, holdTarget)) * 100);
  const currentSide = sideForSet(currentSet);

  // ---- advance a side once the BACKEND confirms this side's hold time is met ----
  useEffect(() => {
    if (phase !== "active" || !result.session_complete) return;

    stop();

    const summary: SideSummary = {
      setNumber: currentSet,
      side: currentSide,
      holdSeconds: result.hold_seconds ?? 0,
      bestStreak: result.best_streak_seconds ?? 0,
      breakCount: result.break_count ?? 0,
      goodSeconds: result.good_seconds ?? 0,
      flawedSeconds: result.flawed_seconds ?? 0,
    };
    setSideSummaries((prev) => [...prev, summary]);

    if (result.exercise_complete) {
      setPhase("complete");
    } else {
      setRestRemaining(restSeconds);
      setPhase("resting");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, result.session_complete, currentSet, restSeconds, result, stop]);

  // ---- persist completion once the backend confirms both sides are done ----
  useEffect(() => {
    if (!result.exercise_complete) return;
    // TODO: wire this up to the real backend endpoint once it exists, e.g.
    //   POST /api/workouts/complete { exercise: "triangle_pose", holdTarget }
    console.log(
      "Exercise completed (backend-validated) — ready to persist to DB.",
    );
  }, [result.exercise_complete]);

  // ---- rest countdown between sides, then auto-start the next one ----
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
        side: sideForSet(nextSet),
      });
      return;
    }

    const timer = window.setTimeout(() => setRestRemaining((r) => r - 1), 1000);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, restRemaining, start, currentSet, holdTarget]);

  function handleStart() {
    setCameraError(null);
    setSideSummaries([]);
    setCurrentSet(1);
    setPhase("active");
    start({
      targetSeconds: holdTarget,
      targetSets: totalSets,
      setNumber: 1,
      side: "left",
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
    setSideSummaries([]);
    setCurrentSet(1);
    setPhase("setup");
  }

  const elapsed = result.elapsed_time ?? 0;

  const totals = useMemo(() => {
    return sideSummaries.reduce(
      (acc, s) => ({
        hold: acc.hold + s.holdSeconds,
        bestStreak: Math.max(acc.bestStreak, s.bestStreak),
        breaks: acc.breaks + s.breakCount,
        good: acc.good + s.goodSeconds,
        flawed: acc.flawed + s.flawedSeconds,
      }),
      { hold: 0, bestStreak: 0, breaks: 0, good: 0, flawed: 0 },
    );
  }, [sideSummaries]);

  return (
    <div className="tri-page">
      <div className="tri-header">
        <div className="tri-header-left">
          <h1 className="tri-title">Triangle Pose Trainer</h1>
        </div>

        <div className="tri-header-right">
          {phase === "active" && (
            <div className="active-controls">
              <span className={`status-dot ${connected ? "live" : ""}`} />
              <span className="active-label">
                {currentSide === "left" ? "Left" : "Right"} side ·{" "}
                {formatSeconds(currentHold)} / {formatSeconds(holdTarget)}
              </span>
              <button className="stop-btn" onClick={handleEndSession}>
                End Session
              </button>
            </div>
          )}

          {phase === "resting" && (
            <div className="active-controls">
              <span className="active-label">
                Resting — next up:{" "}
                {sideForSet(currentSet + 1) === "left" ? "Left" : "Right"} side
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

      {socketError && <div className="tri-error">{socketError}</div>}
      {cameraError && <div className="tri-error">{cameraError}</div>}

      <div className="tri-body">
        <div className="tri-camera-col">
          <TrianglePoseCamera
            active={phase === "active"}
            sendFrame={sendFrame}
            skeleton={skeleton}
            onError={setCameraError}
          />

          {phase === "resting" && (
            <div className="rest-overlay-caption">
              <span className="rest-countdown">{restRemaining}s</span>
              <span>
                until {sideForSet(currentSet + 1) === "left" ? "left" : "right"}{" "}
                side starts
              </span>
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
                  ? `${formatSeconds(currentHold)} / ${formatSeconds(holdTarget)}`
                  : "Side complete — resting"}
              </div>

              <div className="set-dots">
                {[1, 2].map((n) => (
                  <span
                    key={n}
                    className={`set-dot ${
                      n < currentSet || (n === currentSet && phase === "resting")
                        ? "done"
                        : n === currentSet
                          ? "current"
                          : ""
                    }`}
                    title={sideForSet(n)}
                  />
                ))}
              </div>
            </>
          )}
        </div>

        <div className="tri-stats-col">
          {phase === "setup" && (
            <div className="session-builder">
              <div className="builder-row">
                <span className="builder-label">Hold time per side</span>
                <div className="builder-controls">
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
                    className="reps-input"
                  />
                  <div className="reps-presets">
                    {HOLD_PRESETS.map((n) => (
                      <button
                        key={n}
                        className={`reps-preset ${holdTarget === n ? "active" : ""}`}
                        onClick={() => setHoldTarget(n)}
                      >
                        {n}s
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="builder-row">
                <span className="builder-label">Rest between sides</span>
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
                Left side + Right side ={" "}
                <strong>{formatSeconds(holdTarget * 2)} total hold</strong>
              </div>

              <div className="tri-setup-tip">
                Stand facing the camera with your feet wide apart. Turn your
                front foot out, keep both legs straight, and hinge sideways
                from your hip over the front leg — reach your lower hand
                toward your shin and your upper arm straight up, stacked in
                one line. The timer only runs while a real Triangle Pose is
                confirmed, and it always starts with your left leg forward,
                then switches to your right — reps on the wrong side won't
                count toward that side's timer.
              </div>

              <button className="start-btn full-width" onClick={handleStart}>
                Start Session ▶
              </button>
            </div>
          )}

          {phase === "resting" && (
            <div className="rest-panel">
              <div className="rest-panel-title">
                {currentSide === "left" ? "Left" : "Right"} side complete 🎉
              </div>
              <div className="rest-panel-big-countdown">{restRemaining}</div>
              <div className="rest-panel-caption">seconds of rest left</div>

              {sideSummaries[sideSummaries.length - 1] && (
                <div className="arm-grid rest-panel-grid">
                  <div className="arm-grid-item">
                    <span className="k">Held</span>
                    <span className="v">
                      {formatSeconds(
                        sideSummaries[sideSummaries.length - 1].holdSeconds,
                      )}
                    </span>
                  </div>
                  <div className="arm-grid-item">
                    <span className="k">Best streak</span>
                    <span className="v">
                      {formatSeconds(
                        sideSummaries[sideSummaries.length - 1].bestStreak,
                      )}
                    </span>
                  </div>
                  <div className="arm-grid-item">
                    <span className="k">Breaks</span>
                    <span className="v">
                      {sideSummaries[sideSummaries.length - 1].breakCount}
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
              <TrianglePoseStatsPanel data={result} />

              {result.feedback && (
                <div
                  className={`feedback-box ${
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
            <div className="results-panel">
              <div className="results-totals">
                <div className="session-summary-item">
                  <span className="k">Sides</span>
                  <span className="v">{sideSummaries.length}</span>
                </div>
                <div className="session-summary-item">
                  <span className="k">Total held</span>
                  <span className="v">{formatSeconds(totals.hold)}</span>
                </div>
                <div className="session-summary-item">
                  <span className="k">Best streak</span>
                  <span className="v">{formatSeconds(totals.bestStreak)}</span>
                </div>
                <div className="session-summary-item">
                  <span className="k">Total breaks</span>
                  <span className="v">{totals.breaks}</span>
                </div>
                <div className="session-summary-item good">
                  <span className="k">Good</span>
                  <span className="v">{formatSeconds(totals.good)}</span>
                </div>
                <div className="session-summary-item flawed">
                  <span className="k">Flawed</span>
                  <span className="v">{formatSeconds(totals.flawed)}</span>
                </div>
              </div>

              <div className="results-table">
                <div className="results-row results-head">
                  <span>Side</span>
                  <span>Held</span>
                  <span>Best</span>
                  <span>Breaks</span>
                  <span>Good</span>
                </div>
                {sideSummaries.map((s) => (
                  <div key={s.setNumber} className="results-row">
                    <span>{s.side}</span>
                    <span>{formatSeconds(s.holdSeconds)}</span>
                    <span>{formatSeconds(s.bestStreak)}</span>
                    <span>{s.breakCount}</span>
                    <span className="good-text">{formatSeconds(s.goodSeconds)}</span>
                  </div>
                ))}
                {sideSummaries.length === 0 && (
                  <div className="results-row">
                    <span className="empty-hint">
                      Session ended before any side finished.
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

export default TrianglePosePage;
