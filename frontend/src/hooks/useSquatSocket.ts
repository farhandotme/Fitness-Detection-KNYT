import { useCallback, useEffect, useRef, useState } from "react";

export interface Landmark {
  x: number;
  y: number;
  z: number;
  visibility?: number;
}

/** Everything the FastAPI `SquatAnalyzer` sends per frame. */
export interface SquatData {
  pose_detected: boolean;
  angle: number | null;
  smoothed_angle: number | null;
  left_knee_angle: number | null;
  right_knee_angle: number | null;
  angle_velocity: number | null;
  stage: string;
  rep_count: number;
  good_reps: number;
  flawed_reps: number;
  target_reps: number | null;
  session_complete: boolean;
  rep_completed: boolean;
  rep_duration: number | null;
  rep_avg_speed: number | null;
  rep_classification: string | null;
  rep_form_quality: string | null;
  calibrated: boolean;
  posture_ok: boolean;
  posture_issues: string[];
  posture_messages: string[];
  framing_ok: boolean;
  framing_message: string | null;
  feedback: string | null;
  low_visibility: boolean;
  elapsed_time: number;
  landmarks: Landmark[];
}

const EMPTY_RESULT: SquatData = {
  pose_detected: false,
  angle: null,
  smoothed_angle: null,
  left_knee_angle: null,
  right_knee_angle: null,
  angle_velocity: null,
  stage: "down",
  rep_count: 0,
  good_reps: 0,
  flawed_reps: 0,
  target_reps: null,
  session_complete: false,
  rep_completed: false,
  rep_duration: null,
  rep_avg_speed: null,
  rep_classification: null,
  rep_form_quality: null,
  calibrated: false,
  posture_ok: true,
  posture_issues: [],
  posture_messages: [],
  framing_ok: true,
  framing_message: null,
  feedback: null,
  low_visibility: false,
  elapsed_time: 0,
  landmarks: [],
};

const WS_BASE =
  (import.meta.env.VITE_WEBSOCKET_FASTAPI_URL as string | undefined) ||
  `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`;

export default function useSquatSocket() {
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [socketError, setSocketError] = useState<string | null>(null);
  const [result, setResult] = useState<SquatData>(EMPTY_RESULT);

  const [lastCompletedRep, setLastCompletedRep] = useState({
    rep_duration: null as number | null,
    rep_avg_speed: null as number | null,
    rep_classification: null as string | null,
    rep_form_quality: null as string | null,
    feedback: null as string | null,
  });

  // Always close any open socket on unmount.
  useEffect(() => {
    return () => {
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, []);

  const stop = useCallback(() => {
    socketRef.current?.close();
    socketRef.current = null;
  }, []);

  const start = useCallback(() => {
    socketRef.current?.close();

    setResult(EMPTY_RESULT);
    setLastCompletedRep({
      rep_duration: null,
      rep_avg_speed: null,
      rep_classification: null,
      rep_form_quality: null,
      feedback: null,
    });
    setSocketError(null);

    let ws: WebSocket;
    try {
      ws = new WebSocket(`${WS_BASE}/ws/squat`);
    } catch {
      setSocketError("Couldn't reach the detection server. Is it running?");
      return;
    }

    socketRef.current = ws;

    ws.onopen = () => setConnected(true);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data) as SquatData;
      setResult(data);

      if (data.rep_completed) {
        setLastCompletedRep({
          rep_duration: data.rep_duration,
          rep_avg_speed: data.rep_avg_speed,
          rep_classification: data.rep_classification,
          rep_form_quality: data.rep_form_quality,
          feedback: data.feedback,
        });
      }
    };

    ws.onclose = () => {
      setConnected(false);
      socketRef.current = null;
    };

    ws.onerror = () => {
      setSocketError("Connection error — check that the backend is running.");
    };
  }, []);

  const sendFrame = useCallback((image: string) => {
    const ws = socketRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(image);
  }, []);

  return {
    connected,
    result,
    lastCompletedRep,
    sendFrame,
    start,
    stop,
    socketError,
  };
}