import { useState, useRef, useCallback, useEffect } from "react";
import { ExerciseConfig } from "@/config/exercises";

export interface RepData {
  pose_detected: boolean;
  view_mode: "side" | "front" | "angled" | null;
  position_ok: boolean;
  position_message: string | null;
  ready: boolean;
  stage: string;
  rep_count: number;
  good_reps: number;
  flawed_reps: number;
  target_reps: number | null;
  session_complete: boolean;
  rep_completed: boolean;
  rep_duration: number | null;
  rep_avg_speed: number | null;
  rep_classification: string | null;
  rep_form_quality: string | null;
  angle: number | null;
  smoothed_angle: number | null;
  left_elbow_angle: number | null;
  right_elbow_angle: number | null;
  angle_velocity: number | null;
  alignment_ok: boolean;
  alignment_issue: string | null;
  framing_ok: boolean;
  framing_message: string | null;
  feedback: string | null;
  low_visibility: boolean;
  elapsed_time: number;
  landmarks: Array<{ x: number; y: number; z: number; visibility?: number }>;
  set_number?: number;
  target_sets?: number;
  exercise_complete?: boolean;
}

export interface HoldData {
  pose_detected: boolean;
  hold_state: "not_started" | "holding" | "broken";
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
  form_score: number | null;
  avg_form_score: number | null;
  active_side?: "left" | "right" | null;
  alignment_angle?: number | null;
  knee_angle?: number | null;
  framing_ok: boolean;
  framing_message: string | null;
  feedback: string | null;
  low_visibility: boolean;
  elapsed_time: number;
  landmarks: Array<{ x: number; y: number; z: number; visibility?: number }>;
  set_number?: number;
  target_sets?: number;
  exercise_complete?: boolean;
}

export function useExerciseSocket(exercise: ExerciseConfig) {
  const [connected, setConnected] = useState(false);
  const [socketError, setSocketError] = useState<string | null>(null);
  const [data, setData] = useState<RepData | HoldData | null>(null);
  const [lastRep, setLastRep] = useState<{
    rep_form_quality: string | null;
    rep_classification: string | null;
    rep_duration: number | null;
    feedback: string | null;
  } | null>(null);

  const socketRef = useRef<WebSocket | null>(null);

  const start = useCallback(
    (params: {
      targetReps?: number;
      targetSeconds?: number;
      targetSets?: number;
      setNumber?: number;
    }) => {
      // Determine base WS URL
      let wsBase = import.meta.env.VITE_WS_BASE;
      if (!wsBase) {
        const saved = localStorage.getItem("WS_BASE_OVERRIDE");
        if (saved) {
          wsBase = saved;
        } else {
          const protocol = window.location.protocol === "https:" ? "wss" : "ws";
          // if running in a container, often localhost doesn't work from the host, but we will default to it
          wsBase = `${protocol}://localhost:8000`;
        }
      }

      // Build URL
      const searchParams = new URLSearchParams();
      if (params.targetSets)
        searchParams.set("target_sets", params.targetSets.toString());
      if (params.setNumber)
        searchParams.set("set_number", params.setNumber.toString());

      if (exercise.mode === "reps" && params.targetReps) {
        searchParams.set("target_reps", params.targetReps.toString());
      } else if (exercise.mode === "hold" && params.targetSeconds) {
        searchParams.set("target_seconds", params.targetSeconds.toString());
      }

      const wsUrl = `${wsBase}${exercise.wsRoute}?${searchParams.toString()}`;
      console.log("Connecting to WS:", wsUrl);

      try {
        const ws = new WebSocket(wsUrl);
        socketRef.current = ws;

        ws.onopen = () => {
          console.log("WebSocket connected.");
          setConnected(true);
          setSocketError(null);
        };

        ws.onmessage = (event) => {
          try {
            const parsed = JSON.parse(event.data);
            setData(parsed);

            if (exercise.mode === "reps" && parsed.rep_completed) {
              setLastRep({
                rep_form_quality: parsed.rep_form_quality,
                rep_classification: parsed.rep_classification,
                rep_duration: parsed.rep_duration,
                feedback: parsed.feedback,
              });
            }
          } catch (e) {
            console.error("Failed to parse socket message", e);
          }
        };

        ws.onerror = (error) => {
          console.error("WebSocket error:", error);
          setSocketError("Connection error.");
        };

        ws.onclose = () => {
          console.log("WebSocket closed.");
          setConnected(false);
        };
      } catch (e: any) {
        setSocketError(e.message || "Failed to establish connection.");
      }
    },
    [exercise.mode, exercise.wsRoute],
  );

  const stop = useCallback(() => {
    if (socketRef.current) {
      socketRef.current.close();
      socketRef.current = null;
    }
    setConnected(false);
  }, []);

  const sendFrame = useCallback((base64: string) => {
    if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
      socketRef.current.send(base64);
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stop();
    };
  }, [stop]);

  return {
    connected,
    socketError,
    data,
    lastRep,
    start,
    stop,
    sendFrame,
  };
}
