import { useCallback, useEffect, useRef, useState } from "react";
import type { Landmark } from "./useSquatSocket";

export type { Landmark };

interface SpeedAnalysis {
  duration: number | null;
  classification: string | null;
  reps_per_minute: number | null;
}

/** Everything the FastAPI `JumpingJackAnalyzer` sends per frame. */
export interface JumpingJackData {
  pose_detected: boolean;
  openness: number | null;
  smoothed_openness: number | null;
  arm_angle_left: number | null;
  arm_angle_right: number | null;
  elbow_angle_left: number | null;
  elbow_angle_right: number | null;
  leg_spread_ratio: number | null;
  openness_velocity: number | null;
  stage: "closed" | "open" | string;
  phase: "start" | "open" | "close" | "rep_complete" | string;
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
  calibrated: boolean;
  posture_ok: boolean;
  posture_issues: string[];
  posture_messages: string[];
  framing_ok: boolean;
  framing_message: string | null;
  form_score: number | null;
  avg_form_score: number | null;
  rom_score: number | null;
  avg_rom_score: number | null;
  stability_score: number | null;
  avg_stability_score: number | null;
  sync_score: number | null;
  avg_sync_score: number | null;
  speed_analysis: SpeedAnalysis;
  fps: number | null;
  feedback: string | null;
  low_visibility: boolean;
  elapsed_time: number;
  landmarks: Landmark[];
}

const EMPTY_RESULT: JumpingJackData = {
  pose_detected: false,
  openness: null,
  smoothed_openness: null,
  arm_angle_left: null,
  arm_angle_right: null,
  elbow_angle_left: null,
  elbow_angle_right: null,
  leg_spread_ratio: null,
  openness_velocity: null,
  stage: "closed",
  phase: "start",
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
  calibrated: false,
  posture_ok: true,
  posture_issues: [],
  posture_messages: [],
  framing_ok: true,
  framing_message: null,
  form_score: null,
  avg_form_score: null,
  rom_score: null,
  avg_rom_score: null,
  stability_score: null,
  avg_stability_score: null,
  sync_score: null,
  avg_sync_score: null,
  speed_analysis: {
    duration: null,
    classification: null,
    reps_per_minute: null,
  },
  fps: null,
  feedback: null,
  low_visibility: false,
  elapsed_time: 0,
  landmarks: [],
};

const WS_BASE =
  (import.meta.env.VITE_WEBSOCKET_FASTAPI_URL as string | undefined) ||
  `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`;

export default function useJumpingJackSocket() {
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [socketError, setSocketError] = useState<string | null>(null);
  const [result, setResult] = useState<JumpingJackData>(EMPTY_RESULT);

  const [lastCompletedRep, setLastCompletedRep] = useState({
    rep_duration: null as number | null,
    rep_avg_speed: null as number | null,
    rep_classification: null as string | null,
    rep_form_quality: null as string | null,
    form_score: null as number | null,
    rom_score: null as number | null,
    stability_score: null as number | null,
    sync_score: null as number | null,
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

  const start = useCallback(() => {
    socketRef.current?.close();

    setResult(EMPTY_RESULT);
    setLastCompletedRep({
      rep_duration: null,
      rep_avg_speed: null,
      rep_classification: null,
      rep_form_quality: null,
      form_score: null,
      rom_score: null,
      stability_score: null,
      sync_score: null,
      feedback: null,
    });
    setSocketError(null);

    let ws: WebSocket;
    try {
      ws = new WebSocket(`${WS_BASE}/ws/jumping-jack`);
    } catch {
      setSocketError("Couldn't reach the detection server. Is it running?");
      return;
    }

    socketRef.current = ws;

    ws.onopen = () => setConnected(true);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data) as JumpingJackData;
      setResult(data);

      if (data.rep_completed) {
        setLastCompletedRep({
          rep_duration: data.rep_duration,
          rep_avg_speed: data.rep_avg_speed,
          rep_classification: data.rep_classification,
          rep_form_quality: data.rep_form_quality,
          form_score: data.form_score,
          rom_score: data.rom_score,
          stability_score: data.stability_score,
          sync_score: data.sync_score,
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
  }, []);

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
