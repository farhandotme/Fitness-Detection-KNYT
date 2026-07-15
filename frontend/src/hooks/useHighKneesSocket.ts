import { useCallback, useEffect, useRef, useState } from "react";
import type { Landmark } from "./useSquatSocket";

export type { Landmark };

/** Everything the FastAPI `HighKneeAnalyzer` sends per frame. */
export interface HighKneesData {
  pose_detected: boolean;
  left_angle: number | null;
  right_angle: number | null;
  active_leg: "left" | "right" | null;
  lift: number | null;
  smoothed_lift: number | null;
  stage: string;
  rep_count: number;
  good_reps: number;
  flawed_reps: number;
  partial_rep_count: number;
  left_reps: number;
  right_reps: number;
  target_reps: number | null;
  session_complete: boolean;
  rep_completed: boolean;
  rep_leg: "left" | "right" | null;
  rep_duration: number | null;
  rep_classification: string | null;
  rep_form_quality: string | null;
  alternation_ok: boolean;
  calibrated: boolean;
  posture_ok: boolean;
  posture_issues: string[];
  posture_messages: string[];
  framing_ok: boolean;
  framing_message: string | null;
  form_score: number | null;
  avg_form_score: number | null;
  reps_per_minute: number | null;
  pace_classification: string | null;
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

const EMPTY_RESULT: HighKneesData = {
  pose_detected: false,
  left_angle: null,
  right_angle: null,
  active_leg: null,
  lift: null,
  smoothed_lift: null,
  stage: "down",
  rep_count: 0,
  good_reps: 0,
  flawed_reps: 0,
  partial_rep_count: 0,
  left_reps: 0,
  right_reps: 0,
  target_reps: null,
  session_complete: false,
  rep_completed: false,
  rep_leg: null,
  rep_duration: null,
  rep_classification: null,
  rep_form_quality: null,
  alternation_ok: true,
  calibrated: false,
  posture_ok: true,
  posture_issues: [],
  posture_messages: [],
  framing_ok: true,
  framing_message: null,
  form_score: null,
  avg_form_score: null,
  reps_per_minute: null,
  pace_classification: null,
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

export default function useHighKneesSocket() {
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [socketError, setSocketError] = useState<string | null>(null);
  const [result, setResult] = useState<HighKneesData>(EMPTY_RESULT);

  const [lastCompletedRep, setLastCompletedRep] = useState({
    rep_duration: null as number | null,
    rep_classification: null as string | null,
    rep_form_quality: null as string | null,
    form_score: null as number | null,
    rep_leg: null as "left" | "right" | null,
    alternation_ok: true,
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
        rep_classification: null,
        rep_form_quality: null,
        form_score: null,
        rep_leg: null,
        alternation_ok: true,
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
          `${WS_BASE}/ws/high_knees${query ? `?${query}` : ""}`,
        );
      } catch {
        setSocketError("Couldn't reach the detection server. Is it running?");
        return;
      }

      socketRef.current = ws;

      ws.onopen = () => setConnected(true);

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data) as HighKneesData;
        setResult(data);
        // console.log(data);

        if (data.rep_completed) {
          setLastCompletedRep({
            rep_duration: data.rep_duration,
            rep_classification: data.rep_classification,
            rep_form_quality: data.rep_form_quality,
            form_score: data.form_score,
            rep_leg: data.rep_leg,
            alternation_ok: data.alternation_ok,
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
