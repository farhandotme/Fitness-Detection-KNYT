import { useCallback, useEffect, useRef, useState } from "react";

export interface Landmark {
  x: number;
  y: number;
  z: number;
  visibility?: number;
}

/** Everything the FastAPI `ShoulderStandAnalyzer` sends per frame. */
export interface ShoulderStandData {
  pose_detected: boolean;
  ready: boolean;
  stage: "not_in_pose" | "adjusting" | "holding" | string;
  hold_time: number;
  best_hold_time: number;
  target_hold_seconds: number | null;
  session_complete: boolean;
  interruption_count: number;
  position_ok: boolean;
  position_message: string | null;
  /** The strict, moment-to-moment gate that actually drives hold_time —
   * see shoulder_stand.py's module docstring for why this reacts fast to
   * a real break instead of the permissive grace window every other
   * exercise's position gate uses. */
  form_ok: boolean;
  framing_ok: boolean;
  framing_message: string | null;
  feedback: string | null;
  low_visibility: boolean;
  elapsed_time: number;
  hip_inversion_ok: boolean;
  legs_raised_ok: boolean;
  knee_straight_ok: boolean;
  alignment_ok: boolean;
  left_knee_angle: number | null;
  right_knee_angle: number | null;
  body_alignment_deg: number | null;
  landmarks: Landmark[];
  /** Which set (of the coach-assigned plan) this connection is for. */
  set_number?: number;
  /** Total sets in the coach-assigned plan. */
  target_sets?: number;
  /**
   * Backend-validated: true only once every set in the plan has hit its
   * target hold time. The frontend must treat this as the source of
   * truth for "the user completed this exercise" — it must not compute
   * this itself.
   */
  exercise_complete?: boolean;
}

const EMPTY_RESULT: ShoulderStandData = {
  pose_detected: false,
  ready: false,
  stage: "not_in_pose",
  hold_time: 0,
  best_hold_time: 0,
  target_hold_seconds: null,
  session_complete: false,
  interruption_count: 0,
  position_ok: false,
  position_message: null,
  form_ok: false,
  framing_ok: true,
  framing_message: null,
  feedback: null,
  low_visibility: false,
  elapsed_time: 0,
  hip_inversion_ok: false,
  legs_raised_ok: false,
  knee_straight_ok: false,
  alignment_ok: false,
  left_knee_angle: null,
  right_knee_angle: null,
  body_alignment_deg: null,
  landmarks: [],
  set_number: undefined,
  target_sets: undefined,
  exercise_complete: false,
};

const WS_BASE =
  (import.meta.env.VITE_WEBSOCKET_FASTAPI_URL as string | undefined) ||
  `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`;

export default function useShoulderStandSocket() {
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [socketError, setSocketError] = useState<string | null>(null);
  const [result, setResult] = useState<ShoulderStandData>(EMPTY_RESULT);

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
      targetHoldSeconds?: number;
      targetSets?: number;
      setNumber?: number;
    }) => {
      socketRef.current?.close();

      setResult(EMPTY_RESULT);
      setSocketError(null);

      // The coach-assigned plan is sent to the backend; the backend — not
      // this hook — decides when a set / the whole exercise is complete.
      const params = new URLSearchParams();
      if (plan?.targetHoldSeconds != null)
        params.set("target_hold_seconds", String(plan.targetHoldSeconds));
      if (plan?.targetSets != null)
        params.set("target_sets", String(plan.targetSets));
      if (plan?.setNumber != null)
        params.set("set_number", String(plan.setNumber));
      const query = params.toString();

      let ws: WebSocket;
      try {
        ws = new WebSocket(
          `${WS_BASE}/ws/shoulder_stand${query ? `?${query}` : ""}`,
        );
      } catch {
        setSocketError("Couldn't reach the detection server. Is it running?");
        return;
      }

      socketRef.current = ws;

      ws.onopen = () => setConnected(true);

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data) as ShoulderStandData;
        setResult(data);
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
    sendFrame,
    start,
    stop,
    socketError,
  };
}
