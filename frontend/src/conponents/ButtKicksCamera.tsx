import { useEffect, useRef } from "react";
import type { Landmark } from "../hooks/useButtKicksSocket";

interface SkeletonEntity {
  points: Landmark[];
  connections?: [number, number][];
}

interface Props {
  /** Camera only turns on while this is true. */
  active: boolean;
  sendFrame: (image: string) => void;
  skeleton?: SkeletonEntity[];
  onError?: (message: string) => void;
}

/**
 * Butt kicks are filmed standing, ideally with the full lower body (both
 * knees, both ankles) and at least part of the torso in frame — a portrait
 * -leaning box works better here than the push-up camera's landscape bias.
 * Captures at a slightly higher rate than the other exercises since this
 * is a fast cardio drill and the analyzer favors more, closer-spaced
 * samples over risking a missed kick between frames.
 */
export default function ButtKicksCamera({
  active,
  sendFrame,
  skeleton,
  onError,
}: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null); // hidden — captures frames to send
  const overlayRef = useRef<HTMLCanvasElement>(null); // visible — skeleton drawing
  const streamRef = useRef<MediaStream | null>(null);
  const sendFrameRef = useRef(sendFrame);
  sendFrameRef.current = sendFrame;

  useEffect(() => {
    if (!active) {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      if (videoRef.current) videoRef.current.srcObject = null;
      return;
    }

    let cancelled = false;
    let interval: number;

    async function startCamera() {
      if (!navigator.mediaDevices?.getUserMedia) {
        onError?.(
          window.isSecureContext
            ? "This browser doesn't support camera access."
            : "Camera access requires HTTPS. Open this page over https:// (not http://) — plain http only works on localhost.",
        );
        return;
      }
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: "user",
            width: { ideal: 720 },
            height: { ideal: 960 }, // portrait-leaning — full standing body
            aspectRatio: { ideal: 3 / 4 },
          },
          audio: false,
        });
      } catch {
        try {
          stream = await navigator.mediaDevices.getUserMedia({ video: true });
        } catch (err) {
          onError?.(
            err instanceof DOMException && err.name === "NotAllowedError"
              ? "Camera permission was denied. Allow camera access and try again."
              : "Couldn't access a camera on this device.",
          );
          return;
        }
      }

      if (cancelled) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }

      streamRef.current = stream;
      if (videoRef.current) videoRef.current.srcObject = stream;

      // Slightly faster than the 30fps used elsewhere — this is a fast,
      // rhythmic drill and the analyzer is built to tolerate the extra
      // frames rather than to need fewer of them.
      interval = window.setInterval(captureFrame, 25); // ~40 FPS
    }

    startCamera();

    return () => {
      cancelled = true;
      if (interval) clearInterval(interval);
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  useEffect(() => {
    drawOverlay();
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

    sendFrameRef.current(image);
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

      ctx.strokeStyle = "rgba(184, 134, 46, 0.9)";
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
    <div className="bk-viewfinder">
      {active ? (
        <>
          <video
            ref={videoRef}
            autoPlay
            muted
            playsInline
            className="bk-viewfinder-video"
          />
          <canvas ref={overlayRef} className="bk-viewfinder-overlay" />
          <canvas ref={canvasRef} style={{ display: "none" }} />
        </>
      ) : (
        <div className="bk-viewfinder-placeholder">
          <span>🏃‍♂️</span>
          <p>
            Camera turns on when you hit Start — stand tall, full body in frame,
            and start kicking
          </p>
        </div>
      )}
    </div>
  );
}
