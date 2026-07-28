import { useCallback, useEffect, useRef, useState } from "react";

export interface Landmark {
  x: number;
  y: number;
  z: number;
  visibility?: number;
}

/** Everything the FastAPI `BicycleCrunchAnalyzer` sends per frame. */
export interface BicycleCrunchData {
  pose_detected: boolean;
  base_ok: boolean;
  base_message: string | null;
  ready: boolean;
  framing_ok: boolean;
  framing_message: string | null;
  crunch_signal: number | null;
  raw_crunch_signal: number | null;
  signal_envelope: number | null;
  phase: "center" | "left" | "right";
  left_count: number;
  right_count: number;
  rep_count: number;
  target_reps: number | null;
  session_complete: boolean;
  rep_completed: boolean;
  side_completed: boolean;
  side_completed_which: "left" | "right" | null;
  legs_alternating: boolean;
  legs_visible: boolean;
  leg_message: string | null;
  low_visibility: boolean;
  feedback: string | null;
  elapsed_time: number;
  landmarks: Landmark[];
  /** Present only if the backend hit an exception processing this frame — see route error handling. */
  error?: string;
  set_number?: number;
  target_sets?: number;
  /**
   * Backend-validated: true only once every set in the plan has hit its
   * target reps. Treat this as the source of truth for "the user
   * completed this exercise" — do not compute it on the client.
   */
  exercise_complete?: boolean;
}

const EMPTY_RESULT: BicycleCrunchData = {
  pose_detected: false,
  base_ok: false,
  base_message: null,
  ready: false,
  framing_ok: true,
  framing_message: null,
  crunch_signal: null,
  raw_crunch_signal: null,
  signal_envelope: null,
  phase: "center",
  left_count: 0,
  right_count: 0,
  rep_count: 0,
  target_reps: null,
  session_complete: false,
  rep_completed: false,
  side_completed: false,
  side_completed_which: null,
  legs_alternating: true,
  legs_visible: false,
  leg_message: null,
  low_visibility: false,
  feedback: null,
  elapsed_time: 0,
  landmarks: [],
  set_number: undefined,
  target_sets: undefined,
  exercise_complete: false,
};

const WS_BASE =
  (import.meta.env.VITE_WEBSOCKET_FASTAPI_URL as string | undefined) ||
  `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`;

export default function useBicycleCrunchSocket() {
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [socketError, setSocketError] = useState<string | null>(null);
  const [result, setResult] = useState<BicycleCrunchData>(EMPTY_RESULT);

  const [lastEvent, setLastEvent] = useState({
    side: null as "left" | "right" | null,
    wasFullRep: false,
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
      setLastEvent({ side: null, wasFullRep: false, feedback: null });
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
        ws = new WebSocket(
          `${WS_BASE}/ws/bicycle_crunch${query ? `?${query}` : ""}`,
        );
      } catch {
        setSocketError("Couldn't reach the detection server. Is it running?");
        return;
      }

      socketRef.current = ws;

      ws.onopen = () => setConnected(true);

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data) as BicycleCrunchData;
        setResult(data);

        if (data.side_completed) {
          setLastEvent({
            side: data.side_completed_which,
            wasFullRep: data.rep_completed,
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
    lastEvent,
    sendFrame,
    start,
    stop,
    socketError,
  };
}
