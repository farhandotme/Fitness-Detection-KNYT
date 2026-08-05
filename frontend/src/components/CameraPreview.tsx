import React from "react";
import { cn } from "@/lib/utils";
import {
  Camera,
  AlertCircle,
  Loader2,
  ScanLine,
  ShieldCheck,
} from "lucide-react";

interface CameraPreviewProps {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  canvasRef: React.RefObject<HTMLCanvasElement | null>;
  permission: "idle" | "pending" | "granted" | "denied" | "error";
  mirror?: boolean;
  className?: string;
  /** Bottom overlay stats */
  children?: React.ReactNode;
}

export function CameraPreview({
  videoRef,
  canvasRef,
  permission,
  mirror = true,
  className,
  children,
}: CameraPreviewProps) {
  return (
    <div
      className={cn(
        "relative w-full h-full bg-[#071116] overflow-hidden flex items-center justify-center",
        className,
      )}
    >
      <div className="pointer-events-none absolute inset-0 camera-grid opacity-70" />
      <div className="pointer-events-none absolute -left-24 -top-20 h-72 w-72 rounded-full bg-primary/10 blur-3xl ambient-pulse" />
      <div className="pointer-events-none absolute -bottom-24 -right-16 h-80 w-80 rounded-full bg-accent/10 blur-3xl ambient-pulse" />

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

      {/* Hidden canvas for capturing frames */}
      <canvas ref={canvasRef} className="hidden absolute" />

      {/* Overlay states */}
      {permission === "idle" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-[linear-gradient(145deg,hsl(var(--primary)/.13),hsl(222_43%_6%/.93))] text-center px-8">
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

      {/* HUD corner brackets */}
      {permission === "granted" && (
        <>
          <div className="pointer-events-none absolute inset-x-0 top-[18%] h-px bg-linear-to-r from-transparent via-primary/70 to-transparent camera-scan-line" />
          <div className="pointer-events-none absolute left-1/2 top-1/2 h-44 w-44 -translate-x-1/2 -translate-y-1/2 rounded-full border border-primary/20 signal-pulse" />
          <div className="absolute left-4 top-4 flex items-center gap-2 rounded-full border border-primary/25 bg-[#071116]/75 px-3 py-1.5 text-[10px] font-bold uppercase tracking-[.18em] text-primary backdrop-blur-md">
            <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
            Form lock active
          </div>
          <div className="absolute right-4 top-4 flex items-center gap-1.5 rounded-full border border-white/10 bg-black/35 px-2.5 py-1.5 text-[10px] font-mono text-white/60 backdrop-blur-md">
            <ScanLine className="h-3 w-3 text-accent" /> 8 FPS
          </div>
          <div className="absolute top-3 left-3 w-7 h-7 border-t-2 border-l-2 border-primary/60 pointer-events-none" />
          <div className="absolute top-3 right-3 w-7 h-7 border-t-2 border-r-2 border-primary/60 pointer-events-none" />
          <div className="absolute bottom-3 left-3 w-7 h-7 border-b-2 border-l-2 border-primary/60 pointer-events-none" />
          <div className="absolute bottom-3 right-3 w-7 h-7 border-b-2 border-r-2 border-primary/60 pointer-events-none" />
        </>
      )}

      {/* Gradient + bottom stats slot */}
      {children && (
        <div className="absolute bottom-0 left-0 right-0 bg-linear-to-t from-black/90 via-black/40 to-transparent pt-12 pb-3 px-3 pointer-events-none">
          {children}
        </div>
      )}
    </div>
  );
}
