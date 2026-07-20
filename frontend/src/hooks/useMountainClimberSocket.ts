import { useCallback, useEffect, useRef, useState } from "react";

export interface Landmark {
  x: number;
  y: number;
  z: number;
  visibility?: number;
}

/** Everything the FastAPI `MountainClimberAnalyzer` sends per frame. */
export interface MountainClimberData {
  pose_detected: boolean;
  ready: boolean;
  stance_ok: boolean;
  stance_message: string | null;
  framing_ok: boolean;
  framing_message: string | null;
  left_hip_angle: number | null;
  right_hip_angle: number | null;
  left_stage: "extended" | "driven";
  right_stage: "extended" | "driven";
  left_count: number;
  right_count: number;
  rep_count: number;
  target_reps: number | null;
  session_complete: boolean;
  drive_completed: boolean;
  drive_leg: "left" | "right" | null;
  drive_duration: number | null;
  drive_classification: string | null;
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

const EMPTY_RESULT: MountainClimberData = {
  pose_detected: false,
  ready: false,
  stance_ok: false,
  stance_message: null,
  framing_ok: true,
  framing_message: null,
  left_hip_angle: null,
  right_hip_angle: null,
  left_stage: "extended",
  right_stage: "extended",
  left_count: 0,
  right_count: 0,
  rep_count: 0,
  target_reps: null,
  session_complete: false,
  drive_completed: false,
  drive_leg: null,
  drive_duration: null,
  drive_classification: null,
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

export default function useMountainClimberSocket() {
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [socketError, setSocketError] = useState<string | null>(null);
  const [result, setResult] = useState<MountainClimberData>(EMPTY_RESULT);

  const [lastCompletedDrive, setLastCompletedDrive] = useState({
    leg: null as "left" | "right" | null,
    duration: null as number | null,
    classification: null as string | null,
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
      setLastCompletedDrive({
        leg: null,
        duration: null,
        classification: null,
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
        ws = new WebSocket(
          `${WS_BASE}/ws/mountain_climber${query ? `?${query}` : ""}`,
        );
      } catch {
        setSocketError("Couldn't reach the detection server. Is it running?");
        return;
      }

      socketRef.current = ws;

      ws.onopen = () => setConnected(true);

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data) as MountainClimberData;
        setResult(data);

        if (data.drive_completed) {
          setLastCompletedDrive({
            leg: data.drive_leg,
            duration: data.drive_duration,
            classification: data.drive_classification,
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
    lastCompletedDrive,
    sendFrame,
    start,
    stop,
    socketError,
  };
}
