import { useCallback, useEffect, useRef, useState } from "react";

export interface Landmark {
  x: number;
  y: number;
  z: number;
  visibility?: number;
}

export type SquatSide = "left" | "right";
export type SquatMode = "assisted" | "standard" | "deep";

/** Everything the FastAPI `SingleLegSquatAnalyzer` sends per frame. */
export interface SingleLegSquatData {
  pose_detected: boolean;
  ready: boolean;
  stage: "standing" | "descending" | "bottom" | "rising" | string;
  rep_count: number;
  left_reps: number;
  right_reps: number;
  good_reps: number;
  flawed_reps: number;
  rep_completed: boolean;
  rep_classification: string | null;
  rep_form_quality: string | null;
  current_side: SquatSide;
  position_ok: boolean;
  position_message: string | null;
  framing_ok: boolean;
  framing_message: string | null;
  feedback: string | null;
  target_reps: number | null;
  session_complete: boolean;
  low_visibility: boolean;
  elapsed_time: number;
  stance_knee_angle: number | null;
  hip_depth_ratio: number | null;
  torso_angle: number | null;
  knee_tracking_ok: boolean;
  pelvis_level: boolean;
  balance_confidence: number | null;
  support_mode: SquatMode;
  bottom_lock: boolean;
  top_lock: boolean;
  /** True once this connection's personal standing-angle baseline has
   * been captured — see `_run_calibration` in single_leg_squat.py. Rep
   * counting doesn't start until this flips true, which normally takes
   * well under a second. */
  calibrated: boolean;
  baseline_angle: number | null;
  top_angle_threshold: number | null;
  bottom_angle_threshold: number | null;
  landmarks: Landmark[];
  /** Which set (of the coach-assigned plan) this connection is for. */
  set_number?: number;
  /** Total sets in the coach-assigned plan. */
  target_sets?: number;
  /**
   * Backend-validated: true only once every set in the plan has hit its
   * target reps. The frontend must treat this as the source of truth for
   * "the user completed this exercise/side" — it must not compute this
   * itself.
   */
  exercise_complete?: boolean;
}

const EMPTY_RESULT: SingleLegSquatData = {
  pose_detected: false,
  ready: false,
  stage: "standing",
  rep_count: 0,
  left_reps: 0,
  right_reps: 0,
  good_reps: 0,
  flawed_reps: 0,
  rep_completed: false,
  rep_classification: null,
  rep_form_quality: null,
  current_side: "left",
  position_ok: false,
  position_message: null,
  framing_ok: true,
  framing_message: null,
  feedback: null,
  target_reps: null,
  session_complete: false,
  low_visibility: false,
  elapsed_time: 0,
  stance_knee_angle: null,
  hip_depth_ratio: null,
  torso_angle: null,
  knee_tracking_ok: true,
  pelvis_level: true,
  balance_confidence: null,
  support_mode: "standard",
  bottom_lock: false,
  top_lock: false,
  calibrated: false,
  baseline_angle: null,
  top_angle_threshold: null,
  bottom_angle_threshold: null,
  landmarks: [],
  set_number: undefined,
  target_sets: undefined,
  exercise_complete: false,
};

const WS_BASE =
  (import.meta.env.VITE_WEBSOCKET_FASTAPI_URL as string | undefined) ||
  `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`;

export default function useSingleLegSquatSocket() {
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [socketError, setSocketError] = useState<string | null>(null);
  const [result, setResult] = useState<SingleLegSquatData>(EMPTY_RESULT);

  const [lastCompletedRep, setLastCompletedRep] = useState({
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
      side?: SquatSide;
      mode?: SquatMode;
    }) => {
      socketRef.current?.close();

      setResult({
        ...EMPTY_RESULT,
        current_side: plan?.side ?? "left",
        support_mode: plan?.mode ?? "standard",
      });
      setLastCompletedRep({
        rep_classification: null,
        rep_form_quality: null,
        feedback: null,
      });
      setSocketError(null);

      // The coach-assigned plan is sent to the backend; the backend — not
      // this hook — decides when a set / side / the whole exercise is done.
      const params = new URLSearchParams();
      if (plan?.targetReps != null)
        params.set("target_reps", String(plan.targetReps));
      if (plan?.targetSets != null)
        params.set("target_sets", String(plan.targetSets));
      if (plan?.setNumber != null)
        params.set("set_number", String(plan.setNumber));
      if (plan?.side != null) params.set("side", plan.side);
      if (plan?.mode != null) params.set("mode", plan.mode);
      const query = params.toString();

      let ws: WebSocket;
      try {
        ws = new WebSocket(
          `${WS_BASE}/ws/single_leg_squat${query ? `?${query}` : ""}`,
        );
      } catch {
        setSocketError("Couldn't reach the detection server. Is it running?");
        return;
      }

      socketRef.current = ws;

      ws.onopen = () => setConnected(true);

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data) as SingleLegSquatData;
        setResult(data);

        if (data.rep_completed) {
          setLastCompletedRep({
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
