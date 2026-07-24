import { useCallback, useEffect, useRef, useState } from "react";

export interface Landmark {
  x: number;
  y: number;
  z: number;
  visibility?: number;
}

/** Everything the FastAPI `WindmillAnalyzer` sends per frame. */
export interface WindmillData {
  pose_detected: boolean;
  position_ok: boolean;
  position_message: string | null;
  ready: boolean;
  lean_angle: number | null;
  smoothed_lean_angle: number | null;
  stage: "center" | "bent" | string;
  rep_count: number;
  left_reps: number;
  right_reps: number;
  good_reps: number;
  flawed_reps: number;
  target_reps: number | null;
  session_complete: boolean;
  rep_completed: boolean;
  rep_side: "left" | "right" | null;
  rep_duration: number | null;
  rep_classification: string | null;
  rep_form_quality: string | null;
  current_side: "left" | "right" | null;
  framing_ok: boolean;
  framing_message: string | null;
  feedback: string | null;
  low_visibility: boolean;
  elapsed_time: number;
  landmarks: Landmark[];
  /** Which set (of the coach-assigned plan) this connection is for. */
  set_number?: number;
  /** Total sets in the coach-assigned plan. */
  target_sets?: number;
  /**
   * Backend-validated: true only once every set in the plan has hit its
   * target reps. The frontend must treat this as the source of truth —
   * it must not compute this itself.
   */
  exercise_complete?: boolean;
}

const EMPTY_RESULT: WindmillData = {
  pose_detected: false,
  position_ok: false,
  position_message: null,
  ready: false,
  lean_angle: null,
  smoothed_lean_angle: null,
  stage: "center",
  rep_count: 0,
  left_reps: 0,
  right_reps: 0,
  good_reps: 0,
  flawed_reps: 0,
  target_reps: null,
  session_complete: false,
  rep_completed: false,
  rep_side: null,
  rep_duration: null,
  rep_classification: null,
  rep_form_quality: null,
  current_side: null,
  framing_ok: true,
  framing_message: null,
  feedback: null,
  low_visibility: false,
  elapsed_time: 0,
  landmarks: [],
  set_number: undefined,
  target_sets: undefined,
  exercise_complete: false,
};

const WS_BASE =
  (import.meta.env.VITE_WEBSOCKET_FASTAPI_URL as string | undefined) ||
  `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`;

export default function useWindmillSocket() {
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [socketError, setSocketError] = useState<string | null>(null);
  const [result, setResult] = useState<WindmillData>(EMPTY_RESULT);

  const [lastCompletedRep, setLastCompletedRep] = useState({
    rep_side: null as "left" | "right" | null,
    rep_duration: null as number | null,
    rep_classification: null as string | null,
    rep_form_quality: null as string | null,
    feedback: null as string | null,
  });

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

  const start = useCallback(
    (plan?: {
      targetReps?: number;
      targetSets?: number;
      setNumber?: number;
    }) => {
      socketRef.current?.close();

      setResult(EMPTY_RESULT);
      setLastCompletedRep({
        rep_side: null,
        rep_duration: null,
        rep_classification: null,
        rep_form_quality: null,
        feedback: null,
      });
      setSocketError(null);

      const params = new URLSearchParams();
      if (plan?.targetReps != null)
        params.set("target_reps", String(plan.targetReps));
      if (plan?.targetSets != null)
        params.set("target_sets", String(plan.targetSets));
      if (plan?.setNumber != null)
        params.set("set_number", String(plan.setNumber));
      const query = params.toString();

      let ws: WebSocket;
      try {
        ws = new WebSocket(`${WS_BASE}/ws/windmill${query ? `?${query}` : ""}`);
      } catch {
        setSocketError("Couldn't reach the detection server. Is it running?");
        return;
      }

      socketRef.current = ws;

      ws.onopen = () => setConnected(true);

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data) as WindmillData;
        setResult(data);

        if (data.rep_completed) {
          setLastCompletedRep({
            rep_side: data.rep_side,
            rep_duration: data.rep_duration,
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
    },
    [],
  );

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
