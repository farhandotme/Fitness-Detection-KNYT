import { useState } from "react";

import useWebSocket from "../hooks/useWebSocket";
import CameraSelector from "../conponents/CameraSelector";
import VideoPreview from "../conponents/VideoPreview";
import FingerBars from "../conponents/FingerBars";

// standard 21-point MediaPipe hand landmark connections
// const HAND_CONNECTIONS: [number, number][] = [
//   [0, 1], [1, 2], [2, 3], [3, 4],
//   [0, 5], [5, 6], [6, 7], [7, 8],
//   [5, 9], [9, 10], [10, 11], [11, 12],
//   [9, 13], [13, 14], [14, 15], [15, 16],
//   [13, 17], [17, 18], [18, 19], [19, 20],
//   [0, 17],
// ];

function FingerPage() {
  const [cameraId, setCameraId] = useState("");

  const { connected, result, sendFrame } = useWebSocket();

  // const skeleton = result.hands.map((hand: any) => ({
  //   points: hand.landmarks,
  //   connections: HAND_CONNECTIONS,
  // }));

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
            // skeleton={skeleton}
          />
        </div>

        <div className="stats-col">
          <div className="stat-block">
            <span className="stat-label">total fingers</span>
            <span className="stat-number">{result.total_fingers}</span>
          </div>

          <div className="hand-list">
            {result.hands.map((hand: any, i: number) => (
              <FingerBars
                key={i}
                handLabel={hand.hand}
                count={hand.finger_count}
                fingers={hand.fingers}
              />
            ))}

            {result.hands.length === 0 && (
              <p className="empty-hint">show a hand to the camera</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default FingerPage;
