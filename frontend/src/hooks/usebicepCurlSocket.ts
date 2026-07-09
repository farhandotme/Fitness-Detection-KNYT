import { useEffect, useRef, useState } from "react";

export interface Landmark {
  x: number;
  y: number;
  z: number;
  visibility?: number;
}

export interface RepResult {
  pose_detected: boolean;

  angle: number | null;
  smoothed_angle: number | null;
  angle_velocity: number | null;

  stage: string;
  rep_count: number;

  rep_completed: boolean;
  rep_duration: number | null;
  rep_avg_speed: number | null;
  rep_classification: string | null;
  feedback: string | null;
  low_visibility: boolean;

  landmarks: Landmark[];
}
export default function useRepWebSocket(exercise: string) {
  const socket = useRef<WebSocket | null>(null);

  const [connected, setConnected] = useState(false);

  const [result, setResult] = useState<RepResult>({
    pose_detected: false,

    angle: null,
    smoothed_angle: null,
    angle_velocity: null,

    stage: "down",
    rep_count: 0,

    rep_completed: false,
    rep_duration: null,
    rep_avg_speed: null,
    rep_classification: null,
    feedback: null,
    low_visibility: false,

    landmarks: [],
  });
  const [lastCompletedRep, setLastCompletedRep] = useState({
    rep_duration: null as number | null,
    rep_avg_speed: null as number | null,
    rep_classification: null as string | null,
    feedback: null as string | null,
  });

  useEffect(() => {
    socket.current = new WebSocket(
      `${import.meta.env.VITE_WEBSOCKET_FASTAPI_URL}/ws/bicep_curl`,
    );

    socket.current.onopen = () => {
      console.log("bicep socket connected");
      setConnected(true);
    };

    socket.current.onmessage = (event) => {
      const data = JSON.parse(event.data);

      setResult(data);

      if (data.rep_completed) {
        setLastCompletedRep({
          rep_duration: data.rep_duration,
          rep_avg_speed: data.rep_avg_speed,
          rep_classification: data.rep_classification,
          feedback: data.feedback,
        });
      }
    };

    socket.current.onclose = () => {
      console.log("bicep socket disconnected");
      setConnected(false);
    };

    return () => {
      socket.current?.close();
    };
  }, [exercise]);

  const sendFrame = (image: string) => {
    if (!socket.current) return;

    if (socket.current.readyState !== WebSocket.OPEN) return;

    socket.current.send(image);
  };

  return {
    connected,
    result,
    lastCompletedRep,
    sendFrame,
  };
}
