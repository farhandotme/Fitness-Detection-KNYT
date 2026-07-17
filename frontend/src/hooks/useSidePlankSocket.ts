import { useCallback, useEffect, useRef, useState } from "react";

export interface Landmark {
  x: number;
  y: number;
  z: number;
  visibility?: number;
}

export type ActiveSide = "left" | "right" | null;
export type HoldState = "holding" | "broken" | "not_started";

/** Everything the FastAPI `SidePlankHoldAnalyzer` sends per frame — see
 * side_plank.py's `update()` response dict, kept 1:1 with the backend.
 * Unlike the rep-based exercises, there is no rep_count here: progress is
 * a monotonically-increasing hold timer that only advances while
 * `is_holding` is true. */
export interface SidePlankData {
  pose_detected: boolean;
  active_side: ActiveSide;
  support_angle: number | null;
  alignment_angle: number | null;
  knee_angle: number | null;
  head_angle: number | null;
  hold_state: HoldState;
  is_holding: boolean;
  hold_seconds: number;
  good_seconds: number;
  flawed_seconds: number;
  current_streak_seconds: number;
  best_streak_seconds: number;
  break_count: number;
  target_seconds: number | null;
  session_complete: boolean;
  target_reached: boolean;
  hold_quality: "good" | "needs_improvement" | null;
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
  // Added by SidePlankHoldSession.detect() on top of the analyzer's dict.
  set_number: number;
  target_sets: number;
  exercise_complete: boolean;
}

const EMPTY_RESULT: SidePlankData = {
  pose_detected: false,
  active_side: null,
  support_angle: null,
  alignment_angle: null,
  knee_angle: null,
  head_angle: null,
  hold_state: "not_started",
  is_holding: false,
  hold_seconds: 0,
  good_seconds: 0,
  flawed_seconds: 0,
  current_streak_seconds: 0,
  best_streak_seconds: 0,
  break_count: 0,
  target_seconds: null,
  session_complete: false,
  target_reached: false,
  hold_quality: null,
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
  set_number: 1,
  target_sets: 1,
  exercise_complete: false,
};

const WS_BASE =
  (import.meta.env.VITE_WEBSOCKET_FASTAPI_URL as string | undefined) ||
  `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`;

export default function useSidePlankSocket() {
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [socketError, setSocketError] = useState<string | null>(null);
  const [result, setResult] = useState<SidePlankData>(EMPTY_RESULT);

  // Mirrors lastCompletedRep in the rep-based hooks, but there's no
  // discrete "rep" here — this tracks the last time-based milestone
  // (target reached, or a break in the hold) so the UI has something
  // stable to show even after the underlying signal has passed.
  const [lastEvent, setLastEvent] = useState({
    kind: null as "target_reached" | "break" | null,
    feedback: null as string | null,
  });

  const prevHoldingRef = useRef(false);

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

  const start = useCallback(() => {
    socketRef.current?.close();

    setResult(EMPTY_RESULT);
    setLastEvent({ kind: null, feedback: null });
    setSocketError(null);
    prevHoldingRef.current = false;

    let ws: WebSocket;
    try {
      // Single unprefixed "/side_plank" path (see sidePlankRoutes.py),
      // mounted under the app-wide "/ws" prefix in main.py.
      ws = new WebSocket(`${WS_BASE}/ws/side_plank`);
    } catch {
      setSocketError("Couldn't reach the detection server. Is it running?");
      return;
    }

    socketRef.current = ws;

    ws.onopen = () => setConnected(true);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data) as SidePlankData;
      setResult(data);

      if (data.target_reached) {
        setLastEvent({ kind: "target_reached", feedback: data.feedback });
      } else if (prevHoldingRef.current && !data.is_holding) {
        // Just came out of a hold — surface why, so the person sees the
        // break reason instead of it flashing past.
        setLastEvent({ kind: "break", feedback: data.feedback });
      }
      prevHoldingRef.current = data.is_holding;
    };

    ws.onclose = () => {
      setConnected(false);
      socketRef.current = null;
    };

    ws.onerror = () => {
      setSocketError("Connection error — check that the backend is running.");
    };
  }, []);

  const sendFrame = useCallback((image: string) => {
    const ws = socketRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(image);
  }, []);

  return {
    connected,
    result,
    lastEvent,
    sendFrame,
    start,
    stop,
    socketError,
  };
}
