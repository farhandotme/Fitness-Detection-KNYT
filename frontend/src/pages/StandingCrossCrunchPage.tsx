import { useEffect, useMemo, useState } from "react";
import useStandingCrossCrunchSocket from "../hooks/useStandingCrossCrunchSocket";
import StandingCrossCrunchCamera from "../conponents/StandingCrossCrunchCamera";
import StandingCrossCrunchStatsPanel from "../conponents/StandingCrossCrunchStatsPanel";
import "./StandingCrossCrunchPage.css";

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

const REP_PRESETS = [8, 10, 16, 20];
const SET_PRESETS = [1, 2, 3, 4, 5];
const REST_PRESETS = [15, 20, 30, 45];

type Phase = "setup" | "active" | "resting" | "complete";

interface SetSummary {
  setNumber: number;
  reps: number;
  goodReps: number;
  flawedReps: number;
  alternationBreaks: number;
  elapsedTime: number;
}

function StandingCrossCrunchPage() {
  const [repsPerSet, setRepsPerSet] = useState(10);
  const [totalSets, setTotalSets] = useState(3);
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
  } = useStandingCrossCrunchSocket();

  const skeleton = result.landmarks?.length
    ? [{ points: result.landmarks, connections: POSE_CONNECTIONS }]
    : [];

  const currentReps = result.rep_count ?? 0;
  const progressPct = Math.min(
    100,
    (currentReps / Math.max(1, repsPerSet)) * 100,
  );

  // ---- advance a set once the BACKEND confirms this set's reps are done ----
  // `session_complete` is computed server-side
  // (StandingCrossCrunchAnalyzer._is_complete), from the target_reps the
  // backend itself was given when the socket opened. We never derive this
  // from currentReps/repsPerSet on the client.
  useEffect(() => {
    if (phase !== "active" || !result.session_complete) return;

    stop();

    const summary: SetSummary = {
      setNumber: currentSet,
      reps: currentReps,
      goodReps: result.good_reps ?? 0,
      flawedReps: result.flawed_reps ?? 0,
      alternationBreaks: result.alternation_breaks ?? 0,
      elapsedTime: result.elapsed_time ?? 0,
    };
    setSetSummaries((prev) => [...prev, summary]);

    // exercise_complete is also backend-validated: true only once every
    // set in the plan hit its target. This is the boolean that should
    // trigger persisting "user completed this exercise" to the database.
    if (result.exercise_complete) {
      setPhase("complete");
      return;
    }

    setPhase("resting");
    setRestRemaining(restSeconds);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result.session_complete]);

  // ---- rest countdown ----
  useEffect(() => {
    if (phase !== "resting") return;
    if (restRemaining <= 0) {
      setCurrentSet((s) => s + 1);
      setPhase("active");
      start({
        targetReps: repsPerSet,
        targetSets: totalSets,
        setNumber: currentSet + 1,
      });
      return;
    }
    const id = window.setTimeout(() => setRestRemaining((r) => r - 1), 1000);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, restRemaining]);

  function beginWorkout() {
    setSetSummaries([]);
    setCurrentSet(1);
    setPhase("active");
    start({ targetReps: repsPerSet, targetSets: totalSets, setNumber: 1 });
  }

  function skipRest() {
    setRestRemaining(0);
  }

  function stopWorkout() {
    stop();
    setPhase("setup");
  }

  const totalCompletedReps = useMemo(
    () => setSummaries.reduce((sum, s) => sum + s.reps, 0) + (phase === "active" ? currentReps : 0),
    [setSummaries, phase, currentReps],
  );

  return (
    <div className="ccrunch-page">
      <div className="ccrunch-header">
        <h1>Standing Cross Crunch</h1>
        <p className="ccrunch-subtitle">
          Cardio · Core — alternating standing knee-to-elbow crunch, counted
          left/right from the backend, no hold timer involved.
        </p>
      </div>

      {phase === "setup" && (
        <div className="ccrunch-setup">
          <div className="ccrunch-setup-group">
            <span className="ccrunch-setup-label">Reps per set</span>
            <div className="ccrunch-preset-row">
              {REP_PRESETS.map((n) => (
                <button
                  key={n}
                  className={`ccrunch-preset-btn ${repsPerSet === n ? "selected" : ""}`}
                  onClick={() => setRepsPerSet(n)}
                >
                  {n}
                </button>
              ))}
            </div>
          </div>

          <div className="ccrunch-setup-group">
            <span className="ccrunch-setup-label">Sets</span>
            <div className="ccrunch-preset-row">
              {SET_PRESETS.map((n) => (
                <button
                  key={n}
                  className={`ccrunch-preset-btn ${totalSets === n ? "selected" : ""}`}
                  onClick={() => setTotalSets(n)}
                >
                  {n}
                </button>
              ))}
            </div>
          </div>

          <div className="ccrunch-setup-group">
            <span className="ccrunch-setup-label">Rest between sets</span>
            <div className="ccrunch-preset-row">
              {REST_PRESETS.map((n) => (
                <button
                  key={n}
                  className={`ccrunch-preset-btn ${restSeconds === n ? "selected" : ""}`}
                  onClick={() => setRestSeconds(n)}
                >
                  {n}s
                </button>
              ))}
            </div>
          </div>

          <div className="ccrunch-howto">
            <h3>How it's counted</h3>
            <ul>
              <li>Stand tall, clasp your hands behind your head, elbows out.</li>
              <li>
                Drive one knee up while twisting so the opposite elbow
                crosses toward it, then reset to standing.
              </li>
              <li>
                Start on whichever side you like — every rep after that
                must alternate sides. Repeating the same side in a row
                isn't counted until you switch.
              </li>
              <li>Every rep is verified and counted by the backend, live.</li>
            </ul>
          </div>

          <button className="ccrunch-start-btn" onClick={beginWorkout}>
            Start Workout
          </button>
        </div>
      )}

      {phase === "active" && (
        <div className="ccrunch-active">
          <div className="ccrunch-active-top">
            <span>
              Set {currentSet} / {totalSets}
            </span>
            <span>
              {currentReps} / {repsPerSet} reps
            </span>
          </div>
          <div className="ccrunch-progress-track">
            <div
              className="ccrunch-progress-fill"
              style={{ width: `${progressPct}%` }}
            />
          </div>

          <div className="ccrunch-active-body">
            <StandingCrossCrunchCamera
              active
              sendFrame={sendFrame}
              skeleton={skeleton}
              onError={setCameraError}
            />
            <StandingCrossCrunchStatsPanel data={result} />
          </div>

          {cameraError && <div className="ccrunch-alert bad">{cameraError}</div>}
          {socketError && <div className="ccrunch-alert bad">{socketError}</div>}
          {!connected && !socketError && (
            <div className="ccrunch-alert notice">Connecting to detection server…</div>
          )}

          {lastCompletedRep.feedback && (
            <div
              className={`ccrunch-last-rep ${
                lastCompletedRep.rep_form_quality === "needs_improvement"
                  ? "flawed"
                  : "good"
              }`}
            >
              {lastCompletedRep.feedback}
            </div>
          )}

          <button className="ccrunch-stop-btn" onClick={stopWorkout}>
            End Workout
          </button>
        </div>
      )}

      {phase === "resting" && (
        <div className="ccrunch-resting">
          <h2>Rest</h2>
          <div className="ccrunch-rest-timer">{restRemaining}s</div>
          <p>Next up: Set {currentSet + 1} of {totalSets}</p>
          <button className="ccrunch-skip-btn" onClick={skipRest}>
            Skip rest
          </button>
        </div>
      )}

      {phase === "complete" && (
        <div className="ccrunch-complete">
          <h2>Workout complete 🎉</h2>
          <p>
            {totalCompletedReps} total reps across {setSummaries.length} set
            {setSummaries.length === 1 ? "" : "s"}.
          </p>
          <table className="ccrunch-summary-table">
            <thead>
              <tr>
                <th>Set</th>
                <th>Reps</th>
                <th>Good</th>
                <th>Needs work</th>
                <th>Rejected (same side)</th>
              </tr>
            </thead>
            <tbody>
              {setSummaries.map((s) => (
                <tr key={s.setNumber}>
                  <td>{s.setNumber}</td>
                  <td>{s.reps}</td>
                  <td>{s.goodReps}</td>
                  <td>{s.flawedReps}</td>
                  <td>{s.alternationBreaks}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <button className="ccrunch-start-btn" onClick={() => setPhase("setup")}>
            Back to setup
          </button>
        </div>
      )}
    </div>
  );
}

export default StandingCrossCrunchPage;
