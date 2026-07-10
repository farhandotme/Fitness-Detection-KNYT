import { useCallback, useEffect, useRef, useState } from "react";

export type ArmMode = "left" | "right" | "both";

export interface Landmark {
  x: number;
  y: number;
  z: number;
  visibility?: number;
}

/** Everything the FastAPI `ArmCurlAnalyzer` sends for a single arm. */
export interface ArmData {
  side: string;
  pose_detected: boolean;
  angle: number | null;
  smoothed_angle: number | null;
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
  feedback: string | null;
  low_visibility: boolean;
  elapsed_time?: number;
}

/**
 * The websocket message. Single-arm sessions send `ArmData` flattened at the
 * top level; the "both arms" session sends a combined summary plus nested
 * `left_arm` / `right_arm` objects (each shaped like `ArmData`).
 */
export interface RepResult extends Partial<ArmData> {
  pose_detected: boolean;
  stage: string;
  rep_count: number;
  good_reps: number;
  flawed_reps: number;
  target_reps: number | null;
  session_complete: boolean;
  rep_completed: boolean;
  feedback: string | null;
  landmarks: Landmark[];
  left_arm?: ArmData;
  right_arm?: ArmData;
  sync_ok?: boolean;
  elapsed_time?: number;
}

const EMPTY_RESULT: RepResult = {
  pose_detected: false,
  angle: null,
  smoothed_angle: null,
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
  feedback: null,
  low_visibility: false,
  landmarks: [],
};

const WS_BASE =
  (import.meta.env.VITE_WEBSOCKET_FASTAPI_URL as string | undefined) ||
  "ws://localhost:8000";

export default function useRepWebSocket() {
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [socketError, setSocketError] = useState<string | null>(null);
  const [result, setResult] = useState<RepResult>(EMPTY_RESULT);

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

  const start = useCallback((mode: ArmMode) => {
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
      ws = new WebSocket(`${WS_BASE}/ws/bicep_curl_${mode}_arm`);
    } catch {
      setSocketError("Couldn't reach the detection server. Is it running?");
      return;
    }

    socketRef.current = ws;

    ws.onopen = () => setConnected(true);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data) as RepResult;
      setResult(data);

      const primary = mode === "both" ? undefined : (data as ArmData);
      const flavors = mode === "both" ? [data.left_arm, data.right_arm] : [primary];

      if (data.rep_completed) {
        const completed = flavors.find((a) => a?.rep_completed) ?? primary;
        setLastCompletedRep({
          rep_duration: completed?.rep_duration ?? null,
          rep_avg_speed: completed?.rep_avg_speed ?? null,
          rep_classification: completed?.rep_classification ?? null,
          rep_form_quality: completed?.rep_form_quality ?? null,
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

  return { connected, result, lastCompletedRep, sendFrame, start, stop, socketError };
}
