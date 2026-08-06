import React, { useEffect, useState, useRef, useCallback } from "react";
import { useRoute, useLocation, useSearch } from "wouter";
import { getExerciseById } from "@/config/exercises";
import { useCamera } from "@/hooks/useCamera";
import { useExerciseSocket } from "@/hooks/useExerciseSocket";
import { CameraPreview } from "@/components/CameraPreview";
import { RepPanel } from "@/components/RepPanel";
import { HoldPanel } from "@/components/HoldPanel";
import { formatTime } from "@/utils/formatTime";
import {
  X,
  Play,
  Pause,
  CheckCircle2,
  Activity,
  Camera,
  ShieldCheck,
  Eye,
  EyeOff,
  Gauge,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { motion, AnimatePresence } from "framer-motion";
export function SessionPage() {
  const [match, params] = useRoute("/exercise/:id/session");
  const [, setLocation] = useLocation();
  const searchString = useSearch();
  const searchParams = new URLSearchParams(searchString);

  const targetStr = searchParams.get("target");
  const setsStr = searchParams.get("sets");
  const restStr = searchParams.get("rest");

  const id = params?.id;
  const exercise = id ? getExerciseById(id) : undefined;
  const defaultExercise = exercise || getExerciseById("pushup")!;

  const target = targetStr
    ? parseInt(targetStr)
    : exercise?.defaultTarget || 10;
  const targetSets = setsStr ? parseInt(setsStr) : exercise?.defaultSets || 3;
  const restSeconds = restStr
    ? parseInt(restStr)
    : exercise?.defaultRestSeconds || 45;

  const [currentSet, setCurrentSet] = useState(1);
  const [isResting, setIsResting] = useState(false);
  const [restTimeLeft, setRestTimeLeft] = useState(0);
  const [isSessionComplete, setIsSessionComplete] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [countdown, setCountdown] = useState<number | null>(3);
  const [sessionStarted, setSessionStarted] = useState(false);
  const [landmarksVisible, setLandmarksVisible] = useState(false);

  const {
    videoRef,
    canvasRef,
    permission,
    startCamera,
    stopCamera,
    captureFrame,
  } = useCamera(defaultExercise.cameraMirror ?? true);
  const { connected, socketError, data, lastRep, start, stop, sendFrame } =
    useExerciseSocket(defaultExercise);

  // Use refs for values that need to be read inside intervals without stale closures
  const isPausedRef = useRef(isPaused);
  const isRestingRef = useRef(isResting);
  isPausedRef.current = isPaused;
  isRestingRef.current = isResting;

  const frameIntervalRef = useRef<number | null>(null);

  const startSendingFrames = useCallback(() => {
    if (frameIntervalRef.current) return;
    frameIntervalRef.current = window.setInterval(() => {
      if (!isPausedRef.current && !isRestingRef.current) {
        const frame = captureFrame();
        if (frame) sendFrame(frame);
      }
    }, 120); // ~8fps, comfortable for mediapipe
  }, [captureFrame, sendFrame]);

  const stopSendingFrames = useCallback(() => {
    if (frameIntervalRef.current) {
      window.clearInterval(frameIntervalRef.current);
      frameIntervalRef.current = null;
    }
  }, []);

  // The page owns teardown, but intentionally does not start hardware on mount.
  useEffect(() => {
    return () => {
      stop();
      stopSendingFrames();
      stopCamera();
    };
  }, [stop, stopCamera, stopSendingFrames]);

  useEffect(() => {
    if (!sessionStarted || countdown === null) return;
    if (countdown === 0) {
      let cancelled = false;
      startCamera().then((ready) => {
        if (cancelled || !ready) return;
        start({
          targetSets,
          setNumber: 1,
          ...(defaultExercise.mode === "reps"
            ? { targetReps: target }
            : { targetSeconds: target }),
        });
      });
      return () => {
        cancelled = true;
      };
    }
    const timer = window.setTimeout(
      () => setCountdown((value) => (value === null ? null : value - 1)),
      900,
    );
    return () => window.clearTimeout(timer);
  }, [
    sessionStarted,
    countdown,
    startCamera,
    start,
    targetSets,
    target,
    defaultExercise.mode,
  ]);

  // Send frames when connected + camera ready
  useEffect(() => {
    if (connected && permission === "granted") {
      startSendingFrames();
    } else {
      stopSendingFrames();
    }
    return stopSendingFrames;
  }, [connected, permission, startSendingFrames, stopSendingFrames]);

  // Handle set/exercise completion from server
  useEffect(() => {
    if (!data) return;
    if (data.exercise_complete) {
      setIsSessionComplete(true);
      stop();
      stopCamera();
      stopSendingFrames();
      return;
    }
    if (data.session_complete && !isRestingRef.current) {
      stop();
      stopSendingFrames();
      setIsResting(true);
      setRestTimeLeft(restSeconds);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.session_complete, data?.exercise_complete, stopCamera]);

  // Rest countdown
  useEffect(() => {
    if (!isResting || restTimeLeft <= 0) return;
    const timer = setInterval(() => {
      setRestTimeLeft((prev) => {
        if (prev <= 1) {
          setIsResting(false);
          const nextSet = currentSet + 1;
          setCurrentSet(nextSet);
          start({
            targetSets,
            setNumber: nextSet,
            ...(defaultExercise.mode === "reps"
              ? { targetReps: target }
              : { targetSeconds: target }),
          });
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isResting]);

  const handleQuit = () => {
    stop();
    stopCamera();
    stopSendingFrames();
    setLocation(`/exercise/${defaultExercise.id}`);
  };

  const finishToHome = () => {
    stop();
    stopCamera();
    stopSendingFrames();
    setLocation("/");
  };

  const togglePause = () => setIsPaused((p) => !p);

  const beginSession = () => {
    setSessionStarted(true);
    setCountdown(3);
  };

  if (!match || !exercise) {
    return (
      <div className="p-8 text-center text-red-400">Session not found.</div>
    );
  }

  // ── Completion Screen ────────────────────────────────────────────────────────
  if (isSessionComplete) {
    return (
      <div className="min-h-dvh bg-[#11110f] text-foreground flex items-center justify-center p-6">
        <motion.div
          initial={{ scale: 0.9, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          className="bg-[#0d1820] border border-primary/15 p-10 rounded-4xl text-center max-w-sm w-full shadow-2xl shadow-black/30"
        >
          <div className="w-20 h-20 bg-primary/10 rounded-full flex items-center justify-center mx-auto mb-6">
            <CheckCircle2 className="w-10 h-10 text-primary" />
          </div>
          <h1 className="text-3xl font-black uppercase tracking-tight mb-2 text-foreground">
            Workout Complete
          </h1>
          <p className="text-muted-foreground mb-2 text-sm">
            {targetSets} sets of {exercise.name} done.
          </p>
          {data && "rep_count" in data && (
            <p className="text-primary font-bold text-lg font-mono mb-6">
              {(data as any).good_reps} / {(data as any).rep_count} good reps
            </p>
          )}
          <button
            onClick={finishToHome}
            data-testid="button-back-dashboard"
            className="w-full bg-primary text-primary-foreground py-3.5 rounded-xl font-black uppercase tracking-wider hover:brightness-110 transition-all"
          >
            Back to Dashboard
          </button>
        </motion.div>
      </div>
    );
  }

  // ── Live Session ─────────────────────────────────────────────────────────────
  const repData = data && exercise.mode === "reps" ? (data as any) : null;
  const holdData = data && exercise.mode === "hold" ? (data as any) : null;
  // The uploaded backend owns detection and visibility decisions. The
  // frontend only guards against malformed coordinates before drawing.
  // The uploaded backend owns pose detection and framing decisions. The
  // frontend only renders the landmarks it returns.
  const poseDetected = Boolean(data?.pose_detected);
  const poseLandmarks = poseDetected ? (data?.landmarks ?? []) : [];
  const panelData =
    data && !poseDetected
      ? { ...data, pose_detected: false, landmarks: [] }
      : data;
  const visibleLandmarkCount = landmarksVisible
    ? poseLandmarks.filter((point) => (point.visibility ?? 1) >= 0.3).length
    : 0;
  const averageVisibility =
    poseLandmarks.length > 0
      ? Math.round(
          (poseLandmarks.reduce(
            (sum, point) => sum + (point.visibility ?? 1),
            0,
          ) /
            poseLandmarks.length) *
            100,
        )
      : null;
  const poseStatus = !data
    ? "Waiting"
    : poseDetected
      ? "Detected"
      : "Not found";
  const frameStatus = !data
    ? "Waiting"
    : data.framing_ok
      ? "Good"
      : "Adjust view";
  const movementStage = poseDetected
    ? repData?.stage || holdData?.hold_state?.replace(/_/g, " ") || "Waiting"
    : "Waiting";

  return (
    <div className="min-h-dvh max-h-dvh bg-[#11110f] text-foreground flex flex-col overflow-hidden">
      {/* ── Top Bar ─────────────────────────────────────────────────── */}
      <header className="flex items-center gap-3 px-4 py-3 border-b border-white/10 shrink-0 bg-[#171714]/95 backdrop-blur-xl">
        <button
          onClick={handleQuit}
          className="flex items-center gap-1.5 text-slate-400 hover:text-white text-xs font-bold tracking-widest uppercase transition-colors"
        >
          <X className="w-4 h-4" />
          Exit
        </button>

        <div className="h-4 w-px bg-white/10" />

        <h1 className="text-sm font-black uppercase tracking-widest text-foreground flex-1">
          {exercise.name}
        </h1>

        {/* Set counter */}
        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-500">Set</span>
          <span className="font-black text-white font-mono">
            {Math.min(currentSet, targetSets)}/{targetSets}
          </span>
          <span className="mx-1 text-white/20">·</span>
          {repData && (
            <span className="font-mono text-slate-500">
              {repData.rep_count}/{target} reps
            </span>
          )}
          {holdData && (
            <span className="font-mono text-slate-500">
              {formatTime(holdData.hold_seconds)}/{formatTime(target)}
            </span>
          )}
        </div>

        <button
          onClick={handleQuit}
          data-testid="button-end-session"
          className="bg-red-500/10 border border-red-500/30 text-red-400 text-xs font-bold uppercase tracking-widest px-3 py-1.5 rounded-lg hover:bg-red-500/20 transition-colors"
        >
          End Session
        </button>
      </header>

      {/* ── Set Progress Bar ─────────────────────────────────────────── */}
      <div className="flex gap-1 px-4 py-2 shrink-0 border-b border-white/10 bg-[#171714]">
        {Array.from({ length: targetSets }, (_, i) => i + 1).map((s) => (
          <div
            key={s}
            className={cn(
              "flex-1 h-1 rounded-full transition-all duration-500",
              s < currentSet
                ? "bg-primary"
                : s === currentSet
                  ? "bg-primary/45 animate-pulse"
                  : "bg-white/10",
            )}
          />
        ))}
      </div>

      {/* ── Main Body ───────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col lg:flex-row overflow-hidden min-h-0">
        {/* LEFT: Camera */}
        <div className="w-full lg:w-[56%] flex flex-col min-h-0 overflow-y-auto bg-[#11110f] p-3 gap-3">
          <div className="relative w-full aspect-video shrink-0 overflow-hidden rounded-[1.35rem] border border-white/10 bg-[#11110f] shadow-2xl shadow-black/30">
            <CameraPreview
              videoRef={videoRef}
              canvasRef={canvasRef}
              permission={permission}
              mirror={exercise.cameraMirror}
              landmarks={poseLandmarks}
              landmarksVisible={landmarksVisible}
              poseDetected={poseDetected}
              className="rounded-[1.35rem]"
            />

            <AnimatePresence>
              {countdown !== null && sessionStarted && countdown > 0 && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="absolute inset-0 z-40 flex flex-col items-center justify-center bg-[#171714]/96 text-[#f2f5ed]"
                >
                  <p className="relative z-10 text-xs font-bold uppercase tracking-[.28em] text-accent mb-5">
                    Get into position
                  </p>
                  <motion.div
                    key={countdown}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -8 }}
                    transition={{ duration: 0.25, ease: "easeOut" }}
                    className="relative z-10 h-[clamp(8rem,18vw,12rem)] w-[clamp(8rem,18vw,12rem)] text-center font-display text-[clamp(8rem,18vw,12rem)] leading-[.9] font-extrabold tabular-nums text-primary drop-shadow-[0_0_32px_hsl(var(--primary)/.35)]"
                  >
                    {countdown}
                  </motion.div>
                  <p className="relative z-10 text-sm text-slate-300 mt-3">
                    Camera begins after the countdown
                  </p>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Rest Overlay */}
            <AnimatePresence>
              {isResting && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="absolute inset-0 bg-[#11110f]/95 backdrop-blur-sm flex flex-col items-center justify-center z-30"
                >
                  <p className="text-[10px] font-bold tracking-widest uppercase text-slate-500 mb-3">
                    Rest
                  </p>
                  <div className="text-8xl font-black font-mono text-primary tabular-nums mb-2 drop-shadow-[0_0_26px_hsl(var(--primary)/.25)]">
                    {formatTime(restTimeLeft)}
                  </div>
                  <p className="text-sm text-slate-500 uppercase tracking-widest">
                    Next: Set {currentSet + 1}
                  </p>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Pause Overlay */}
            <AnimatePresence>
              {isPaused && !isResting && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="absolute inset-0 bg-[#11110f]/92 backdrop-blur-sm flex flex-col items-center justify-center z-30"
                >
                  <Pause className="w-16 h-16 text-slate-500 mb-4" />
                  <p className="text-2xl font-black uppercase tracking-widest text-white">
                    Paused
                  </p>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* Development rail: useful telemetry stays below the clean camera frame. */}
          <div className="min-h-37.5 flex-1 rounded-[1.35rem] border border-white/10 bg-[#171714] p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-[.22em] text-primary">
                  Live exercise data
                </p>
                <p className="mt-1 text-sm font-semibold text-white">
                  {data
                    ? repData?.feedback ||
                      holdData?.feedback ||
                      "Tracking your movement."
                    : "Telemetry will appear when the coach connects."}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setLandmarksVisible((visible) => !visible)}
                aria-pressed={landmarksVisible}
                className={cn(
                  "flex items-center gap-2 rounded-full border px-3 py-1.5 text-[10px] font-bold uppercase tracking-widest transition-all",
                  landmarksVisible
                    ? "border-primary/35 bg-primary/10 text-primary"
                    : "border-white/15 bg-white/5 text-slate-400 hover:border-primary/30 hover:text-primary",
                )}
              >
                {landmarksVisible ? (
                  <Eye className="h-3.5 w-3.5" />
                ) : (
                  <EyeOff className="h-3.5 w-3.5" />
                )}
                Landmarks {landmarksVisible ? "on" : "off"}
              </button>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-4">
              <SessionMetric
                label="Pose"
                value={poseStatus}
                tone={poseDetected ? "good" : "neutral"}
              />
              <SessionMetric
                label="Frame"
                value={frameStatus}
                tone={data?.framing_ok ? "good" : "warn"}
              />
              <SessionMetric
                label={exercise.mode === "reps" ? "Stage" : "Hold state"}
                value={movementStage}
                tone="accent"
              />
              <SessionMetric
                label="Landmarks"
                value={`${visibleLandmarkCount}/33`}
                tone={landmarksVisible ? "good" : "neutral"}
              />
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-[10px] font-bold uppercase tracking-[.14em] text-slate-500">
              <span className="inline-flex items-center gap-1.5">
                <Gauge className="h-3.5 w-3.5 text-accent" /> Visibility{" "}
                {averageVisibility !== null ? `${averageVisibility}%` : "—"}
              </span>
              {repData?.angle !== null && repData?.angle !== undefined && (
                <span>Angle {Math.round(repData.angle)}°</span>
              )}
              {holdData?.form_score !== null &&
                holdData?.form_score !== undefined && (
                  <span>Form score {Math.round(holdData.form_score)}/100</span>
                )}
              <span className="ml-auto inline-flex items-center gap-1.5">
                <span
                  className={cn(
                    "h-1.5 w-1.5 rounded-full animate-pulse",
                    connected ? "bg-primary" : "bg-accent",
                  )}
                />
                {connected ? "Telemetry live" : "Camera ready"}
              </span>
            </div>
          </div>
        </div>

        {/* RIGHT: Data Panel */}
        <div className="flex-1 flex flex-col overflow-hidden border-t lg:border-t-0 lg:border-l border-white/10 min-h-0 bg-[#171714]/90 lg:rounded-tl-[1.35rem]">
          {/* Scrollable data */}
          <div
            className="flex-1 overflow-y-auto p-4 space-y-4"
            style={{
              scrollbarWidth: "thin",
              scrollbarColor: "hsl(var(--primary) / .3) transparent",
            }}
          >
            {!sessionStarted ? (
              <div className="flex flex-col items-center justify-center h-full min-h-70 text-center px-6">
                <div className="signal-pulse w-14 h-14 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center mb-4">
                  <Camera className="w-6 h-6 text-primary" />
                </div>
                <h2 className="font-display text-xl font-extrabold text-foreground">
                  Ready when you are
                </h2>
                <p className="text-sm text-muted-foreground mt-2 max-w-xs">
                  Your camera and live form coach stay off until you start.
                </p>
                <button
                  onClick={beginSession}
                  data-testid="button-begin-countdown"
                  className="mt-6 inline-flex items-center gap-2 rounded-xl bg-primary text-primary-foreground px-5 py-3 text-sm font-bold uppercase tracking-wider shadow-lg shadow-primary/20 hover:brightness-105"
                >
                  <Play className="w-4 h-4 fill-current" /> Start session
                </button>
                <div className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
                  <ShieldCheck className="w-4 h-4 text-primary" /> Camera access
                  stays local to this session
                </div>
              </div>
            ) : panelData ? (
              exercise.mode === "reps" ? (
                <RepPanel
                  data={panelData as typeof repData}
                  lastRep={lastRep}
                  exerciseName={exercise.name}
                />
              ) : (
                <HoldPanel
                  data={panelData as typeof holdData}
                  exerciseName={exercise.name}
                />
              )
            ) : (
              <div className="flex flex-col items-center justify-center h-48 text-center">
                <div className="relative mb-5 flex h-16 w-16 items-center justify-center rounded-full border border-accent/25 bg-accent/5">
                  <Activity className="h-7 w-7 text-accent" />
                  <span className="absolute inset-0 rounded-full border border-accent/20 animate-ping" />
                </div>
                <p className="text-xs font-bold text-slate-300 uppercase tracking-[.2em]">
                  Coach is connecting
                </p>
                <div className="mt-4 flex items-center gap-1.5">
                  {[0, 1, 2].map((dot) => (
                    <span
                      key={dot}
                      className="h-1.5 w-1.5 rounded-full bg-primary/70 animate-pulse"
                      style={{ animationDelay: `${dot * 180}ms` }}
                    />
                  ))}
                </div>
                {socketError && (
                  <p className="text-xs text-red-300/80 mt-3">{socketError}</p>
                )}
                {!connected && !socketError && (
                  <p className="text-xs text-slate-500 mt-2">
                    Your camera can still stay ready while tracking connects.
                  </p>
                )}
              </div>
            )}
          </div>

          {/* Bottom: Pause / Resume */}
          <div className="px-4 py-3 border-t border-white/10 shrink-0 bg-[#171714]">
            <button
              data-testid="button-pause-session"
              onClick={togglePause}
              disabled={isResting}
              className={cn(
                "w-full py-3.5 rounded-xl font-black uppercase tracking-widest text-sm flex items-center justify-center gap-2 transition-all disabled:opacity-40",
                isPaused
                  ? "bg-primary text-primary-foreground hover:brightness-110"
                  : "bg-white/10 text-white hover:bg-white/15",
              )}
            >
              {isPaused ? (
                <>
                  <Play className="w-4 h-4" /> Resume
                </>
              ) : (
                <>
                  <Pause className="w-4 h-4" /> Pause
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function SessionMetric({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: React.ReactNode;
  tone?: "good" | "warn" | "accent" | "neutral";
}) {
  return (
    <div className="rounded-xl border border-white/10 bg-black/15 px-3 py-2.5">
      <p className="text-[9px] font-bold uppercase tracking-[.16em] text-slate-500">
        {label}
      </p>
      <p
        className={cn(
          "mt-1 truncate text-xs font-bold capitalize",
          tone === "good" && "text-primary",
          tone === "warn" && "text-accent",
          tone === "accent" && "text-accent",
          tone === "neutral" && "text-slate-300",
        )}
      >
        {value}
      </p>
    </div>
  );
}
