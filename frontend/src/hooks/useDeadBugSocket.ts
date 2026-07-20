import { useCallback, useEffect, useRef, useState } from "react";

export interface Landmark {
  x: number;
  y: number;
  z: number;
  visibility?: number;
}

/** Everything the FastAPI `DeadBugAnalyzer` sends per frame. */
export interface DeadBugData {
  pose_detected: boolean;
  ready: boolean;
  stance_ok: boolean;
  stance_message: string | null;
  framing_ok: boolean;
  framing_message: string | null;
  rep_count: number;
  right_arm_left_leg_count: number;
  left_arm_right_leg_count: number;
  target_reps: number | null;
  session_complete: boolean;
  rep_completed: boolean;
  rep_diagonal: "right_arm_left_leg" | "left_arm_right_leg" | null;
  invalid_attempt: boolean;
  invalid_reason: "tempo" | "cross_limb" | "hip_drift" | null;
  feedback: string | null;
  low_visibility: boolean;
  elapsed_time: number;
  landmarks: Landmark[];
  set_number?: number;
  target_sets?: number;
  /**
   * Backend-validated: true only once every set in the plan hit its
   * target reps. The frontend must treat this as the source of truth for
   * "the user completed this exercise" — never compute it client-side.
   */
  exercise_complete?: boolean;
}

const EMPTY_RESULT: DeadBugData = {
  pose_detected: false,
  ready: false,
  stance_ok: false,
  stance_message: null,
  framing_ok: true,
  framing_message: null,
  rep_count: 0,
  right_arm_left_leg_count: 0,
  left_arm_right_leg_count: 0,
  target_reps: null,
  session_complete: false,
  rep_completed: false,
  rep_diagonal: null,
  invalid_attempt: false,
  invalid_reason: null,
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

export default function useDeadBugSocket() {
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [socketError, setSocketError] = useState<string | null>(null);
  const [result, setResult] = useState<DeadBugData>(EMPTY_RESULT);

  const [lastEvent, setLastEvent] = useState({
    kind: null as "rep" | "invalid" | null,
    diagonal: null as string | null,
    reason: null as string | null,
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

  const start = useCallback(
    (plan?: {
      targetReps?: number;
      targetSets?: number;
      setNumber?: number;
    }) => {
      socketRef.current?.close();

      setResult(EMPTY_RESULT);
      setLastEvent({ kind: null, diagonal: null, reason: null, feedback: null });
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
          `${WS_BASE}/ws/dead_bug${query ? `?${query}` : ""}`,
        );
      } catch {
        setSocketError("Couldn't reach the detection server. Is it running?");
        return;
      }

      socketRef.current = ws;

      ws.onopen = () => setConnected(true);

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data) as DeadBugData;
        setResult(data);

        if (data.rep_completed) {
          setLastEvent({
            kind: "rep",
            diagonal: data.rep_diagonal,
            reason: null,
            feedback: data.feedback,
          });
        } else if (data.invalid_attempt) {
          setLastEvent({
            kind: "invalid",
            diagonal: null,
            reason: data.invalid_reason,
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
