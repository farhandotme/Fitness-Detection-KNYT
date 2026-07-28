import { useCallback, useEffect, useRef, useState } from "react";

export interface Landmark {
  x: number;
  y: number;
  z: number;
  visibility?: number;
}

/** Everything the FastAPI `HinduPushupAnalyzer` sends per frame. */
export interface HinduPushupData {
  pose_detected: boolean;
  view_mode: "side" | "front" | "angled" | null;
  position_ok: boolean;
  position_message: string | null;
  ready: boolean;
  hip_arc: number | null;
  smoothed_hip_arc: number | null;
  left_elbow_angle: number | null;
  right_elbow_angle: number | null;
  elbow_angle: number | null;
  head_lift: number | null;
  arc_velocity: number | null;
  /** "downdog" = piked rest position, "updog" = sagged Cobra position. */
  stage: "downdog" | "updog";
  rep_count: number;
  good_reps: number;
  flawed_reps: number;
  partial_rep_count: number;
  target_reps: number | null;
  session_complete: boolean;
  rep_completed: boolean;
  rep_duration: number | null;
  rep_avg_speed: number | null;
  rep_classification: string | null;
  rep_form_quality: string | null;
  alignment_ok: boolean;
  alignment_issue: string | null;
  framing_ok: boolean;
  framing_message: string | null;
  feedback: string | null;
  low_visibility: boolean;
  elapsed_time: number;
  landmarks: Landmark[];
  set_number?: number;
  target_sets?: number;
  /**
   * Backend-validated: true only once every set in the plan hit its
   * target reps. The frontend treats this as the source of truth for
   * "the user completed this exercise" — it never computes this itself.
   */
  exercise_complete?: boolean;
}

const EMPTY_RESULT: HinduPushupData = {
  pose_detected: false,
  view_mode: null,
  position_ok: false,
  position_message: null,
  ready: false,
  hip_arc: null,
  smoothed_hip_arc: null,
  left_elbow_angle: null,
  right_elbow_angle: null,
  elbow_angle: null,
  head_lift: null,
  arc_velocity: null,
  stage: "downdog",
  rep_count: 0,
  good_reps: 0,
  flawed_reps: 0,
  partial_rep_count: 0,
  target_reps: null,
  session_complete: false,
  rep_completed: false,
  rep_duration: null,
  rep_avg_speed: null,
  rep_classification: null,
  rep_form_quality: null,
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

export default function useHinduPushupSocket() {
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [socketError, setSocketError] = useState<string | null>(null);
  const [result, setResult] = useState<HinduPushupData>(EMPTY_RESULT);

  const [lastCompletedRep, setLastCompletedRep] = useState({
    rep_duration: null as number | null,
    rep_avg_speed: null as number | null,
    rep_classification: null as string | null,
    rep_form_quality: null as string | null,
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
      setLastCompletedRep({
        rep_duration: null,
        rep_avg_speed: null,
        rep_classification: null,
        rep_form_quality: null,
        feedback: null,
      });
      setSocketError(null);

      const params = new URLSearchParams();
      if (plan?.targetReps != null) params.set("target_reps", String(plan.targetReps));
      if (plan?.targetSets != null) params.set("target_sets", String(plan.targetSets));
      if (plan?.setNumber != null) params.set("set_number", String(plan.setNumber));
      const query = params.toString();

      let ws: WebSocket;
      try {
        ws = new WebSocket(`${WS_BASE}/ws/hindu_pushup${query ? `?${query}` : ""}`);
      } catch {
        setSocketError("Couldn't reach the detection server. Is it running?");
        return;
      }

      socketRef.current = ws;

      ws.onopen = () => setConnected(true);

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data) as HinduPushupData;
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
