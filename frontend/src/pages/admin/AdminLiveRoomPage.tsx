import React, { useEffect, useRef, useState } from "react";
import { useRoute, Link } from "wouter";
import { AdminShell } from "@/components/admin/AdminShell";
import { useAdminSpectate } from "@/hooks/useAdminSpectate";
import { ArrowLeft, Wifi, WifiOff, Trophy, Users, AlertTriangle, Radio } from "lucide-react";
import { cn } from "@/lib/utils";

const STATUS_LABEL: Record<string, string> = {
  WAITING: "Waiting for players",
  FULL: "Room full - starting soon",
  COUNTDOWN: "Starting",
  ROUND_RUNNING: "Round in progress",
  ROUND_FINISHED: "Round finished",
  BREAK: "On break",
  COMPLETED: "Completed",
  ABANDONED: "Abandoned",
};

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

function formatClock(ms: number | null): string {
  if (ms === null) return "--:--";
  const totalSeconds = Math.ceil(ms / 1000);
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

const RANK_STYLE: Record<number, string> = {
  1: "bg-primary text-primary-foreground",
  2: "bg-secondary text-foreground",
  3: "bg-secondary/70 text-foreground",
};

export function AdminLiveRoomPage() {
  const [, params] = useRoute("/admin/rooms/:competitionId");
  const competitionId = params?.competitionId;
  const { room, error, connected } = useAdminSpectate(competitionId);
  const offsetRef = useServerClockOffset(room?.serverNow);

  const countdownRemaining = useCountdownTo(room?.countdownEndAt ?? null, offsetRef);
  const roundRemaining = useCountdownTo(room?.roundEndAt ?? null, offsetRef);
  const breakRemaining = useCountdownTo(room?.breakEndAt ?? null, offsetRef);

  const clock =
    room?.status === "COUNTDOWN"
      ? countdownRemaining
      : room?.status === "ROUND_RUNNING"
        ? roundRemaining
        : room?.status === "BREAK"
          ? breakRemaining
          : null;

  const isLive = room?.status === "ROUND_RUNNING" || room?.status === "COUNTDOWN";

  return (
    <AdminShell>
      <Link
        href="/admin"
        className="inline-flex items-center gap-2 text-sm font-bold text-muted-foreground hover:text-foreground transition-colors mb-6"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to control room
      </Link>

      {error && (
        <div className="bg-destructive/10 border border-destructive/30 rounded-2xl p-4 flex gap-3 items-start mb-6">
          <AlertTriangle className="w-5 h-5 text-destructive shrink-0 mt-0.5" />
          <p className="text-sm text-destructive font-semibold">{error}</p>
        </div>
      )}

      {!room && !error && (
        <div className="space-y-4">
          <div className="h-24 bg-card border border-card-border rounded-3xl animate-pulse" />
          <div className="h-64 bg-card border border-card-border rounded-3xl animate-pulse" />
        </div>
      )}

      {room && (
        <>
          <div className="flex items-start justify-between flex-wrap gap-4 mb-8">
            <div>
              <div className="flex items-center gap-2 mb-1.5">
                <span className={cn("w-2 h-2 rounded-full bg-destructive", isLive && "live-pulse")} />
                <span className="text-[10px] font-mono uppercase tracking-[0.25em] text-destructive font-bold">
                  Live spectate
                </span>
              </div>
              <h1 className="font-display text-2xl md:text-3xl font-extrabold tracking-tight">{room.eventName}</h1>
              <p className="text-sm text-muted-foreground mt-1">{STATUS_LABEL[room.status] ?? room.status}</p>
            </div>

            <div className="flex items-center gap-2">
              {connected ? (
                <span className="flex items-center gap-1.5 text-xs font-bold text-primary bg-primary/10 px-3 py-1.5 rounded-full">
                  <Wifi className="w-3.5 h-3.5" />
                  Connected
                </span>
              ) : (
                <span className="flex items-center gap-1.5 text-xs font-bold text-destructive bg-destructive/10 px-3 py-1.5 rounded-full">
                  <WifiOff className="w-3.5 h-3.5" />
                  Reconnecting
                </span>
              )}
            </div>
          </div>

          {/* Broadcast strip: round + timer + participants */}
          <div className="grid grid-cols-3 gap-3 mb-8">
            <div className="bg-card border border-card-border rounded-3xl p-5">
              <p className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground mb-1">Round</p>
              <p className="font-mono text-3xl font-bold tabular-nums">
                {room.currentRound || 1}
                <span className="text-muted-foreground text-lg">/{room.totalRounds}</span>
              </p>
            </div>
            <div className="bg-card border border-card-border rounded-3xl p-5">
              <p className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground mb-1">
                {room.status === "BREAK" ? "Break ends in" : room.status === "COUNTDOWN" ? "Starts in" : "Time left"}
              </p>
              <p className="font-mono text-3xl font-bold tabular-nums">{formatClock(clock)}</p>
            </div>
            <div className="bg-card border border-card-border rounded-3xl p-5">
              <p className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground mb-1">Players</p>
              <p className="font-mono text-3xl font-bold tabular-nums">
                {room.participants.length}
                <span className="text-muted-foreground text-lg">/{room.maxParticipants}</span>
              </p>
            </div>
          </div>

          {/* Live leaderboard */}
          <section>
            <div className="flex items-center gap-2 mb-4">
              <Trophy className="w-4 h-4 text-primary" />
              <h2 className="font-display text-lg font-extrabold tracking-tight">Live leaderboard</h2>
            </div>

            <div className="bg-card border border-card-border rounded-3xl overflow-hidden divide-y divide-card-border/60">
              {room.leaderboard.length === 0 && (
                <div className="p-8 text-center">
                  <Users className="w-8 h-8 text-muted-foreground mx-auto mb-2 opacity-40" />
                  <p className="text-sm text-muted-foreground font-semibold">No scores reported yet.</p>
                </div>
              )}
              {room.leaderboard.map((entry) => {
                const participant = room.participants.find((p) => p.participantId === entry.participantId);
                return (
                  <div
                    key={entry.participantId}
                    data-testid={`leaderboard-row-${entry.participantId}`}
                    className="flex items-center gap-4 px-5 py-4"
                  >
                    <span
                      className={cn(
                        "w-8 h-8 rounded-lg flex items-center justify-center font-mono font-bold text-sm shrink-0",
                        RANK_STYLE[entry.rank] ?? "bg-secondary/50 text-muted-foreground",
                      )}
                    >
                      {entry.rank}
                    </span>
                    <span className="flex-1 font-bold truncate">{entry.displayName}</span>
                    <span
                      className={cn(
                        "w-1.5 h-1.5 rounded-full shrink-0",
                        participant?.connected ? "bg-primary" : "bg-muted-foreground/40",
                      )}
                      title={participant?.connected ? "Connected" : "Disconnected"}
                    />
                    <span className="font-mono text-xl font-bold tabular-nums w-16 text-right">{entry.score}</span>
                  </div>
                );
              })}
            </div>
          </section>

          {room.status === "COMPLETED" && (
            <div className="mt-6 flex items-center gap-2.5 bg-primary/10 border border-primary/20 rounded-2xl p-4">
              <Radio className="w-4 h-4 text-primary" />
              <p className="text-sm font-semibold text-primary">
                This competition has finished. Final results are stored - the room stays visible here briefly for
                review.
              </p>
            </div>
          )}
        </>
      )}
    </AdminShell>
  );
}
