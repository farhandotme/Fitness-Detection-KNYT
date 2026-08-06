import React, { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import { Camera, AlertCircle, Loader2, ShieldCheck } from "lucide-react";
import type { PoseLandmark } from "@/hooks/useExerciseSocket";

interface CameraPreviewProps {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  canvasRef: React.RefObject<HTMLCanvasElement | null>;
  permission: "idle" | "pending" | "granted" | "denied" | "error";
  mirror?: boolean;
  className?: string;
  landmarks?: PoseLandmark[];
  landmarksVisible?: boolean;
  poseDetected?: boolean;
  /** Bottom overlay stats */
  children?: React.ReactNode;
}

const POSE_CONNECTIONS: Array<[number, number]> = [
  [0, 1],
  [1, 2],
  [2, 3],
  [3, 4],
  [0, 5],
  [5, 6],
  [6, 7],
  [7, 8],
  [9, 10],
  [5, 11],
  [6, 12],
  [11, 12],
  [11, 13],
  [13, 15],
  [15, 17],
  [15, 19],
  [15, 21],
  [12, 14],
  [14, 16],
  [16, 18],
  [16, 20],
  [11, 23],
  [12, 24],
  [23, 24],
  [23, 25],
  [25, 27],
  [27, 29],
  [27, 31],
  [24, 26],
  [26, 28],
  [28, 30],
  [28, 32],
];

function pointFor(
  landmarks: PoseLandmark[] | undefined,
  index: number,
  content: { left: number; top: number; width: number; height: number },
) {
  const point = landmarks?.[index];
  if (
    !point ||
    !Number.isFinite(point.x) ||
    !Number.isFinite(point.y) ||
    (point.visibility ?? 1) < 0.45
  )
    return null;
  return {
    // The tracking frame is mirrored in useCamera before it is sent to the
    // backend, and the preview is mirrored with CSS. These coordinates already
    // match the displayed preview; mirroring them again makes the skeleton
    // appear on the opposite side of the body.
    x: content.left + Math.min(1, Math.max(0, point.x)) * content.width,
    y: content.top + Math.min(1, Math.max(0, point.y)) * content.height,
  };
}

export function CameraPreview({
  videoRef,
  canvasRef,
  permission,
  mirror = true,
  className,
  landmarks = [],
  landmarksVisible = false,
  poseDetected = false,
}: CameraPreviewProps) {
  const landmarkCanvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = landmarkCanvasRef.current;
    if (!canvas) return;

    const context = canvas.getContext("2d", { alpha: true });
    if (!context) return;

    const bounds = canvas.getBoundingClientRect();
    const width = Math.max(1, Math.round(bounds.width));
    const height = Math.max(1, Math.round(bounds.height));
    // A capped pixel ratio keeps the overlay cheap on high-density displays.
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 1.5);
    canvas.width = Math.round(width * pixelRatio);
    canvas.height = Math.round(height * pixelRatio);
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    context.clearRect(0, 0, width, height);

    if (
      !landmarksVisible ||
      permission !== "granted" ||
      !poseDetected ||
      landmarks.length === 0
    )
      return;

    const video = videoRef.current;
    const videoAspect =
      video?.videoWidth && video?.videoHeight
        ? video.videoWidth / video.videoHeight
        : 16 / 9;
    const containerAspect = width / height;
    const contentWidth =
      containerAspect > videoAspect ? height * videoAspect : width;
    const contentHeight =
      containerAspect > videoAspect ? height : width / videoAspect;
    const content = {
      left: (width - contentWidth) / 2,
      top: (height - contentHeight) / 2,
      width: contentWidth,
      height: contentHeight,
    };

    context.lineCap = "round";
    context.lineJoin = "round";

    for (const [fromIndex, toIndex] of POSE_CONNECTIONS) {
      const from = pointFor(landmarks, fromIndex, content);
      const to = pointFor(landmarks, toIndex, content);
      if (!from || !to) continue;
      // A dark under-stroke keeps the skeleton readable over bright or busy
      // rooms without making the visible lime line thick.
      context.lineWidth = 3.5;
      context.strokeStyle = "rgba(7, 12, 12, 0.8)";
      context.beginPath();
      context.moveTo(from.x, from.y);
      context.lineTo(to.x, to.y);
      context.stroke();
      context.lineWidth = 1.35;
      context.strokeStyle = "rgba(214, 255, 52, 0.98)";
      context.stroke();
    }

    for (let index = 0; index < landmarks.length; index += 1) {
      const point = pointFor(landmarks, index, content);
      if (!point) continue;
      context.fillStyle = "rgba(7, 12, 12, 0.9)";
      context.beginPath();
      context.arc(point.x, point.y, 4.4, 0, Math.PI * 2);
      context.fill();
      context.fillStyle = "rgba(255, 126, 91, 1)";
      context.beginPath();
      context.arc(point.x, point.y, 2.7, 0, Math.PI * 2);
      context.fill();
    }
  }, [
    canvasRef,
    landmarks,
    landmarksVisible,
    permission,
    poseDetected,
    videoRef,
  ]);

  return (
    <div
      className={cn(
        "relative w-full h-full bg-[#11110f] overflow-hidden flex items-center justify-center",
        className,
      )}
    >
      {/* Single video element — always in DOM so the ref stays stable and the stream is always attached */}
      <video
        ref={videoRef}
        className={cn(
          "w-full h-full object-contain transition-opacity duration-300",
          mirror && "scale-x-[-1]",
          permission === "granted" ? "opacity-100" : "opacity-0",
        )}
        playsInline
        muted
        autoPlay
      />

      <canvas
        ref={landmarkCanvasRef}
        className="pointer-events-none absolute inset-0 z-20 h-full w-full"
        aria-label="Live body landmarks"
      />

      {/* Hidden canvas for capturing frames */}
      <canvas ref={canvasRef} className="hidden absolute" />

      {/* Overlay states */}
      {permission === "idle" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-[linear-gradient(145deg,hsl(var(--primary)/.12),hsl(222_43%_6%/.93))] text-center px-8">
          <div className="signal-pulse flex h-16 w-16 items-center justify-center rounded-2xl border border-primary/30 bg-primary/10">
            <Camera className="w-7 h-7 text-primary" />
          </div>
          <div>
            <p className="text-sm font-bold tracking-wide text-slate-100">
              Camera ready when you are
            </p>
            <p className="text-xs text-slate-400 mt-1">
              Your camera starts after the countdown.
            </p>
          </div>
          <div className="mt-2 flex items-center gap-2 text-[10px] font-bold uppercase tracking-[.2em] text-primary/75">
            <ShieldCheck className="h-3.5 w-3.5" /> Private session
          </div>
        </div>
      )}

      {permission === "pending" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-[#071116]/75 text-slate-300 backdrop-blur-sm">
          <div className="relative flex h-20 w-20 items-center justify-center rounded-full border border-primary/35">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <span className="absolute inset-2 rounded-full border border-primary/15" />
          </div>
          <p className="text-xs font-semibold tracking-[.2em] uppercase">
            Locking camera position
          </p>
        </div>
      )}

      {permission === "denied" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-center px-8">
          <AlertCircle className="w-10 h-10 text-destructive" />
          <p className="text-sm font-bold uppercase tracking-wide text-destructive">
            Camera Access Denied
          </p>
          <p className="text-xs text-muted-foreground leading-relaxed">
            Allow camera permissions in your browser settings and refresh.
          </p>
        </div>
      )}

      {permission === "error" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
          <Camera className="w-10 h-10 text-destructive" />
          <p className="text-sm font-bold uppercase tracking-wide text-destructive">
            Camera Unavailable
          </p>
        </div>
      )}

      {/* The live frame intentionally stays clean. Workout feedback lives below it. */}
    </div>
  );
}
