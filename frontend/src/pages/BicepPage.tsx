import { useState } from "react";
import useRepWebSocket from "../hooks/usebicepCurlSocket";
import CameraSelector from "../conponents/CameraSelector";
import VideoPreview from "../conponents/VideoPreview";
import AngleGauge from "../conponents/AngleGauge";

const SELECT_ARM = ["left", "right", "both"] as const;
type ArmMode = (typeof SELECT_ARM)[number];

const MODE_LABELS: Record<ArmMode, string> = {
  left: "LEFT ARM",
  right: "RIGHT ARM",
  both: "BOTH ARM",
};

const THRESHOLDS: Record<string, { up: number; down: number }> = {
  left: { up: 50, down: 160 },
  right: { up: 50, down: 160 },
  both: { up: 50, down: 160 },
};

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

function BicepPage() {
  const [cameraId, setCameraId] = useState("");
  const [exercise, setExercise] = useState<ArmMode>("left");

  const { connected, result, lastCompletedRep, sendFrame } =
    useRepWebSocket(exercise);

  const range = THRESHOLDS[exercise] ?? { up: 50, down: 160 };

  const skeleton = result.landmarks?.length
    ? [{ points: result.landmarks, connections: POSE_CONNECTIONS }]
    : [];

  const quality =
    lastCompletedRep.rep_classification ?? result.rep_classification;

  const duration = lastCompletedRep.rep_duration ?? result.rep_duration;
  const speed = lastCompletedRep.rep_avg_speed ?? result.rep_avg_speed;
  const feedback = lastCompletedRep.feedback ?? result.feedback;

  const stageText = (result.stage ?? "down").toUpperCase();

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
            {SELECT_ARM.map((ex) => (
              <button
                key={ex}
                className={`pill ${exercise === ex ? "active" : ""}`}
                onClick={() => setExercise(ex)}
              >
                {MODE_LABELS[ex]}
              </button>
            ))}
          </div>
        </div>

        <div className="stats-col">
          <div className="stat-block">
            <span className="stat-label">Reps</span>
            <span className="stat-number">{result.rep_count ?? 0}</span>
          </div>

          <AngleGauge
            angle={result.smoothed_angle ?? result.angle}
            upThreshold={range.up}
            downThreshold={range.down}
            stage={result.stage ?? "down"}
          />

          <div className="meta-row">
            <span>Pose</span>
            <span>
              {result.pose_detected
                ? result.low_visibility
                  ? "⚠️ Unstable"
                  : "✅ Yes"
                : "❌ No"}
            </span>
          </div>

          <div className="meta-row">
            <span>Stage</span>
            <span>{stageText}</span>
          </div>

          <div className="meta-row">
            <span>Smoothed Angle</span>
            <span>
              {result.smoothed_angle != null
                ? `${result.smoothed_angle.toFixed(1)}°`
                : "—"}
            </span>
          </div>

          <div className="meta-row">
            <span>Velocity</span>
            <span>
              {result.angle_velocity != null
                ? `${result.angle_velocity.toFixed(1)}°/s`
                : "—"}
            </span>
          </div>

          <div className="section-label">Tempo</div>

          <div className="meta-row">
            <span>Last Rep Duration</span>
            <span>{duration != null ? `${duration.toFixed(2)} s` : "—"}</span>
          </div>

          <div className="meta-row">
            <span>Last Rep Speed</span>
            <span>{speed != null ? `${speed.toFixed(1)}°/s` : "—"}</span>
          </div>

          <div className="meta-row">
            <span>Quality</span>
            <span className={`quality-badge ${quality ?? ""}`}>
              {quality ? quality.replace("_", " ") : "—"}
            </span>
          </div>

          {feedback && (
            <div className={`feedback-box ${quality ?? ""}`}>
              <strong>Coach Feedback</strong>
              <p>{feedback}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default BicepPage;
