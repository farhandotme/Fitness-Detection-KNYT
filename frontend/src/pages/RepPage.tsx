import { useState } from "react";

import useRepWebSocket from "../hooks/useRepWebSocket";
import CameraSelector from "../conponents/CameraSelector";
import VideoPreview from "../conponents/VideoPreview";
import AngleGauge from "../conponents/AngleGauge";

const EXERCISES = ["bicep_curl", "squat", "pushup"] as const;

// mirrors backend EXERCISES config — keep in sync if thresholds change server-side
const THRESHOLDS: Record<string, { up: number; down: number }> = {
  bicep_curl: { up: 50, down: 160 },
  squat: { up: 90, down: 160 },
  pushup: { up: 70, down: 160 },
};

// subset of BlazePose 33-point connections relevant to the tracked joints
const POSE_CONNECTIONS: [number, number][] = [
  [11, 13], [13, 15],
  [12, 14], [14, 16],
  [11, 12],
  [23, 24],
  [11, 23], [12, 24],
  [23, 25], [25, 27],
  [24, 26], [26, 28],
];

function RepPage() {
  const [cameraId, setCameraId] = useState("");
  const [exercise, setExercise] = useState<string>(EXERCISES[0]);

  const { connected, result, sendFrame } = useRepWebSocket(exercise);
  const range = THRESHOLDS[exercise];

  const skeleton = result.landmarks?.length
    ? [{ points: result.landmarks, connections: POSE_CONNECTIONS }]
    : [];

  return (
    <div className="page">
      <div className="page-grid">
        <div className="camera-col">
          <div className="camera-toolbar">
            <CameraSelector onCameraChange={setCameraId} />
            <span className={`status-dot ${connected ? "live" : ""}`} />
          </div>

          <VideoPreview
            deviceId={cameraId}
            sendFrame={sendFrame}
            skeleton={skeleton}
          />

          <div className="exercise-picker">
            {EXERCISES.map((ex) => (
              <button
                key={ex}
                className={`pill ${exercise === ex ? "active" : ""}`}
                onClick={() => setExercise(ex)}
              >
                {ex.replace("_", " ")}
              </button>
            ))}
          </div>
        </div>

        <div className="stats-col">
          <div className="stat-block">
            <span className="stat-label">reps</span>
            <span className="stat-number">{result.rep_count}</span>
          </div>

          <AngleGauge
            angle={result.angle}
            upThreshold={range.up}
            downThreshold={range.down}
            stage={result.stage}
          />

          <div className="meta-row">
            <span>pose detected</span>
            <span>{result.pose_detected ? "yes" : "no"}</span>
          </div>
          <div className="meta-row">
            <span>angle</span>
            <span>{result.angle != null ? `${result.angle.toFixed(1)}°` : "—"}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default RepPage;
