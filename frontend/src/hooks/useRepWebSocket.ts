import { useEffect, useRef, useState } from "react";

export interface RepResult {
  pose_detected: boolean;
  angle: number | null;
  stage: string;
  rep_count: number;
  rep_completed: boolean;
  landmarks: any[];
}

export default function useRepWebSocket(exercise: string) {
  const socket = useRef<WebSocket | null>(null);

  const [connected, setConnected] = useState(false);

  const [result, setResult] = useState<RepResult>({
    pose_detected: false,
    angle: null,
    stage: "down",
    rep_count: 0,
    rep_completed: false,
    landmarks: [],
  });

  useEffect(() => {
    socket.current = new WebSocket(
      `${import.meta.env.VITE_WEBSOCKET_FASTAPI_URL}/ws/rep?exercise=${exercise}`,
    );

    socket.current.onopen = () => {
      console.log("Rep socket connected");
      setConnected(true);
    };

    socket.current.onmessage = (event) => {
      const data = JSON.parse(event.data);

      setResult(data);
    };

    socket.current.onclose = () => {
      console.log("Rep socket disconnected");
      setConnected(false);
    };

    return () => {
      socket.current?.close();
    };
  }, [exercise]); // reconnects whenever exercise changes — backend spins up a fresh RepCounter per connection

  const sendFrame = (image: string) => {
    if (!socket.current) return;

    if (socket.current.readyState !== WebSocket.OPEN) return;

    socket.current.send(image);
  };

  return {
    connected,
    result,
    sendFrame,
  };
}
