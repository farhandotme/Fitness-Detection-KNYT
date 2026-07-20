import { useCallback, useEffect, useRef, useState } from "react";
import type { Landmark } from "./usePushupSocket";

export type { Landmark };

/** Everything the FastAPI `BirdDogAnalyzer` sends per frame. */
export interface BirdDogData {
  pose_detected: boolean;
  ready: boolean;
  /** True for the first ~1s of a session while the backend is learning
   * this person's resting tabletop angles (see bird_dog.py docstring —
   * reach detection is calibrated per-session, not a fixed angle). */
  calibrating: boolean;
  base_calibrated: boolean;
  baseline_arm_angle: number | null;
  baseline_leg_angle: number | null;
  stage: "tabletop" | "reaching";
  reach_arm_side: "left" | "right" | null;
  reach_leg_side: "left" | "right" | null;
  left_arm_reach_angle: number | null;
  right_arm_reach_angle: number | null;
  left_leg_reach_angle: number | null;
  right_leg_reach_angle: number | null;
  elbow_angle: number | null;
  knee_angle: number | null;
  alignment_angle: number | null;
  rep_count: number;
  good_reps: number;
  flawed_reps: number;
  rejected_reps: number;
  target_reps: number | null;
  session_complete: boolean;
  rep_completed: boolean;
  rep_form_quality: "good" | "needs_improvement" | null;
  posture_issues: string[];
  framing_ok: boolean;
  framing_message: string | null;
  calibrated: boolean;
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

const EMPTY_RESULT: BirdDogData = {
  pose_detected: false,
  ready: false,
  calibrating: true,
  base_calibrated: false,
  baseline_arm_angle: null,
  baseline_leg_angle: null,
  stage: "tabletop",
  reach_arm_side: null,
  reach_leg_side: null,
  left_arm_reach_angle: null,
  right_arm_reach_angle: null,
  left_leg_reach_angle: null,
  right_leg_reach_angle: null,
  elbow_angle: null,
  knee_angle: null,
  alignment_angle: null,
  rep_count: 0,
  good_reps: 0,
  flawed_reps: 0,
  rejected_reps: 0,
  target_reps: null,
  session_complete: false,
  rep_completed: false,
  rep_form_quality: null,
  posture_issues: [],
  framing_ok: true,
  framing_message: null,
  calibrated: false,
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

export default function useBirdDogSocket() {
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [socketError, setSocketError] = useState<string | null>(null);
  const [result, setResult] = useState<BirdDogData>(EMPTY_RESULT);

  // Sticky feedback for the most recently *scored* rep (counted OR
  // rejected) so the coach message doesn't disappear the instant the
  // user drops back to tabletop, same UX convention as usePushupSocket.
  const [lastRepEvent, setLastRepEvent] = useState({
    rep_form_quality: null as string | null,
    feedback: null as string | null,
    was_rejected: false,
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
    (plan?: { targetReps?: number; targetSets?: number; setNumber?: number }) => {
      socketRef.current?.close();

      setResult(EMPTY_RESULT);
      setLastRepEvent({
        rep_form_quality: null,
        feedback: null,
        was_rejected: false,
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
        ws = new WebSocket(`${WS_BASE}/ws/bird_dog${query ? `?${query}` : ""}`);
      } catch {
        setSocketError("Couldn't reach the detection server. Is it running?");
        return;
      }

      socketRef.current = ws;

      ws.onopen = () => setConnected(true);

      let prevRejectedReps = 0;

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data) as BirdDogData;
        setResult(data);

        if (data.rep_completed) {
          setLastRepEvent({
            rep_form_quality: data.rep_form_quality,
            feedback: data.feedback,
            was_rejected: false,
          });
        } else if (data.rejected_reps > prevRejectedReps) {
          // An attempt just failed the anti-cheat / partial-rep gate —
          // still surface that feedback prominently, it's the whole point.
          setLastRepEvent({
            rep_form_quality: "needs_improvement",
            feedback: data.feedback,
            was_rejected: true,
          });
        }
        prevRejectedReps = data.rejected_reps;
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
    lastRepEvent,
    sendFrame,
    start,
    stop,
    socketError,
  };
}
