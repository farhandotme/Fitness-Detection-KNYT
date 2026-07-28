import { useCallback, useEffect, useRef, useState } from "react";

export interface Landmark {
  x: number;
  y: number;
  z: number;
  visibility?: number;
}

/** Everything the FastAPI `ArnoldPressAnalyzer` sends per frame. */
export interface ArnoldPressData {
  pose_detected: boolean;
  ready: boolean;
  stage: "down" | "up" | string;
  rep_count: number;
  good_reps: number;
  flawed_reps: number;
  left_elbow_angle: number | null;
  right_elbow_angle: number | null;
  arms_in_sync: boolean;
  top_reached: boolean;
  bottom_reached: boolean;
  rep_completed: boolean;
  rep_classification: string | null;
  rep_form_quality: string | null;
  position_ok: boolean;
  position_message: string | null;
  framing_ok: boolean;
  framing_message: string | null;
  feedback: string | null;
  target_reps: number | null;
  session_complete: boolean;
  low_visibility: boolean;
  elapsed_time: number;
  wrist_overhead_ok: boolean;
  torso_stable_ok: boolean;
  rep_duration: number | null;
  rep_avg_speed: number | null;
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

const EMPTY_RESULT: ArnoldPressData = {
  pose_detected: false,
  ready: false,
  stage: "down",
  rep_count: 0,
  good_reps: 0,
  flawed_reps: 0,
  left_elbow_angle: null,
  right_elbow_angle: null,
  arms_in_sync: true,
  top_reached: false,
  bottom_reached: false,
  rep_completed: false,
  rep_classification: null,
  rep_form_quality: null,
  position_ok: false,
  position_message: null,
  framing_ok: true,
  framing_message: null,
  feedback: null,
  target_reps: null,
  session_complete: false,
  low_visibility: false,
  elapsed_time: 0,
  wrist_overhead_ok: false,
  torso_stable_ok: true,
  rep_duration: null,
  rep_avg_speed: null,
  landmarks: [],
  set_number: undefined,
  target_sets: undefined,
  exercise_complete: false,
};

const WS_BASE =
  (import.meta.env.VITE_WEBSOCKET_FASTAPI_URL as string | undefined) ||
  `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`;

export default function useArnoldPressSocket() {
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [socketError, setSocketError] = useState<string | null>(null);
  const [result, setResult] = useState<ArnoldPressData>(EMPTY_RESULT);

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

  const start = useCallback(
    (plan?: {
      targetReps?: number;
      targetSets?: number;
      setNumber?: number;
    }) => {
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
          `${WS_BASE}/ws/arnold_press${query ? `?${query}` : ""}`,
        );
      } catch {
        setSocketError("Couldn't reach the detection server. Is it running?");
        return;
      }

      socketRef.current = ws;

      ws.onopen = () => setConnected(true);

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data) as ArnoldPressData;
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
