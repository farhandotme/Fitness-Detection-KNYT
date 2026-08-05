import { useRef, useState, useCallback, useEffect } from "react";

export function useCamera(mirror = true) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [permission, setPermission] = useState<
    "idle" | "pending" | "granted" | "denied" | "error"
  >("idle");
  const [error, setError] = useState<string | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const startCamera = useCallback(async () => {
    if (streamRef.current) return true;
    setPermission("pending");
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: "user",
          width: { ideal: 1280 },
          height: { ideal: 720 },
          aspectRatio: { ideal: 16 / 9 },
        },
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
        setPermission("granted");
        return true;
      }
      stream.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      return false;
    } catch (err: any) {
      console.error("Error starting camera", err);
      if (err.name === "NotAllowedError") {
        setPermission("denied");
        setError("Camera access denied.");
      } else {
        setPermission("error");
        setError(err.message || "Could not start camera.");
      }
      return false;
    }
  }, []);

  const stopCamera = useCallback(() => {
    const stream =
      streamRef.current || (videoRef.current?.srcObject as MediaStream | null);
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.pause();
      videoRef.current.srcObject = null;
    }
    setPermission("idle");
  }, []);

  const captureFrame = useCallback((): string | null => {
    if (!videoRef.current || !canvasRef.current) return null;
    if (videoRef.current.readyState !== videoRef.current.HAVE_ENOUGH_DATA)
      return null;

    const video = videoRef.current;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;

    if (mirror) {
      ctx.translate(canvas.width, 0);
      ctx.scale(-1, 1);
    }

    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    // Return base64 jpeg
    return canvas.toDataURL("image/jpeg", 0.6);
  }, [mirror]);

  // Stop camera on unmount
  useEffect(() => {
    return () => stopCamera();
  }, [stopCamera]);

  return {
    videoRef,
    canvasRef,
    permission,
    error,
    startCamera,
    stopCamera,
    captureFrame,
  };
}
