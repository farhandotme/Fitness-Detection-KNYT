import React, { useEffect, useState } from "react";
import { useRoute, Link, useLocation } from "wouter";
import { AdminShell } from "@/components/admin/AdminShell";
import {
  type AdminEventRoomsResponse,
  type AdminEventRoomSummary,
  clearAdminSession,
  fetchEventRooms,
  getAdminToken,
} from "@/lib/adminApi";
import {
  ArrowLeft,
  Radio,
  Users,
  Timer,
  Crown,
  AlertTriangle,
  RefreshCw,
  Lock,
  Globe,
  CheckCircle2,
  XCircle,
  Clock,
} from "lucide-react";
import { cn } from "@/lib/utils";

const STATUS_LABEL: Record<string, string> = {
  WAITING: "Waiting for players",
  FULL: "Room full",
  COUNTDOWN: "Starting",
  ROUND_RUNNING: "Round in progress",
  ROUND_FINISHED: "Round finished",
  BREAK: "On break",
  COMPLETED: "Completed",
  ABANDONED: "Closed",
};

const PHASE_STYLES: Record<AdminEventRoomSummary["phase"], string> = {
  running: "bg-destructive/10 text-destructive",
  waiting: "bg-primary/15 text-primary",
  ended: "bg-secondary text-muted-foreground",
};

const PHASE_LABEL: Record<AdminEventRoomSummary["phase"], string> = {
  running: "Running",
  waiting: "Not started",
  ended: "Ended",
};

/**
 * A single event's rooms, organized instead of dumped alongside every other
 * event on one page: what's live right now, and the full history of every
 * room created under this event with who created it (the room's host - see
 * models/Competition.ts isHost / services/roomService.ts).
 */
export function AdminEventRoomsPage() {
  const [, params] = useRoute("/admin/events/:eventId");
  const [, setLocation] = useLocation();
  const eventId = params?.eventId;

  const [data, setData] = useState<AdminEventRoomsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!getAdminToken()) {
      setLocation("/admin/login");
      return;
    }
    if (!eventId) return;
    void load(true);
    const interval = window.setInterval(() => void load(false), 5000);
    return () => window.clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eventId]);

  const load = async (showSpinner: boolean) => {
    if (!eventId) return;
    if (showSpinner) setLoading(true);
    try {
      const res = await fetchEventRooms(eventId);
      setData(res);
      setError(null);
    } catch (err: any) {
      const message = err.message || "Could not load this event's rooms";
      setError(message);
      if (message.toLowerCase().includes("session") || message.toLowerCase().includes("token")) {
        clearAdminSession();
        setLocation("/admin/login");
      }
    } finally {
      if (showSpinner) setLoading(false);
    }
  };

  if (!eventId) {
    return (
      <AdminShell>
        <p className="text-sm text-destructive">Event not found.</p>
      </AdminShell>
    );
  }

  const runningRooms = data?.rooms.filter((r) => r.phase === "running") ?? [];
  const waitingRooms = data?.rooms.filter((r) => r.phase === "waiting") ?? [];
  const endedRooms = data?.rooms.filter((r) => r.phase === "ended") ?? [];

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
        <div className="bg-destructive/10 border border-destructive/30 rounded-2xl p-4 flex gap-3 items-center mb-6">
          <AlertTriangle className="w-5 h-5 text-destructive shrink-0" />
          <p className="text-sm text-destructive font-bold">{error}</p>
        </div>
      )}

      {loading && !data && (
        <div className="space-y-4">
          <div className="h-20 bg-card border border-card-border rounded-3xl animate-pulse" />
          <div className="h-48 bg-card border border-card-border rounded-3xl animate-pulse" />
        </div>
      )}

      {data && (
        <>
          <div className="flex items-start justify-between flex-wrap gap-3 mb-8">
            <div>
              <p className="text-[10px] font-mono uppercase tracking-[0.25em] text-primary mb-1.5">
                {data.event.exerciseName}
              </p>
              <h1 className="font-display text-3xl md:text-[2.25rem] font-extrabold tracking-tight leading-none">
                {data.event.name}
              </h1>
              <p className="text-sm text-muted-foreground mt-2">
                {data.rooms.length} room{data.rooms.length === 1 ? "" : "s"} created under this event · max{" "}
                {data.event.maxParticipants} players per room
              </p>
            </div>
            <button
              onClick={() => load(true)}
              disabled={loading}
              className="flex items-center gap-2 px-4 py-2.5 rounded-full text-xs font-bold uppercase tracking-wider bg-secondary text-muted-foreground hover:bg-secondary/85 transition-colors disabled:opacity-50"
            >
              <RefreshCw className={loading ? "w-3.5 h-3.5 animate-spin" : "w-3.5 h-3.5"} />
              Refresh
            </button>
          </div>

          <section className="mb-10">
            <div className="flex items-center gap-2 mb-4">
              <h2 className="font-display text-lg font-extrabold tracking-tight">Live now</h2>
              {runningRooms.length > 0 && <span className="w-1.5 h-1.5 rounded-full bg-destructive live-pulse" />}
            </div>

            {runningRooms.length === 0 && (
              <div className="bg-card border border-card-border border-dashed rounded-3xl p-8 text-center">
                <Radio className="w-8 h-8 text-muted-foreground mx-auto mb-2 opacity-50" />
                <p className="text-sm font-semibold text-muted-foreground">No rooms running right now.</p>
              </div>
            )}

            {runningRooms.length > 0 && (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {runningRooms.map((room) => (
                  <RoomTile key={room.competitionId} room={room} />
                ))}
              </div>
            )}
          </section>

          {waitingRooms.length > 0 && (
            <section className="mb-10">
              <h2 className="font-display text-lg font-extrabold tracking-tight mb-4">Waiting to start</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {waitingRooms.map((room) => (
                  <RoomTile key={room.competitionId} room={room} />
                ))}
              </div>
            </section>
          )}

          <section>
            <h2 className="font-display text-lg font-extrabold tracking-tight mb-4">All rooms</h2>

            {data.rooms.length === 0 ? (
              <div className="bg-card border border-card-border rounded-3xl p-10 text-center">
                <Users className="w-10 h-10 text-muted-foreground mx-auto mb-3" />
                <p className="font-bold text-foreground">No rooms yet</p>
                <p className="text-sm text-muted-foreground mt-1">
                  Rooms appear here the moment a player creates one for this event.
                </p>
              </div>
            ) : (
              <div className="bg-card border border-card-border rounded-3xl overflow-hidden divide-y divide-card-border/60">
                <div className="hidden md:grid grid-cols-[1.5fr_1fr_1fr_0.8fr_1fr] gap-3 px-5 py-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                  <span>Room</span>
                  <span>Created by</span>
                  <span>Status</span>
                  <span>Players</span>
                  <span>Created</span>
                </div>
                {data.rooms.map((room) => (
                  <RoomRow key={room.competitionId} room={room} />
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </AdminShell>
  );
}

function RoomTile({ room }: { room: AdminEventRoomSummary }) {
  const statusLabel = STATUS_LABEL[room.status] ?? room.status;
  const isRunning = room.status === "ROUND_RUNNING";

  return (
    <div className="bg-card border border-card-border rounded-3xl p-5 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <span
          className={cn(
            "flex items-center gap-1.5 text-[10px] font-mono uppercase tracking-[0.2em] font-bold px-2 py-1 rounded-full",
            PHASE_STYLES[room.phase],
          )}
        >
          <span className={cn("w-1.5 h-1.5 rounded-full", room.phase === "running" ? "bg-destructive" : "bg-current", isRunning && "live-pulse")} />
          {PHASE_LABEL[room.phase]}
        </span>
        {room.totalRounds > 0 && (
          <span className="text-[11px] font-mono text-muted-foreground tabular-nums">
            Round {room.currentRound || 1}/{room.totalRounds}
          </span>
        )}
      </div>

      <div>
        <h3 className="font-bold text-base leading-tight truncate flex items-center gap-1.5">
          {room.visibility === "private" ? (
            <Lock className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
          ) : (
            <Globe className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
          )}
          {room.roomName}
        </h3>
        <p className="text-xs text-muted-foreground mt-1">{statusLabel}</p>
      </div>

      {room.hostName && (
        <p className="flex items-center gap-1.5 text-[11px] font-semibold text-muted-foreground">
          <Crown className="w-3 h-3 text-primary" />
          Created by {room.hostName}
        </p>
      )}

      <div className="flex items-center justify-between mt-auto pt-1">
        <span className="flex items-center gap-1.5 text-xs font-mono text-muted-foreground">
          <Users className="w-3.5 h-3.5" />
          {room.participantCount}/{room.maxParticipants}
        </span>
        <Link
          href={`/admin/rooms/${room.competitionId}`}
          className="flex items-center gap-1.5 px-3.5 py-2 rounded-full text-xs font-black uppercase tracking-wider bg-foreground text-background hover:brightness-110 transition-all"
        >
          <Timer className="w-3.5 h-3.5" />
          Watch live
        </Link>
      </div>
    </div>
  );
}

function RoomRow({ room }: { room: AdminEventRoomSummary }) {
  const statusLabel = STATUS_LABEL[room.status] ?? room.status;
  const createdAt = new Date(room.createdAt);

  return (
    <Link
      href={`/admin/rooms/${room.competitionId}`}
      className="grid grid-cols-2 md:grid-cols-[1.5fr_1fr_1fr_0.8fr_1fr] gap-3 px-5 py-4 hover:bg-secondary/30 transition-colors items-center"
    >
      <div className="flex items-center gap-2 min-w-0 col-span-2 md:col-span-1">
        {room.visibility === "private" ? (
          <Lock className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
        ) : (
          <Globe className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
        )}
        <span className="font-bold truncate">{room.roomName}</span>
      </div>
      <div className="flex items-center gap-1.5 min-w-0 text-sm">
        {room.hostName ? (
          <>
            <Crown className="w-3.5 h-3.5 text-primary shrink-0" />
            <span className="truncate font-semibold">{room.hostName}</span>
          </>
        ) : (
          <span className="text-muted-foreground text-xs">—</span>
        )}
      </div>
      <div>
        <span
          className={cn(
            "inline-flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider px-2.5 py-1 rounded-full",
            PHASE_STYLES[room.phase],
          )}
        >
          {room.phase === "ended" ? (
            room.status === "COMPLETED" ? (
              <CheckCircle2 className="w-3 h-3" />
            ) : (
              <XCircle className="w-3 h-3" />
            )
          ) : room.phase === "running" ? (
            <Radio className="w-3 h-3" />
          ) : (
            <Clock className="w-3 h-3" />
          )}
          {statusLabel}
        </span>
      </div>
      <div className="flex items-center gap-1.5 text-sm font-mono text-muted-foreground">
        <Users className="w-3.5 h-3.5" />
        {room.participantCount}/{room.maxParticipants}
      </div>
      <div className="text-xs text-muted-foreground font-mono">
        {createdAt.toLocaleDateString()} {createdAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
      </div>
    </Link>
  );
}
