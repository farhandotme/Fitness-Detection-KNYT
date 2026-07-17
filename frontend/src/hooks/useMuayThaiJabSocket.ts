import { useCallback, useEffect, useRef, useState } from "react";
import type { Landmark } from "./useSquatSocket";

export type { Landmark };

/**
 * Everything the FastAPI `JabAnalyzer` (muay_thai_jab.py) sends per frame.
 *
 * Note what's deliberately absent: there's no per-hand rep split (only a
 * combined `rep_count` — a jab drill is very often thrown lead-hand-only,
 * so the backend doesn't track left/right totals separately), and
 * `target_reps`/`session_complete`/`exercise_complete` never actually
 * resolve to anything meaningful — the current `/ws/jab` route always
 * connects with `target_reps=None`, so `session_complete` is permanently
 * `false` server-side. This hook still exposes those fields (for parity
 * with every other detector's shape, and in case the route is upgraded to
 * read them later), but the page does not depend on them — round length is
 * a client-side timer instead, the same way a real Muay Thai round works.
 */
export interface JabData {
  pose_detected: boolean;
  left_elbow_angle: number | null;
  right_elbow_angle: number | null;
  punching_hand: "left" | "right" | "both" | null;
  phase: string;
  stage: string;
  rep_count: number;
  good_reps: number;
  flawed_reps: number;
  partial_rep_count: number;
  not_counted_no_guard: number;
  target_reps: number | null;
  session_complete: boolean;
  rep_completed: boolean;
  rep_duration: number | null;
  rep_avg_speed: number | null;
  rep_classification: string | null;
  rep_form_quality: string | null;
  calibrated: boolean;
  guard_ok: boolean;
  posture_ok: boolean;
  posture_issues: string[];
  posture_messages: string[];
  framing_ok: boolean;
  framing_message: string | null;
  feedback: string | null;
  low_visibility: boolean;
  elapsed_time: number;
  landmarks: Landmark[];
  set_number?: number;
  target_sets?: number;
  exercise_complete?: boolean;
}

const EMPTY_RESULT: JabData = {
  pose_detected: false,
  left_elbow_angle: null,
  right_elbow_angle: null,
  punching_hand: null,
  phase: "guard",
  stage: "guard",
  rep_count: 0,
  good_reps: 0,
  flawed_reps: 0,
  partial_rep_count: 0,
  not_counted_no_guard: 0,
  target_reps: null,
  session_complete: false,
  rep_completed: false,
  rep_duration: null,
  rep_avg_speed: null,
  rep_classification: null,
  rep_form_quality: null,
  calibrated: false,
  guard_ok: false,
  posture_ok: true,
  posture_issues: [],
  posture_messages: [],
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

export default function useMuayThaiJabSocket() {
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
  const [result, setResult] = useState<JabData>(EMPTY_RESULT);

  const [lastCompletedRep, setLastCompletedRep] = useState({
    rep_duration: null as number | null,
    rep_avg_speed: null as number | null,
    rep_classification: null as string | null,
    rep_form_quality: null as string | null,
    feedback: null as string | null,
  });

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
      return `${WS_BASE}/ws/jab${query ? `?${query}` : ""}`;
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
            const data = JSON.parse(event.data) as JabData;
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
          } catch {
            /* already closing */
          }
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
      setLastCompletedRep({
        rep_duration: null,
        rep_avg_speed: null,
        rep_classification: null,
        rep_form_quality: null,
        feedback: null,
      });
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
