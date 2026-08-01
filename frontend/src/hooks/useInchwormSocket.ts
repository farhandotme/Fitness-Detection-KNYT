import { useCallback, useEffect, useRef, useState } from "react";

export interface Landmark {
  x: number;
  y: number;
  z: number;
  visibility?: number;
}

/** Everything the FastAPI `InchwormAnalyzer` sends per frame. */
export interface InchwormData {
  pose_detected: boolean;
  view_mode: "side" | "front" | "angled" | null;
  position_ok: boolean;
  position_message: string | null;
  ready: boolean;
  standing_confirmed: boolean;
  torso_incline: number | null;
  stage: "standing" | "plank";
  rep_count: number;
  good_reps: number;
  flawed_reps: number;
  partial_rep_count: number;
  target_reps: number | null;
  session_complete: boolean;
  rep_completed: boolean;
  rep_duration: number | null;
  rep_hold_duration: number | null;
  rep_classification: string | null;
  rep_form_quality: string | null;
  hold_progress: number;
  hold_elapsed: number | null;
  hold_required: number;
  hold_confirmed: boolean;
  hands_aligned: boolean;
  legs_straight: boolean;
  neck_neutral: boolean;
  alignment_ok: boolean;
  alignment_issue: string | null;
  framing_ok: boolean;
  framing_message: string | null;
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

const EMPTY_RESULT: InchwormData = {
  pose_detected: false,
  view_mode: null,
  position_ok: false,
  position_message: null,
  ready: false,
  standing_confirmed: true,
  torso_incline: null,
  stage: "standing",
  rep_count: 0,
  good_reps: 0,
  flawed_reps: 0,
  partial_rep_count: 0,
  target_reps: null,
  session_complete: false,
  rep_completed: false,
  rep_duration: null,
  rep_hold_duration: null,
  rep_classification: null,
  rep_form_quality: null,
  hold_progress: 0,
  hold_elapsed: null,
  hold_required: 1.0,
  hold_confirmed: false,
  hands_aligned: true,
  legs_straight: true,
  neck_neutral: true,
  alignment_ok: true,
  alignment_issue: null,
  framing_ok: true,
  framing_message: null,
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

export default function useInchwormSocket() {
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [socketError, setSocketError] = useState<string | null>(null);
  const [result, setResult] = useState<InchwormData>(EMPTY_RESULT);

  const [lastCompletedRep, setLastCompletedRep] = useState({
    rep_hold_duration: null as number | null,
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
        rep_hold_duration: null,
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
        ws = new WebSocket(`${WS_BASE}/ws/inchworm${query ? `?${query}` : ""}`);
      } catch {
        setSocketError("Couldn't reach the detection server. Is it running?");
        return;
      }

      socketRef.current = ws;

      ws.onopen = () => setConnected(true);

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data) as InchwormData;
        setResult(data);

        if (data.rep_completed) {
          setLastCompletedRep({
            rep_hold_duration: data.rep_hold_duration,
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
