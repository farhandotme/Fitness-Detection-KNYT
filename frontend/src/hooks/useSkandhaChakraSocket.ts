import { useCallback, useEffect, useRef, useState } from "react";

export interface Landmark {
  x: number;
  y: number;
  z: number;
  visibility?: number;
}

export type RotationDirection = "forward" | "backward" | "either";

/** Everything the FastAPI `SkandhaChakraAnalyzer` sends per frame. */
export interface SkandhaChakraData {
  pose_detected: boolean;
  ready: boolean;
  stage: "rotating" | "waiting" | string;
  rep_count: number;
  good_reps: number;
  flawed_reps: number;
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
  left_arm_angle: number | null;
  right_arm_angle: number | null;
  arms_in_sync: boolean;
  /** 0-1, how far through the current revolution the accumulated
   * rotation is — drives a "circle progress" ring in the UI. */
  rotation_progress: number;
  rotation_direction: "forward" | "backward" | null;
  target_direction: RotationDirection;
  rep_duration: number | null;
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

const EMPTY_RESULT: SkandhaChakraData = {
  pose_detected: false,
  ready: false,
  stage: "waiting",
  rep_count: 0,
  good_reps: 0,
  flawed_reps: 0,
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
  left_arm_angle: null,
  right_arm_angle: null,
  arms_in_sync: true,
  rotation_progress: 0,
  rotation_direction: null,
  target_direction: "either",
  rep_duration: null,
  landmarks: [],
  set_number: undefined,
  target_sets: undefined,
  exercise_complete: false,
};

const WS_BASE =
  (import.meta.env.VITE_WEBSOCKET_FASTAPI_URL as string | undefined) ||
  `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`;

export default function useSkandhaChakraSocket() {
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [socketError, setSocketError] = useState<string | null>(null);
  const [result, setResult] = useState<SkandhaChakraData>(EMPTY_RESULT);

  const [lastCompletedRep, setLastCompletedRep] = useState({
    rep_classification: null as string | null,
    rep_form_quality: null as string | null,
    rotation_direction: null as "forward" | "backward" | null,
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
      direction?: RotationDirection;
    }) => {
      socketRef.current?.close();

      setResult({ ...EMPTY_RESULT, target_direction: plan?.direction ?? "either" });
      setLastCompletedRep({
        rep_classification: null,
        rep_form_quality: null,
        rotation_direction: null,
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
      if (plan?.direction != null) params.set("direction", plan.direction);
      const query = params.toString();

      let ws: WebSocket;
      try {
        ws = new WebSocket(`${WS_BASE}/ws/skandha_chakra${query ? `?${query}` : ""}`);
      } catch {
        setSocketError("Couldn't reach the detection server. Is it running?");
        return;
      }

      socketRef.current = ws;

      ws.onopen = () => setConnected(true);

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data) as SkandhaChakraData;
        setResult(data);

        if (data.rep_completed) {
          setLastCompletedRep({
            rep_classification: data.rep_classification,
            rep_form_quality: data.rep_form_quality,
            rotation_direction: data.rotation_direction,
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
