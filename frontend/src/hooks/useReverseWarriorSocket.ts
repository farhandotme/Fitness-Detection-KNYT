import { useCallback, useEffect, useRef, useState } from "react";

export interface Landmark {
  x: number;
  y: number;
  z: number;
  visibility: number | null;
}

/** Everything the FastAPI `ReverseWarriorAnalyzer` sends per frame. */
export interface ReverseWarriorData {
  pose_detected: boolean;
  front_side: "left" | "right" | null;
  stance_ratio: number | null;
  front_knee_angle: number | null;
  back_knee_angle: number | null;
  raised_elbow_angle: number | null;
  raised_wrist_height: number | null;
  lowered_elbow_angle?: number | null;
  lowered_wrist_height?: number | null;
  torso_lean: number | null;
  hold_state: "not_started" | "holding" | "broken";
  is_holding: boolean;
  hold_seconds: number;
  good_seconds: number;
  flawed_seconds: number;
  current_streak_seconds: number;
  best_streak_seconds: number;
  break_count: number;
  target_seconds: number | null;
  session_complete: boolean;
  /** Edge-triggered: true for exactly one frame the moment the target is met. */
  target_reached: boolean;
  hold_quality: "good" | "needs_improvement" | null;
  posture_ok: boolean;
  posture_issues: string[];
  posture_messages: string[];
  framing_ok: boolean;
  framing_message: string | null;
  form_score: number | null;
  avg_form_score: number | null;
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
   * target hold time. The frontend must treat this as the source of truth
   * for "the user completed this exercise" — it must not compute this
   * itself, and it must not count time the backend didn't already count.
   */
  exercise_complete?: boolean;
}

const EMPTY_RESULT: ReverseWarriorData = {
  pose_detected: false,
  front_side: null,
  stance_ratio: null,
  front_knee_angle: null,
  back_knee_angle: null,
  raised_elbow_angle: null,
  raised_wrist_height: null,
  torso_lean: null,
  hold_state: "not_started",
  is_holding: false,
  hold_seconds: 0,
  good_seconds: 0,
  flawed_seconds: 0,
  current_streak_seconds: 0,
  best_streak_seconds: 0,
  break_count: 0,
  target_seconds: null,
  session_complete: false,
  target_reached: false,
  hold_quality: null,
  posture_ok: true,
  posture_issues: [],
  posture_messages: [],
  framing_ok: true,
  framing_message: null,
  form_score: null,
  avg_form_score: null,
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

export default function useReverseWarriorSocket() {
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [socketError, setSocketError] = useState<string | null>(null);
  const [result, setResult] = useState<ReverseWarriorData>(EMPTY_RESULT);

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
      targetSeconds?: number;
      targetSets?: number;
      setNumber?: number;
    }) => {
      socketRef.current?.close();

      setResult(EMPTY_RESULT);
      setSocketError(null);

      // The coach-assigned plan is sent to the backend; the backend — not
      // this hook — decides whether a set / the whole exercise is complete.
      const params = new URLSearchParams();
      if (plan?.targetSeconds != null)
        params.set("target_seconds", String(plan.targetSeconds));
      if (plan?.targetSets != null)
        params.set("target_sets", String(plan.targetSets));
      if (plan?.setNumber != null)
        params.set("set_number", String(plan.setNumber));
      const query = params.toString();

      let ws: WebSocket;
      try {
        ws = new WebSocket(
          `${WS_BASE}/ws/reverse_warrior${query ? `?${query}` : ""}`,
        );
      } catch {
        setSocketError("Couldn't reach the detection server. Is it running?");
        return;
      }

      socketRef.current = ws;

      ws.onopen = () => setConnected(true);

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data) as ReverseWarriorData;
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
