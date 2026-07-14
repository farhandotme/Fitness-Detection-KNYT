import { useCallback, useEffect, useRef, useState } from "react";
import type { Landmark } from "./useSquatSocket";

export type { Landmark };

/** Everything the FastAPI `LungeAnalyzer` sends per frame. */
export interface LungeData {
  pose_detected: boolean;
  depth: number | null;
  smoothed_depth: number | null;
  front_knee_angle: number | null;
  back_knee_angle: number | null;
  left_knee_angle: number | null;
  right_knee_angle: number | null;
  active_leg: "left" | "right" | null;
  depth_velocity: number | null;
  stage: string;
  rep_count: number;
  good_reps: number;
  flawed_reps: number;
  partial_rep_count: number;
  left_reps: number;
  right_reps: number;
  leg_balance_ok: boolean;
  leg_balance_message: string | null;
  target_reps: number | null;
  session_complete: boolean;
  rep_completed: boolean;
  rep_duration: number | null;
  rep_avg_speed: number | null;
  rep_classification: string | null;
  rep_form_quality: string | null;
  calibrated: boolean;
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
   * target reps. The frontend must treat this as the source of truth for
   * "the user completed this exercise" — it must not compute this itself.
   */
  exercise_complete?: boolean;
}

const EMPTY_RESULT: LungeData = {
  pose_detected: false,
  depth: null,
  smoothed_depth: null,
  front_knee_angle: null,
  back_knee_angle: null,
  left_knee_angle: null,
  right_knee_angle: null,
  active_leg: null,
  depth_velocity: null,
  stage: "standing",
  rep_count: 0,
  good_reps: 0,
  flawed_reps: 0,
  partial_rep_count: 0,
  left_reps: 0,
  right_reps: 0,
  leg_balance_ok: true,
  leg_balance_message: null,
  target_reps: null,
  session_complete: false,
  rep_completed: false,
  rep_duration: null,
  rep_avg_speed: null,
  rep_classification: null,
  rep_form_quality: null,
  calibrated: false,
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

export default function useLungeSocket() {
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [socketError, setSocketError] = useState<string | null>(null);
  const [result, setResult] = useState<LungeData>(EMPTY_RESULT);

  const [lastCompletedRep, setLastCompletedRep] = useState({
    rep_duration: null as number | null,
    rep_avg_speed: null as number | null,
    rep_classification: null as string | null,
    rep_form_quality: null as string | null,
    form_score: null as number | null,
    active_leg: null as "left" | "right" | null,
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
        form_score: null,
        active_leg: null,
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
        ws = new WebSocket(`${WS_BASE}/ws/lunge${query ? `?${query}` : ""}`);
      } catch {
        setSocketError("Couldn't reach the detection server. Is it running?");
        return;
      }

      socketRef.current = ws;

      ws.onopen = () => setConnected(true);

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data) as LungeData;
        setResult(data);

        if (data.rep_completed) {
          setLastCompletedRep({
            rep_duration: data.rep_duration,
            rep_avg_speed: data.rep_avg_speed,
            rep_classification: data.rep_classification,
            rep_form_quality: data.rep_form_quality,
            form_score: data.form_score,
            active_leg: data.active_leg,
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
