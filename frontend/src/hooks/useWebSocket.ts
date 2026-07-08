import { useEffect, useRef, useState } from "react";

export interface FingerResult {
  hands: any[];
  total_fingers: number;
}

export default function useWebSocket() {
  const socket = useRef<WebSocket | null>(null);

  const [connected, setConnected] = useState(false);

  const [result, setResult] = useState<FingerResult>({
    hands: [],
    total_fingers: 0,
  });

  useEffect(() => {
    socket.current = new WebSocket(
      `${import.meta.env.VITE_WEBSOCKET_FASTAPI_URL}/ws/finger`,
    );

    socket.current.onopen = () => {
      console.log("Connected");
      setConnected(true);
    };

    socket.current.onmessage = (event) => {
      const data = JSON.parse(event.data);

      setResult(data);
    };

    socket.current.onclose = () => {
      console.log("Disconnected");
      setConnected(false);
    };

    return () => {
      socket.current?.close();
    };
  }, []);

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
