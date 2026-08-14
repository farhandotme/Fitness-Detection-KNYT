import React, { useCallback, useEffect, useRef, useState } from "react";
import { useRoute, useLocation } from "wouter";
import { getExerciseById } from "@/config/exercises";
import { useCamera } from "@/hooks/useCamera";
import { useExerciseSocket } from "@/hooks/useExerciseSocket";
import { useCompetitionRoom } from "@/hooks/useCompetitionRoom";
import { CameraPreview } from "@/components/CameraPreview";
import { RepPanel } from "@/components/RepPanel";
import { HoldPanel } from "@/components/HoldPanel";
import { cn } from "@/lib/utils";
import {
  X,
  Trophy,
  Users,
  Wifi,
  WifiOff,
  Coffee,
  Flag,
  AlertTriangle,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

/** How the competition-server clock relates to this browser's clock. */
function useServerClockOffset(serverNow: number | undefined) {
  const offsetRef = useRef(0);
  useEffect(() => {
    if (typeof serverNow === "number") offsetRef.current = serverNow - Date.now();
  }, [serverNow]);
  return offsetRef;
}

function useCountdownTo(targetEpochMs: number | null, offsetRef: React.MutableRefObject<number>) {
  const [remainingMs, setRemainingMs] = useState<number | null>(null);
  useEffect(() => {
    if (targetEpochMs === null) {
      setRemainingMs(null);
      return;
    }
    const tick = () => setRemainingMs(Math.max(0, targetEpochMs - (Date.now() + offsetRef.current)));
    tick();
    const id = window.setInterval(tick, 200);
    return () => window.clearInterval(id);
  }, [targetEpochMs, offsetRef]);
  return remainingMs;
}

export function CompetitionPlayPage() {
  const [match, params] = useRoute("/competitions/:competitionId/play");
  const [, setLocation] = useLocation();
  const competitionId = params?.competitionId;

  const { room, identity, error, closed, connected, submitScore } = useCompetitionRoom(competitionId);
  const offsetRef = useServerClockOffset(room?.serverNow);

  const exercise = room ? getExerciseById(room.exerciseId) : undefined;

  const { videoRef, canvasRef, permission, startCamera, stopCamera, captureFrame } = useCamera(
    exercise?.cameraMirror ?? true,
  );
  const {
    connected: exerciseConnected,
    socketError: exerciseSocketError,
    data,
    lastRep,
    start,
    stop,
    sendFrame,
  } = useExerciseSocket(exercise ?? getExerciseById("pushup")!);

  const frameIntervalRef = useRef<number | null>(null);
  const prevStatusRef = useRef<string | null>(null);
  const lastSentRef = useRef<{ value: number; time: number }>({ value: -1, time: 0 });

  const startSendingFrames = useCallback(() => {
    if (frameIntervalRef.current) return;
    frameIntervalRef.current = window.setInterval(() => {
      const frame = captureFrame();
      if (frame) sendFrame(frame);
    }, 120);
  }, [captureFrame, sendFrame]);

  const stopSendingFrames = useCallback(() => {
    if (frameIntervalRef.current) {
      window.clearInterval(frameIntervalRef.current);
      frameIntervalRef.current = null;
    }
  }, []);

  // No stored identity for this room -> the participant never actually
  // joined it (direct link, cleared storage, etc). Send them to join properly.
  useEffect(() => {
    if (competitionId && !identity) {
      const t = setTimeout(() => setLocation("/events"), 1200);
      return () => clearTimeout(t);
    }
  }, [competitionId, identity, setLocation]);

  useEffect(() => {
    if (room?.status === "COMPLETED") {
      setLocation(`/competitions/${room.competitionId}/results`);
    }
  }, [room?.status, room?.competitionId, setLocation]);

  // The host left/disconnected for good and the room was torn down
  // server-side (see useCompetitionRoom.ts "room:closed") - stop everything
  // and send this participant back to browse other events.
  useEffect(() => {
    if (!closed) return;
    stop();
    stopCamera();
    stopSendingFrames();
    const t = setTimeout(() => setLocation("/events"), 2500);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [closed, setLocation]);

  // Drive the camera + exercise engine strictly off the server-authoritative round state.
  useEffect(() => {
    if (!room || !exercise) return;
    const status = room.status;

    if (status === "ROUND_RUNNING" && prevStatusRef.current !== "ROUND_RUNNING") {
      let cancelled = false;
      (async () => {
        const ready = await startCamera();
        if (cancelled || !ready) return;
        start(
          exercise.mode === "reps"
            ? { targetReps: 999, targetSets: 1, setNumber: room.currentRound }
            : { targetSeconds: room.roundDurationSeconds + 5, targetSets: 1, setNumber: room.currentRound },
        );
      })();
      prevStatusRef.current = status;
      return () => {
        cancelled = true;
      };
    }

    if (status !== "ROUND_RUNNING" && prevStatusRef.current === "ROUND_RUNNING") {
      stop();
      stopCamera();
      stopSendingFrames();
    }

    prevStatusRef.current = status;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [room?.status, room?.currentRound, exercise?.id]);

  useEffect(() => {
    if (exerciseConnected && permission === "granted" && room?.status === "ROUND_RUNNING") {
      startSendingFrames();
    } else {
      stopSendingFrames();
    }
    return stopSendingFrames;
  }, [exerciseConnected, permission, room?.status, startSendingFrames, stopSendingFrames]);

  // Report score to the competition backend - the frontend never decides the
  // official leaderboard, it only tells the server what it is currently seeing.
  useEffect(() => {
    if (!data || !room || room.status !== "ROUND_RUNNING" || !exercise) return;
    const raw =
      exercise.mode === "reps" ? (data as any).rep_count : (data as any).hold_seconds;
    if (typeof raw !== "number") return;
    const now = Date.now();
    if (raw === lastSentRef.current.value) return;
    if (now - lastSentRef.current.time < 200) return;
    lastSentRef.current = { value: raw, time: now };
    submitScore(room.currentRound, raw, "RUNNING");
  }, [data, room?.status, room?.currentRound, exercise, submitScore]);

  // Full teardown on unmount.
  useEffect(() => {
    return () => {
      stop();
      stopCamera();
      stopSendingFrames();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const countdownRemaining = useCountdownTo(room?.countdownEndAt ?? null, offsetRef);
  const roundRemaining = useCountdownTo(room?.roundEndAt ?? null, offsetRef);
  const breakRemaining = useCountdownTo(room?.breakEndAt ?? null, offsetRef);

  if (!match || !competitionId) {
    return <div className="p-8 text-center text-destructive">Room not found.</div>;
  }

  if (closed) {
    return (
      <div className="min-h-dvh flex items-center justify-center bg-[#11110f] text-slate-300">
        <div className="flex flex-col items-center gap-3 text-center px-6">
          <AlertTriangle className="w-8 h-8 text-destructive" />
          <p className="font-bold text-lg text-white">Room closed</p>
          <p className="text-sm text-slate-400 max-w-sm">{closed}</p>
        </div>
      </div>
    );
  }

  if (!room || !exercise) {
    return (
      <div className="min-h-dvh flex items-center justify-center bg-[#11110f] text-slate-300">
        {error ? (
          <div className="flex items-center gap-2 text-destructive">
            <AlertTriangle className="w-5 h-5" /> {error}
          </div>
        ) : (
          "Connecting to your competition room..."
        )}
      </div>
    );
  }

  const myScore = room.leaderboard.find((e) => e.participantId === identity?.participantId);
  const repData = exercise.mode === "reps" && data ? (data as any) : null;
  const holdData = exercise.mode === "hold" && data ? (data as any) : null;
  const poseDetected = Boolean((data as any)?.pose_detected);
  const poseLandmarks = poseDetected ? ((data as any)?.landmarks ?? []) : [];

  const handleExit = () => {
    stop();
    stopCamera();
    stopSendingFrames();
    setLocation("/events");
  };

  return (
    <div className="min-h-dvh max-h-dvh bg-[#11110f] text-foreground flex flex-col overflow-hidden">
      {/* Top bar */}
      <header className="flex items-center gap-3 px-4 py-3 border-b border-white/10 shrink-0 bg-[#171714]/95 backdrop-blur-xl">
        <button
          onClick={handleExit}
          data-testid="button-exit-competition"
          className="flex items-center gap-1.5 text-slate-400 hover:text-white text-xs font-bold tracking-widest uppercase transition-colors"
        >
          <X className="w-4 h-4" />
          Exit
        </button>
        <div className="h-4 w-px bg-white/10" />
        <h1 className="text-sm font-black uppercase tracking-widest text-foreground flex-1 truncate">
          {room.eventName}
        </h1>
        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-500">Round</span>
          <span className="font-black text-white font-mono">
            {Math.max(room.currentRound, 1)}/{room.totalRounds}
          </span>
        </div>
        <span
          className={cn(
            "flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest px-2 py-1 rounded-md",
            connected ? "text-primary" : "text-destructive",
          )}
        >
          {connected ? <Wifi className="w-3.5 h-3.5" /> : <WifiOff className="w-3.5 h-3.5" />}
        </span>
      </header>

      <div className="flex-1 flex flex-col lg:flex-row overflow-hidden min-h-0">
        {/* LEFT: Camera */}
        <div className="w-full lg:w-[58%] flex flex-col min-h-0 overflow-y-auto bg-[#11110f] p-3 gap-3">
          <div className="relative w-full aspect-video shrink-0 overflow-hidden rounded-[1.35rem] border border-white/10 bg-[#11110f] shadow-2xl shadow-black/30">
            <CameraPreview
              videoRef={videoRef}
              canvasRef={canvasRef}
              permission={permission}
              mirror={exercise.cameraMirror}
              landmarks={poseLandmarks}
              landmarksVisible={false}
              poseDetected={poseDetected}
              className="rounded-[1.35rem]"
            />

            {/* Round timer overlay */}
            {room.status === "ROUND_RUNNING" && roundRemaining !== null && (
              <div className="absolute top-4 left-4 z-20 bg-black/50 backdrop-blur-md rounded-xl px-4 py-2">
                <p className="text-[10px] uppercase tracking-widest text-slate-400">Time left</p>
                <p className="text-2xl font-mono font-black text-primary tabular-nums">
                  {Math.ceil(roundRemaining / 1000)}s
                </p>
              </div>
            )}

            {/* Your live score overlay */}
            {room.status === "ROUND_RUNNING" && (
              <div className="absolute top-4 right-4 z-20 bg-black/50 backdrop-blur-md rounded-xl px-4 py-2 text-right">
                <p className="text-[10px] uppercase tracking-widest text-slate-400">Your score</p>
                <p className="text-2xl font-mono font-black text-white tabular-nums">
                  {myScore?.score ?? 0}
                </p>
              </div>
            )}

            {/* Countdown overlay */}
            <AnimatePresence>
              {room.status === "COUNTDOWN" && countdownRemaining !== null && (
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
                    key={Math.ceil(countdownRemaining / 1000)}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -8 }}
                    transition={{ duration: 0.25, ease: "easeOut" }}
                    className="relative z-10 h-[clamp(8rem,18vw,12rem)] w-[clamp(8rem,18vw,12rem)] text-center font-display text-[clamp(8rem,18vw,12rem)] leading-[.9] font-extrabold tabular-nums text-primary drop-shadow-[0_0_32px_hsl(var(--primary)/.35)]"
                  >
                    {Math.max(1, Math.ceil(countdownRemaining / 1000))}
                  </motion.div>
                  <p className="relative z-10 text-sm text-slate-300 mt-3">
                    Round {room.currentRound || 1} begins for everyone at once
                  </p>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Round finished / break overlay */}
            <AnimatePresence>
              {(room.status === "ROUND_FINISHED" || room.status === "BREAK") && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="absolute inset-0 bg-[#11110f]/95 backdrop-blur-sm flex flex-col items-center justify-center z-30 text-center px-6"
                >
                  <Flag className="w-10 h-10 text-primary mb-4" />
                  <p className="text-[10px] font-bold tracking-widest uppercase text-slate-500 mb-2">
                    Round {room.currentRound} complete
                  </p>
                  {room.status === "BREAK" && breakRemaining !== null ? (
                    <>
                      <div className="flex items-center gap-2 text-slate-300 mb-2">
                        <Coffee className="w-4 h-4" />
                        <span className="text-xs uppercase tracking-widest">Short break</span>
                      </div>
                      <div className="text-6xl font-black font-mono text-primary tabular-nums mb-2">
                        {Math.ceil(breakRemaining / 1000)}s
                      </div>
                      <p className="text-sm text-slate-500 uppercase tracking-widest">
                        Next: Round {room.currentRound + 1}
                      </p>
                    </>
                  ) : (
                    <p className="text-sm text-slate-400">Calculating results...</p>
                  )}
                </motion.div>
              )}
            </AnimatePresence>

            {room.status === "WAITING" || room.status === "FULL" ? (
              <div className="absolute inset-0 bg-[#171714]/95 flex items-center justify-center text-slate-400 text-sm">
                Waiting for the room to fill...
              </div>
            ) : null}
          </div>

          {exerciseSocketError && (
            <p className="text-xs text-destructive px-1">{exerciseSocketError}</p>
          )}
        </div>

        {/* RIGHT: Leaderboard + telemetry */}
        <div className="flex-1 flex flex-col overflow-hidden border-t lg:border-t-0 lg:border-l border-white/10 min-h-0 bg-[#171714]/90 lg:rounded-tl-[1.35rem]">
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            <div>
              <div className="flex items-center gap-2 mb-3">
                <Trophy className="w-4 h-4 text-accent" />
                <h3 className="text-xs font-bold uppercase tracking-[.2em] text-accent">
                  Live leaderboard
                </h3>
              </div>
              <div className="space-y-2">
                {room.leaderboard.map((entry) => {
                  const isMe = entry.participantId === identity?.participantId;
                  return (
                    <div
                      key={entry.participantId}
                      data-testid={`leaderboard-entry-${entry.rank}`}
                      className={cn(
                        "flex items-center gap-3 rounded-xl px-3 py-2.5 border",
                        isMe
                          ? "border-primary/40 bg-primary/10"
                          : "border-white/10 bg-white/[0.03]",
                      )}
                    >
                      <span
                        className={cn(
                          "w-7 h-7 rounded-full flex items-center justify-center text-xs font-black shrink-0",
                          entry.rank === 1
                            ? "bg-accent text-[#171714]"
                            : "bg-white/10 text-slate-300",
                        )}
                      >
                        {entry.rank}
                      </span>
                      <span className="flex-1 truncate text-sm font-bold text-white">
                        {entry.displayName}
                        {isMe && <span className="text-primary"> (You)</span>}
                      </span>
                      <span className="font-mono text-lg font-black text-white tabular-nums">
                        {entry.score}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            <div>
              <div className="flex items-center gap-2 mb-3">
                <Users className="w-4 h-4 text-primary" />
                <h3 className="text-xs font-bold uppercase tracking-[.2em] text-primary">
                  Participants
                </h3>
              </div>
              <div className="flex flex-wrap gap-2">
                {room.participants.map((p) => (
                  <span
                    key={p.participantId}
                    className={cn(
                      "text-xs font-semibold px-2.5 py-1 rounded-full border flex items-center gap-1.5",
                      p.connected
                        ? "border-white/15 text-slate-300"
                        : "border-destructive/30 text-destructive",
                    )}
                  >
                    <span
                      className={cn(
                        "h-1.5 w-1.5 rounded-full",
                        p.connected ? "bg-primary" : "bg-destructive",
                      )}
                    />
                    {p.displayName}
                  </span>
                ))}
              </div>
            </div>

            {room.status === "ROUND_RUNNING" && (
              <div className="pt-2">
                {exercise.mode === "reps" && repData ? (
                  <RepPanel data={repData} lastRep={lastRep} exerciseName={exercise.name} />
                ) : exercise.mode === "hold" && holdData ? (
                  <HoldPanel data={holdData} exerciseName={exercise.name} />
                ) : (
                  <p className="text-xs text-slate-500 text-center py-6">
                    Waiting for the camera feed...
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
