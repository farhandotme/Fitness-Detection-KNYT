import { useEffect, useRef, useState } from "react";

interface Props {
  /** Camera turns on as soon as this is true. */
  active: boolean;
  /** Set to true to start the countdown -> capture sequence. */
  scanning: boolean;
  countdownSeconds?: number;
  onCapture: (dataUrl: string) => void;
  onError?: (message: string) => void;
}

/**
 * Single-shot capture camera for the body scan.
 *
 * Unlike BicepCamera/SquatCamera (which stream ~30fps to a websocket for
 * continuous rep detection), this component only needs ONE good frame:
 * it shows a live preview + a full-body framing guide, counts down, then
 * grabs a single high-resolution frame and hands it to the parent.
 */
export default function BodyScanCamera({
  active,
  scanning,
  countdownSeconds = 5,
  onCapture,
  onError,
}: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const onCaptureRef = useRef(onCapture);
  onCaptureRef.current = onCapture;

  const [countdown, setCountdown] = useState<number | null>(null);

  // --- camera lifecycle ---
  useEffect(() => {
    if (!active) {
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      if (videoRef.current) videoRef.current.srcObject = null;
      return;
    }

    let cancelled = false;

    async function startCamera() {
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: "user",
            width: { ideal: 1280 },
            height: { ideal: 960 },
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
        stream.getTracks().forEach((t) => t.stop());
        return;
      }

      streamRef.current = stream;
      if (videoRef.current) videoRef.current.srcObject = stream;
    }

    startCamera();

    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    };
  }, [active, onError]);

  // --- countdown -> capture ---
  useEffect(() => {
    if (!scanning) {
      setCountdown(null);
      return;
    }

    let remaining = countdownSeconds;
    setCountdown(remaining);

    const interval = window.setInterval(() => {
      remaining -= 1;
      if (remaining <= 0) {
        clearInterval(interval);
        setCountdown(null);
        capture();
      } else {
        setCountdown(remaining);
      }
    }, 1000);

    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scanning, countdownSeconds]);

  function capture() {
    if (!videoRef.current || !canvasRef.current) return;
    const video = videoRef.current;
    const canvas = canvasRef.current;

    if (video.videoWidth === 0) {
      onError?.("Camera isn't ready yet — try again in a moment.");
      return;
    }

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.drawImage(video, 0, 0);
    const dataUrl = canvas.toDataURL("image/jpeg", 0.92);
    onCaptureRef.current(dataUrl);
  }

  return (
    <div className="scan-viewfinder">
      {active ? (
        <>
          <video ref={videoRef} autoPlay muted playsInline className="scan-viewfinder-video" />

          {/* Full-body framing guide */}
          <svg className="scan-guide" viewBox="0 0 200 300" preserveAspectRatio="none">
            <ellipse cx="100" cy="35" rx="18" ry="22" />
            <line x1="100" y1="57" x2="100" y2="180" />
            <line x1="100" y1="75" x2="55" y2="130" />
            <line x1="100" y1="75" x2="145" y2="130" />
            <line x1="100" y1="180" x2="65" y2="280" />
            <line x1="100" y1="180" x2="135" y2="280" />
          </svg>

          {countdown !== null && (
            <div className="scan-countdown">
              <span>{countdown}</span>
            </div>
          )}

          <canvas ref={canvasRef} style={{ display: "none" }} />
        </>
      ) : (
        <div className="scan-viewfinder-placeholder">
          <span>📷</span>
          <p>Camera turns on when you start the scan</p>
        </div>
      )}
    </div>
  );
}
