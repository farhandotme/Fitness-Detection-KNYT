import { useCallback, useEffect, useRef, useState } from "react";
import type { Landmark } from "./useSquatSocket";

export type { Landmark };

export interface MountainClimberData {
  pose_detected: boolean;
  active_leg: "left" | "right" | null;
  stage: string;
  rep_count: number;
  good_reps: number;
  flawed_reps: number;
  target_reps: number | null;
  session_complete: boolean;
  rep_completed: boolean;
  rep_leg: "left" | "right" | null;
  rep_duration: number | null;
  rep_classification: string | null;
  rep_form_quality: string | null;
  form_score: number | null;
  avg_form_score: number | null;
  reps_per_minute: number | null;
  pace_classification: string | null;
  posture_ok: boolean;
  posture_issues: string[];
  posture_messages: string[];
  framing_ok: boolean;
  framing_message: string | null;
  feedback: string | null;
  calibrated?: boolean;
  low_visibility: boolean;
  left_knee_drive: boolean | number | null;
  right_knee_drive: boolean | number | null;
  body_alignment: number | null;
  elapsed_time: number;
  landmarks: Landmark[];
  set_number?: number;
  target_sets?: number;
  exercise_complete?: boolean;
}

const EMPTY_RESULT: MountainClimberData = {
  pose_detected: false,
  active_leg: null,
  stage: "ready",
  rep_count: 0,
  good_reps: 0,
  flawed_reps: 0,
  target_reps: null,
  session_complete: false,
  rep_completed: false,
  rep_leg: null,
  rep_duration: null,
  rep_classification: null,
  rep_form_quality: null,
  form_score: null,
  avg_form_score: null,
  reps_per_minute: null,
  pace_classification: null,
  posture_ok: true,
  posture_issues: [],
  posture_messages: [],
  framing_ok: true,
  framing_message: null,
  feedback: null,
  low_visibility: false,
  left_knee_drive: null,
  right_knee_drive: null,
  body_alignment: null,
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
  const reconnectRef = useRef(0);
  const manualCloseRef = useRef(false);
  const retryTimerRef = useRef<number | null>(null);
  const lastPlanRef = useRef<{
    targetReps?: number;
    targetSets?: number;
    setNumber?: number;
  } | null>(null);

  const [connected, setConnected] = useState(false);
  const [socketError, setSocketError] = useState<string | null>(null);
  const [result, setResult] = useState<MountainClimberData>(EMPTY_RESULT);

  const stop = useCallback(() => {
    manualCloseRef.current = true;
    reconnectRef.current = 0;
    if (retryTimerRef.current) {
      window.clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
    socketRef.current?.close();
    socketRef.current = null;
    setConnected(false);
  }, []);

  useEffect(() => {
    return () => {
      stop();
    };
  }, [stop]);

  const buildUrl = useCallback(
    (plan?: {
      targetReps?: number;
      targetSets?: number;
      setNumber?: number;
    }) => {
      const params = new URLSearchParams();
      if (plan?.targetReps != null)
        params.set("target_reps", String(plan.targetReps));
      if (plan?.targetSets != null)
        params.set("target_sets", String(plan.targetSets));
      if (plan?.setNumber != null)
        params.set("set_number", String(plan.setNumber));
      const query = params.toString();
      return `${WS_BASE}/ws/mountain_climber${query ? `?${query}` : ""}`;
    },
    [],
  );

  const connect = useCallback(
    (plan?: {
      targetReps?: number;
      targetSets?: number;
      setNumber?: number;
    }) => {
      const url = buildUrl(plan);

      try {
        const ws = new WebSocket(url);
        socketRef.current = ws;

        ws.onopen = () => {
          reconnectRef.current = 0;
          setConnected(true);
          setSocketError(null);
        };

        ws.onmessage = (event) => {
          try {
            setResult(JSON.parse(event.data) as MountainClimberData);
          } catch {
            setSocketError("Received invalid data from server.");
          }
        };

        ws.onclose = () => {
          setConnected(false);

          if (manualCloseRef.current) {
            socketRef.current = null;
            return;
          }

          const tries = reconnectRef.current;
          if (tries >= 5) {
            setSocketError(
              "Couldn't reach the detection server. Is it running?",
            );
            socketRef.current = null;
            return;
          }

          reconnectRef.current = tries + 1;
          if (retryTimerRef.current) window.clearTimeout(retryTimerRef.current);
          retryTimerRef.current = window.setTimeout(
            () => {
              connect(lastPlanRef.current ?? undefined);
            },
            1000 * (tries + 1),
          );
        };

        ws.onerror = () => {
          setSocketError(
            "Connection error — check that the backend is running.",
          );
          try {
            ws.close();
          } catch {}
        };
      } catch {
        setSocketError("Couldn't create WebSocket connection.");
      }
    },
    [buildUrl],
  );

  const start = useCallback(
    (plan?: {
      targetReps?: number;
      targetSets?: number;
      setNumber?: number;
    }) => {
      manualCloseRef.current = false;
      reconnectRef.current = 0;
      lastPlanRef.current = plan ?? null;
      if (retryTimerRef.current) {
        window.clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
      socketRef.current?.close();
      socketRef.current = null;
      setResult(EMPTY_RESULT);
      setSocketError(null);
      connect(plan);
    },
    [connect],
  );

  const sendFrame = useCallback((image: string) => {
    const ws = socketRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(image);
  }, []);

  return { connected, result, sendFrame, start, stop, socketError };
}
