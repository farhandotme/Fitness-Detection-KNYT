import { useEffect, useRef } from "react";

interface SkeletonEntity {
  points: { x: number; y: number }[];
  connections?: [number, number][];
}

interface Props {
  deviceId: string;
  sendFrame: (image: string) => void;
  skeleton?: SkeletonEntity[];
}

export default function VideoPreview({ deviceId, sendFrame, skeleton }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null); // hidden — used only to capture frames to send
  const overlayRef = useRef<HTMLCanvasElement>(null); // visible — skeleton drawing

  useEffect(() => {
    if (!deviceId) return;

    let stream: MediaStream;
    let interval: number;

    async function startCamera() {
      stream = await navigator.mediaDevices.getUserMedia({
        video: {
          deviceId: {
            exact: deviceId,
          },
          width: 640,
          height: 480,
        },
      });

      if (videoRef.current) {
        videoRef.current.srcObject = stream;
      }

      interval = window.setInterval(() => {
        captureFrame();
      }, 33); // ~30 FPS
    }

    startCamera();

    return () => {
      if (interval) clearInterval(interval);

      if (stream) {
        stream.getTracks().forEach((track) => track.stop());
      }
    };
  }, [deviceId]);

  useEffect(() => {
    drawOverlay();
  }, [skeleton]);

  function captureFrame() {
    if (!videoRef.current || !canvasRef.current) return;

    const video = videoRef.current;
    const canvas = canvasRef.current;

    if (video.videoWidth === 0) return;

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;

    const ctx = canvas.getContext("2d");

    if (!ctx) return;

    ctx.drawImage(video, 0, 0);

    const image = canvas.toDataURL("image/jpeg", 0.8);

    sendFrame(image);
  }

  function drawOverlay() {
    if (!overlayRef.current || !videoRef.current) return;

    const video = videoRef.current;
    const canvas = overlayRef.current;

    if (video.videoWidth === 0) return;

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;

    const ctx = canvas.getContext("2d");

    if (!ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (!skeleton || skeleton.length === 0) return;

    skeleton.forEach((entity) => {
      const { points, connections } = entity;

      ctx.strokeStyle = "rgba(132, 199, 96, 0.9)";
      ctx.lineWidth = 3;

      if (connections) {
        connections.forEach(([a, b]) => {
          const pa = points[a];
          const pb = points[b];

          if (!pa || !pb) return;

          ctx.beginPath();
          ctx.moveTo(pa.x * canvas.width, pa.y * canvas.height);
          ctx.lineTo(pb.x * canvas.width, pb.y * canvas.height);
          ctx.stroke();
        });
      }

      ctx.fillStyle = "#F2EFE4";

      points.forEach((p) => {
        ctx.beginPath();
        ctx.arc(p.x * canvas.width, p.y * canvas.height, 3, 0, Math.PI * 2);
        ctx.fill();
      });
    });
  }

  return (
    <div className="viewfinder">
      <video
        ref={videoRef}
        autoPlay
        muted
        playsInline
        className="viewfinder-video"
      />

      <canvas ref={overlayRef} className="viewfinder-overlay" />

      <canvas ref={canvasRef} style={{ display: "none" }} />
    </div>
  );
}
