import { useCallback, useEffect, useRef, useState } from "react";

export interface Landmark {
  x: number;
  y: number;
  z: number;
  visibility?: number;
}

/** Everything the FastAPI `ArmCirclesAnalyzer` sends per frame. */
export interface ArmCirclesData {
  pose_detected: boolean;
  framing_ok: boolean;
  framing_message: string | null;
  left_arm_extended: boolean;
  right_arm_extended: boolean;
  left_elbow_angle: number | null;
  right_elbow_angle: number | null;
  left_direction: "forward" | "backward" | null;
  right_direction: "forward" | "backward" | null;
  /** Raw per-arm circle counts — always increment the instant that arm alone finishes a circle. */
  left_arm_rounds: number;
  right_arm_rounds: number;
  /** Both-arms-synced rounds — this is what target_reps/session_complete is based on. */
  rep_count: number;
  good_reps: number;
  flawed_reps: number;
  target_reps: number | null;
  session_complete: boolean;
  rep_completed: boolean;
  rep_form_quality: "good" | "needs_improvement" | null;
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
   * target rounds. The frontend must treat this as the source of truth
   * for "the user completed this exercise" — it must not compute this
   * itself.
   */
  exercise_complete?: boolean;
}

const EMPTY_RESULT: ArmCirclesData = {
  pose_detected: false,
  framing_ok: true,
  framing_message: null,
  left_arm_extended: false,
  right_arm_extended: false,
  left_elbow_angle: null,
  right_elbow_angle: null,
  left_direction: null,
  right_direction: null,
  left_arm_rounds: 0,
  right_arm_rounds: 0,
  rep_count: 0,
  good_reps: 0,
  flawed_reps: 0,
  target_reps: null,
  session_complete: false,
  rep_completed: false,
  rep_form_quality: null,
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

export default function useArmCirclesSocket() {
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [socketError, setSocketError] = useState<string | null>(null);
  const [result, setResult] = useState<ArmCirclesData>(EMPTY_RESULT);

  const [lastCompletedRep, setLastCompletedRep] = useState({
    rep_form_quality: null as "good" | "needs_improvement" | null,
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
    (plan?: { targetReps?: number; targetSets?: number; setNumber?: number }) => {
      socketRef.current?.close();

      setResult(EMPTY_RESULT);
      setLastCompletedRep({ rep_form_quality: null, feedback: null });
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
        ws = new WebSocket(`${WS_BASE}/ws/arm_circles${query ? `?${query}` : ""}`);
      } catch {
        setSocketError("Couldn't reach the detection server. Is it running?");
        return;
      }

      socketRef.current = ws;

      ws.onopen = () => setConnected(true);

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data) as ArmCirclesData;
        setResult(data);

        if (data.rep_completed) {
          setLastCompletedRep({
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
