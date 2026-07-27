import { useCallback, useEffect, useRef, useState } from "react";

export interface Landmark {
  x: number;
  y: number;
  z: number;
  visibility?: number;
}

/** Everything the FastAPI `RussianTwistAnalyzer` sends per frame. */
export interface RussianTwistData {
  pose_detected: boolean;
  seated_ok: boolean;
  seated_message: string | null;
  ready: boolean;
  framing_ok: boolean;
  framing_message: string | null;
  torso_rotation_deg: number | null;
  raw_rotation_deg: number | null;
  shoulder_hip_ratio: number | null;
  baseline_ratio: number | null;
  rotation_envelope_deg: number | null;
  phase: "center" | "left" | "right";
  left_count: number;
  right_count: number;
  rep_count: number;
  target_reps: number | null;
  session_complete: boolean;
  rep_completed: boolean;
  side_completed: boolean;
  side_completed_which: "left" | "right" | null;
  legs_stable: boolean;
  legs_visible: boolean;
  leg_message: string | null;
  low_visibility: boolean;
  feedback: string | null;
  elapsed_time: number;
  landmarks: Landmark[];
  /** Which set (of the coach-assigned plan) this connection is for. */
  set_number?: number;
  /** Total sets in the coach-assigned plan. */
  target_sets?: number;
  /**
   * Backend-validated: true only once every set in the plan has hit its
   * target reps. The frontend must treat this as the source of truth for
   * "the user completed this exercise" — it must not compute this itself.
   */
  exercise_complete?: boolean;
}

const EMPTY_RESULT: RussianTwistData = {
  pose_detected: false,
  seated_ok: false,
  seated_message: null,
  ready: false,
  framing_ok: true,
  framing_message: null,
  torso_rotation_deg: null,
  raw_rotation_deg: null,
  shoulder_hip_ratio: null,
  baseline_ratio: null,
  rotation_envelope_deg: null,
  phase: "center",
  left_count: 0,
  right_count: 0,
  rep_count: 0,
  target_reps: null,
  session_complete: false,
  rep_completed: false,
  side_completed: false,
  side_completed_which: null,
  legs_stable: true,
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

export default function useRussianTwistSocket() {
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [socketError, setSocketError] = useState<string | null>(null);
  const [result, setResult] = useState<RussianTwistData>(EMPTY_RESULT);

  // Mirrors usePushupSocket's `lastCompletedRep` — the transient feedback
  // that only lives on the one frame a side touch (or full rep) lands
  // gets latched here so the UI can keep showing it until the next event.
  const [lastEvent, setLastEvent] = useState({
    side: null as "left" | "right" | null,
    wasFullRep: false,
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
      setLastEvent({ side: null, wasFullRep: false, feedback: null });
      setSocketError(null);

      // The coach-assigned plan is sent to the backend; the backend — not
      // this hook — decides when a set / the whole exercise is complete.
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
          `${WS_BASE}/ws/russian_twist${query ? `?${query}` : ""}`,
        );
      } catch {
        setSocketError("Couldn't reach the detection server. Is it running?");
        return;
      }

      socketRef.current = ws;

      ws.onopen = () => setConnected(true);

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data) as RussianTwistData;
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
