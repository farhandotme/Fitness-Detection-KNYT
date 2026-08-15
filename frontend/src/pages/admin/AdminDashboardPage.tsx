import React, { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "wouter";
import { AdminShell } from "@/components/admin/AdminShell";
import { exercises } from "@/config/exercises";
import {
  type AdminEvent,
  type AdminStats,
  type LiveRoomSummary,
  clearAdminSession,
  createAdminEvent,
  deleteAdminEvent,
  fetchAdminEvents,
  fetchAdminStats,
  fetchLiveRooms,
  getAdminToken,
  setAdminEventStatus,
  setAdminEventSchedulingPhase,
  updateAdminEvent,
} from "@/lib/adminApi";
import {
  uploadEventImage,
  deleteEventImage,
  EventImageUploadsDisabledError,
} from "@/lib/eventImageStore";
import { getScheduleStatus } from "@/utils/eventSchedule";
import { formatInTimeZone, formatTimeOnlyInTimeZone } from "@/utils/formatTime";
import {
  AlertTriangle,
  Plus,
  RefreshCw,
  Trophy,
  Users,
  Radio,
  Timer,
  Zap,
  CheckCircle2,
  CalendarClock,
  Clock,
  Info,
  Rocket,
  Pencil,
  Trash2,
  ArrowLeft,
  ArrowUpRight,
  Crown,
  Check,
  X,
  Loader2,
  Upload,
} from "lucide-react";
import { cn } from "@/lib/utils";

const STATUS_STYLES: Record<AdminEvent["status"], string> = {
  live: "bg-primary/15 text-primary",
  draft: "bg-secondary text-muted-foreground",
  closed: "bg-destructive/10 text-destructive",
};

const ROOM_STATUS_LABEL: Record<string, string> = {
  WAITING: "Waiting for players",
  FULL: "Room full",
  COUNTDOWN: "Starting",
  ROUND_RUNNING: "Round in progress",
  ROUND_FINISHED: "Round finished",
  BREAK: "On break",
};

export function AdminDashboardPage() {
  const [, setLocation] = useLocation();

  const [stats, setStats] = useState<AdminStats | null>(null);
  const [liveRooms, setLiveRooms] = useState<LiveRoomSummary[] | null>(null);
  const [events, setEvents] = useState<AdminEvent[] | null>(null);
  const [loading, setLoading] = useState(true);

  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [showCreate, setShowCreate] = useState(false);
  const [editingEvent, setEditingEvent] = useState<AdminEvent | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [confirmStatusTarget, setConfirmStatusTarget] = useState<{
    id: string;
    status: AdminEvent["status"];
  } | null>(null);
  const [confirmScheduleCancelId, setConfirmScheduleCancelId] = useState<
    string | null
  >(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    if (success) {
      const timer = setTimeout(() => setSuccess(null), 4000);
      return () => clearTimeout(timer);
    }
  }, [success]);

  useEffect(() => {
    if (!getAdminToken()) {
      setLocation("/admin/login");
      return;
    }
    void loadAll(true);
    const interval = window.setInterval(() => void loadAll(false), 5000);
    return () => window.clearInterval(interval);
  }, []);

  const loadAll = async (showSpinner: boolean) => {
    if (showSpinner) setLoading(true);
    try {
      const [s, rooms, evts] = await Promise.all([
        fetchAdminStats(),
        fetchLiveRooms(),
        fetchAdminEvents(),
      ]);
      setStats(s);
      setLiveRooms(rooms);
      setEvents(evts);
      setError(null);
    } catch (err: any) {
      const message = err.message || "Could not load dashboard data";
      setError(message);
      if (
        message.toLowerCase().includes("session") ||
        message.toLowerCase().includes("token")
      ) {
        clearAdminSession();
        setLocation("/admin/login");
      }
    } finally {
      if (showSpinner) setLoading(false);
    }
  };

  const handleStatusChange = async (
    id: string,
    status: AdminEvent["status"],
  ) => {
    setError(null);
    setSuccess(null);
    try {
      const updated = await setAdminEventStatus(id, status);
      setEvents(
        (prev) => prev?.map((e) => (e._id === id ? updated : e)) ?? prev,
      );
      setConfirmStatusTarget(null);
      setSuccess(`Event successfully updated to ${status}.`);
    } catch (err: any) {
      setError(err.message || "Could not update event status");
      setConfirmStatusTarget(null);
    }
  };

  const handleCancelSchedule = async (id: string) => {
    setError(null);
    setSuccess(null);
    try {
      const updated = await setAdminEventSchedulingPhase(id, "CANCELLED");
      setEvents(
        (prev) => prev?.map((e) => (e._id === id ? updated : e)) ?? prev,
      );
      setConfirmScheduleCancelId(null);
      setSuccess("Schedule has been successfully cancelled.");
    } catch (err: any) {
      setError(err.message || "Could not cancel this event's schedule");
      setConfirmScheduleCancelId(null);
    }
  };

  const handleDelete = async (id: string) => {
    setDeletingId(id);
    setError(null);
    setSuccess(null);
    try {
      await deleteAdminEvent(id);
      setEvents((prev) => prev?.filter((e) => e._id !== id) ?? prev);
      setConfirmDeleteId(null);
      setSuccess("Event has been permanently deleted.");
    } catch (err: any) {
      setError(err.message || "Could not delete this event");
      setConfirmDeleteId(null);
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <AdminShell>
      {showCreate || editingEvent ? (
        <CreateEventView
          event={editingEvent || undefined}
          onClose={() => {
            setShowCreate(false);
            setEditingEvent(null);
          }}
          onSaved={(event) => {
            if (editingEvent) {
              setEvents(
                (prev) =>
                  prev?.map((e) => (e._id === event._id ? event : e)) ?? prev,
              );
              setSuccess("Changes saved successfully.");
            } else {
              setEvents((prev) => (prev ? [event, ...prev] : [event]));
              setSuccess("New event created successfully.");
            }
            setShowCreate(false);
            setEditingEvent(null);
          }}
        />
      ) : (
        <>
          <div className="flex items-start justify-between flex-wrap gap-3 mb-8">
            <div>
              <p className="text-[10px] font-mono uppercase tracking-[0.25em] text-primary mb-1.5">
                Overview
              </p>
              <h1 className="font-display text-3xl md:text-[2.25rem] font-extrabold tracking-tight leading-none">
                Control room
              </h1>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => loadAll(true)}
                disabled={loading}
                className="flex items-center gap-2 px-4 py-2.5 rounded-full text-xs font-bold uppercase tracking-wider bg-secondary text-muted-foreground hover:bg-secondary/85 transition-colors disabled:opacity-50"
              >
                <RefreshCw
                  className={
                    loading ? "w-3.5 h-3.5 animate-spin" : "w-3.5 h-3.5"
                  }
                />
                Refresh
              </button>
              <button
                onClick={() => setShowCreate(true)}
                className="flex items-center gap-2 px-4 py-2.5 rounded-full text-xs font-black uppercase tracking-wider bg-primary text-primary-foreground hover:brightness-110 transition-all shadow-lg shadow-primary/20"
              >
                <Plus className="w-3.5 h-3.5" />
                New event
              </button>
            </div>
          </div>

          {error && (
            <div className="bg-destructive/10 border border-destructive/30 rounded-2xl p-4 flex gap-3 items-center mb-6 shadow-sm">
              <AlertTriangle className="w-5 h-5 text-destructive shrink-0" />
              <p className="text-sm text-destructive font-bold">{error}</p>
            </div>
          )}
          {success && (
            <div className="bg-green-500/10 border border-green-500/30 rounded-2xl p-4 flex gap-3 items-center mb-6 shadow-sm animate-in fade-in slide-in-from-top-2">
              <CheckCircle2 className="w-5 h-5 text-green-500 shrink-0" />
              <p className="text-sm text-green-500 font-bold">{success}</p>
            </div>
          )}

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-10">
            <StatCard
              label="Live rooms"
              value={stats?.activeRooms}
              icon={Radio}
              accent="primary"
              loading={loading}
            />
            <StatCard
              label="Players now"
              value={stats?.playersOnlineNow}
              icon={Users}
              accent="foreground"
              loading={loading}
            />
            <StatCard
              label="Live events"
              value={stats?.liveEvents}
              icon={Zap}
              accent="foreground"
              loading={loading}
            />
            <StatCard
              label="Completed"
              value={stats?.completedCompetitions}
              icon={CheckCircle2}
              accent="foreground"
              loading={loading}
            />
          </div>

          <section className="mb-10">
            <div className="flex items-center gap-2 mb-4">
              <h2 className="font-display text-lg font-extrabold tracking-tight">
                Live now
              </h2>
              {liveRooms && liveRooms.length > 0 && (
                <span className="w-1.5 h-1.5 rounded-full bg-destructive live-pulse" />
              )}
            </div>

            {!loading && liveRooms && liveRooms.length === 0 && (
              <div className="bg-card border border-card-border border-dashed rounded-3xl p-8 text-center">
                <Radio className="w-8 h-8 text-muted-foreground mx-auto mb-2 opacity-50" />
                <p className="text-sm font-semibold text-muted-foreground">
                  No rooms in progress right now.
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  Rooms appear here the moment a player joins a live event.
                </p>
              </div>
            )}

            {loading && (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {[1, 2, 3].map((i) => (
                  <div
                    key={i}
                    className="bg-card border border-card-border rounded-3xl p-5 h-44 animate-pulse"
                  />
                ))}
              </div>
            )}

            {!loading && liveRooms && liveRooms.length > 0 && (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {liveRooms.map((room) => (
                  <LiveRoomTile key={room.competitionId} room={room} />
                ))}
              </div>
            )}
          </section>

          <section>
            <h2 className="font-display text-lg font-extrabold tracking-tight mb-4">
              Events
            </h2>

            {loading && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {[1, 2].map((i) => (
                  <div
                    key={i}
                    className="bg-card border border-card-border rounded-3xl p-5 h-40 animate-pulse"
                  />
                ))}
              </div>
            )}

            {!loading && events && events.length === 0 && (
              <div className="bg-card border border-card-border rounded-3xl p-10 text-center">
                <Trophy className="w-10 h-10 text-muted-foreground mx-auto mb-3" />
                <p className="font-bold text-foreground">No events yet</p>
                <p className="text-sm text-muted-foreground mt-1">
                  Create one to test the competition flow.
                </p>
              </div>
            )}

            {!loading && events && events.length > 0 && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {events.map((event) => (
                  <EventCard
                    key={event._id}
                    event={event}
                    onStatusChange={handleStatusChange}
                    onCancelSchedule={handleCancelSchedule}
                    onEdit={() => setEditingEvent(event)}
                    onDelete={handleDelete}
                    confirmingDelete={confirmDeleteId === event._id}
                    onRequestDelete={() => setConfirmDeleteId(event._id)}
                    onCancelDeleteRequest={() => setConfirmDeleteId(null)}
                    deleting={deletingId === event._id}
                    confirmingStatusTarget={
                      confirmStatusTarget?.id === event._id
                        ? confirmStatusTarget.status
                        : null
                    }
                    onRequestStatusChange={(status: AdminEvent["status"]) =>
                      setConfirmStatusTarget({ id: event._id, status })
                    }
                    onCancelStatusRequest={() => setConfirmStatusTarget(null)}
                    confirmingScheduleCancel={
                      confirmScheduleCancelId === event._id
                    }
                    onRequestScheduleCancel={() =>
                      setConfirmScheduleCancelId(event._id)
                    }
                    onCancelScheduleCancelRequest={() =>
                      setConfirmScheduleCancelId(null)
                    }
                  />
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </AdminShell>
  );
}

function StatCard({
  label,
  value,
  icon: Icon,
  accent,
  loading,
}: {
  label: string;
  value: number | undefined;
  icon: React.ComponentType<{ className?: string }>;
  accent: "primary" | "foreground";
  loading: boolean;
}) {
  return (
    <div className="bg-card border border-card-border rounded-3xl p-5 flex flex-col gap-3">
      <div
        className={cn(
          "w-9 h-9 rounded-xl flex items-center justify-center",
          accent === "primary"
            ? "bg-primary/15 text-primary"
            : "bg-secondary text-foreground",
        )}
      >
        <Icon className="w-4 h-4" />
      </div>
      <div>
        <p className="font-mono text-3xl font-bold tracking-tight tabular-nums">
          {loading || value === undefined ? "–" : value}
        </p>
        <p className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground mt-0.5">
          {label}
        </p>
      </div>
    </div>
  );
}

function LiveRoomTile({ room }: { room: LiveRoomSummary }) {
  const statusLabel = ROOM_STATUS_LABEL[room.status] ?? room.status;
  const isRunning = room.status === "ROUND_RUNNING";

  return (
    <div className="bg-card border border-card-border rounded-3xl p-5 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "w-2 h-2 rounded-full bg-destructive",
              isRunning && "live-pulse",
            )}
          />
          <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-destructive font-bold">
            Live
          </span>
        </div>
        <span className="text-[11px] font-mono text-muted-foreground tabular-nums">
          Round {room.currentRound || 1}/{room.totalRounds}
        </span>
      </div>
      <div>
        <h3 className="font-bold text-base leading-tight truncate">
          {room.eventName}
        </h3>
        <p className="text-xs text-muted-foreground mt-1">{statusLabel}</p>
      </div>
      {room.hostName && (
        <p className="flex items-center gap-1.5 text-[11px] font-semibold text-muted-foreground -mt-2">
          <Crown className="w-3 h-3 text-primary" />
          Created by {room.hostName}
        </p>
      )}
      <div className="flex items-center gap-1.5 flex-wrap">
        {room.participantNames.slice(0, 5).map((name) => (
          <span
            key={name}
            className="text-[11px] font-semibold bg-secondary/70 text-foreground px-2 py-1 rounded-full truncate max-w-25"
          >
            {name}
          </span>
        ))}
      </div>
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

function EventCard({
  event,
  onStatusChange,
  onCancelSchedule,
  onEdit,
  onDelete,
  confirmingDelete,
  onRequestDelete,
  onCancelDeleteRequest,
  deleting,
  confirmingStatusTarget,
  onRequestStatusChange,
  onCancelStatusRequest,
  confirmingScheduleCancel,
  onRequestScheduleCancel,
  onCancelScheduleCancelRequest,
}: any) {
  const schedule = event.scheduling
    ? getScheduleStatus(event.scheduling, Date.now())
    : null;

  return (
    <div className="bg-card border border-card-border rounded-3xl overflow-hidden flex flex-col">
      <Link
        href={`/admin/events/${event._id}`}
        className="h-28 relative bg-secondary/40 overflow-hidden block group"
      >
        {event.imageUrls?.[0] ? (
          <img
            src={event.imageUrls[0]}
            alt=""
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center bg-linear-to-br from-primary/20 via-secondary/40 to-transparent">
            <Trophy className="w-8 h-8 text-muted-foreground opacity-40" />
          </div>
        )}
        <span
          className={cn(
            "absolute top-3 right-3 text-[10px] font-black uppercase tracking-widest px-2.5 py-1 rounded-md",
            STATUS_STYLES[event.status as keyof typeof STATUS_STYLES],
          )}
        >
          {event.status}
        </span>
        <div className="absolute top-3 left-3 flex items-center gap-1.5">
          <button
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onEdit();
            }}
            title="Edit event"
            className="w-7 h-7 rounded-full bg-background/80 backdrop-blur flex items-center justify-center hover:bg-background transition-colors"
          >
            <Pencil className="w-3.5 h-3.5 text-foreground" />
          </button>
          <button
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onRequestDelete();
            }}
            title="Delete event"
            className="w-7 h-7 rounded-full bg-background/80 backdrop-blur flex items-center justify-center hover:bg-destructive/20 transition-colors"
          >
            <Trash2 className="w-3.5 h-3.5 text-destructive" />
          </button>
        </div>
      </Link>

      <div className="p-5 flex flex-col gap-3 flex-1">
        {confirmingDelete ? (
          <div className="rounded-2xl border border-destructive/30 bg-destructive/10 p-4 space-y-3 animate-in fade-in">
            <p className="text-sm font-bold text-destructive">
              Delete "{event.name}"?
            </p>
            <p className="text-xs text-muted-foreground">
              This can't be undone. Rooms already completed under this event
              keep their results.
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => onDelete(event._id)}
                disabled={deleting}
                className="flex-1 py-2 rounded-xl text-[11px] font-black uppercase tracking-wider bg-destructive text-destructive-foreground hover:brightness-110 transition-all disabled:opacity-50"
              >
                {deleting ? "Deleting..." : "Yes, delete"}
              </button>
              <button
                onClick={onCancelDeleteRequest}
                disabled={deleting}
                className="flex-1 py-2 rounded-xl text-[11px] font-bold uppercase tracking-wider bg-secondary text-muted-foreground hover:bg-secondary/80 transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : confirmingStatusTarget ? (
          <div className="rounded-2xl border border-primary/30 bg-primary/10 p-4 space-y-3 animate-in fade-in">
            <p className="text-sm font-bold text-primary">
              Change status to {confirmingStatusTarget.toUpperCase()}?
            </p>
            <p className="text-xs text-muted-foreground">
              This will update how players interact with this event immediately.
            </p>
            <div className="flex gap-2">
              <button
                onClick={() =>
                  onStatusChange(event._id, confirmingStatusTarget)
                }
                className="flex-1 py-2 rounded-xl text-[11px] font-black uppercase tracking-wider bg-primary text-primary-foreground hover:brightness-110 transition-all"
              >
                Confirm
              </button>
              <button
                onClick={onCancelStatusRequest}
                className="flex-1 py-2 rounded-xl text-[11px] font-bold uppercase tracking-wider bg-secondary text-muted-foreground hover:bg-secondary/80 transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : confirmingScheduleCancel ? (
          <div className="rounded-2xl border border-destructive/30 bg-destructive/10 p-4 space-y-3 animate-in fade-in">
            <p className="text-sm font-bold text-destructive">
              Cancel this event's schedule?
            </p>
            <p className="text-xs text-muted-foreground">
              Scheduled automatic triggers for this event will be aborted.
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => onCancelSchedule(event._id)}
                className="flex-1 py-2 rounded-xl text-[11px] font-black uppercase tracking-wider bg-destructive text-destructive-foreground hover:brightness-110 transition-all"
              >
                Yes, cancel schedule
              </button>
              <button
                onClick={onCancelScheduleCancelRequest}
                className="flex-1 py-2 rounded-xl text-[11px] font-bold uppercase tracking-wider bg-secondary text-muted-foreground hover:bg-secondary/80 transition-colors"
              >
                Back
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="flex items-start justify-between gap-2">
              <div>
                <h3 className="text-lg font-bold tracking-tight truncate">
                  {event.name}
                </h3>
                <p className="text-xs text-muted-foreground mt-0.5 font-mono">
                  {event.exerciseName} · {event.rounds}×
                  {event.roundDurationSeconds}s · max {event.maxParticipants}
                </p>
              </div>
              <Link
                href={`/admin/events/${event._id}`}
                className="shrink-0 flex items-center gap-1 text-[10px] font-black uppercase tracking-wider text-primary hover:underline whitespace-nowrap"
              >
                Rooms
                <ArrowUpRight className="w-3 h-3" />
              </Link>
            </div>
            {event.description && (
              <p className="text-sm text-muted-foreground line-clamp-2">
                {event.description}
              </p>
            )}
            {event.scheduling && schedule && (
              <div className="flex items-center justify-between gap-2 bg-secondary/50 rounded-xl px-3 py-2">
                <div className="flex items-center gap-1.5 min-w-0">
                  <CalendarClock className="w-3.5 h-3.5 text-primary shrink-0" />
                  <span className="text-[11px] font-bold text-foreground truncate">
                    {formatInTimeZone(
                      event.scheduling.scheduledAt,
                      event.scheduling.timezone,
                    )}
                    {event.scheduling.scheduledEndAt &&
                      ` - ${formatTimeOnlyInTimeZone(
                        event.scheduling.scheduledEndAt,
                        event.scheduling.timezone,
                      )}`}{" "}
                    · {event.scheduling.phase.replace(/_/g, " ").toLowerCase()}
                  </span>
                </div>
                {!["COMPLETED", "CANCELLED", "POSTPONED"].includes(
                  event.scheduling.phase,
                ) && (
                  <button
                    onClick={onRequestScheduleCancel}
                    className="text-[10px] font-bold uppercase tracking-wider text-destructive hover:underline shrink-0"
                  >
                    Cancel
                  </button>
                )}
              </div>
            )}
            <div className="flex items-center gap-2 mt-auto pt-1">
              {(["draft", "live", "closed"] as const).map((status) => (
                <button
                  key={status}
                  onClick={() => onRequestStatusChange(status)}
                  disabled={event.status === status}
                  className={cn(
                    "flex-1 py-2 rounded-xl text-[11px] font-bold uppercase tracking-wider transition-colors",
                    event.status === status
                      ? "bg-foreground text-background cursor-default"
                      : "bg-secondary text-muted-foreground hover:bg-secondary/80",
                  )}
                >
                  {status}
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

const DEFAULT_EVENT_TIMEZONE = "Asia/Kolkata";

function minusMinutesLocal(localIso: string, minutes: number): string {
  const d = new Date(localIso);
  d.setMinutes(d.getMinutes() - minutes);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:00`;
}

function utcToLocalParts(
  isoUtc: string,
  timeZone: string,
): { date: string; time: string } {
  const dtf = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  const parts: Record<string, string> = {};
  for (const p of dtf.formatToParts(new Date(isoUtc))) {
    if (p.type !== "literal") parts[p.type] = p.value;
  }
  return {
    date: `${parts.year}-${parts.month}-${parts.day}`,
    time: `${parts.hour}:${parts.minute}`,
  };
}

function CreateEventView({
  event,
  onClose,
  onSaved,
}: {
  event?: AdminEvent;
  onClose: () => void;
  onSaved: (event: AdminEvent) => void;
}) {
  const isEditing = Boolean(event);

  const [name, setName] = useState(event?.name ?? "");
  const [exerciseId, setExerciseId] = useState(
    event?.exerciseId ?? exercises[0]?.id ?? "",
  );
  const [rounds, setRounds] = useState(event?.rounds ?? 2);
  const [roundDurationSeconds, setRoundDurationSeconds] = useState(
    event?.roundDurationSeconds ?? 60,
  );
  const [breakDurationSeconds, setBreakDurationSeconds] = useState(
    event?.breakDurationSeconds ?? 15,
  );
  const [maxParticipants, setMaxParticipants] = useState(
    event?.maxParticipants ?? 5,
  );
  // How many players a room needs before its host can start it early
  // (room:start) instead of waiting for it to fill to maxParticipants.
  // Distinct from scheduling's own minParticipants below, which governs a
  // *scheduled* event's auto-cancel/postpone check, not room start-early.
  const [roomMinParticipants, setRoomMinParticipants] = useState(
    event?.minParticipants ?? 2,
  );
  const [description, setDescription] = useState(event?.description ?? "");
  const [imageUrls, setImageUrls] = useState<string[]>(event?.imageUrls ?? []);
  const [status, setStatus] = useState<"draft" | "live">(
    event?.status === "draft" ? "draft" : "live",
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const existingSchedule = event?.scheduling;
  const existingStart = existingSchedule
    ? utcToLocalParts(existingSchedule.scheduledAt, existingSchedule.timezone)
    : null;
  const minutesBetween = (fromIso: string, toIso: string) =>
    Math.round(
      (new Date(toIso).getTime() - new Date(fromIso).getTime()) / 60000,
    );

  const existingEnd =
    existingSchedule && existingSchedule.scheduledEndAt
      ? utcToLocalParts(
          existingSchedule.scheduledEndAt,
          existingSchedule.timezone,
        )
      : null;

  const [isScheduled, setIsScheduled] = useState(Boolean(existingSchedule));
  const [scheduleDate, setScheduleDate] = useState(existingStart?.date ?? "");
  const [scheduleTime, setScheduleTime] = useState(
    existingStart?.time ?? "19:00",
  );
  const [scheduleEndTime, setScheduleEndTime] = useState(
    existingEnd?.time ?? "23:00",
  );
  const [registrationOpensBeforeMin, setRegistrationOpensBeforeMin] = useState(
    existingSchedule
      ? minutesBetween(
          existingSchedule.registrationOpensAt,
          existingSchedule.scheduledAt,
        )
      : 30,
  );
  const [registrationClosesBeforeMin, setRegistrationClosesBeforeMin] =
    useState(
      existingSchedule
        ? minutesBetween(
            existingSchedule.registrationClosesAt,
            existingSchedule.scheduledAt,
          )
        : 2,
    );
  const [minParticipants, setMinParticipants] = useState(
    existingSchedule?.minParticipants ?? 2,
  );
  const [onInsufficientParticipants, setOnInsufficientParticipants] = useState<
    "cancel" | "postpone"
  >(existingSchedule?.onInsufficientParticipants ?? "cancel");

  const selectedExercise = useMemo(
    () => exercises.find((e) => e.id === exerciseId),
    [exerciseId],
  );

  const schedulePreview = useMemo(() => {
    if (!isScheduled || !scheduleDate || !scheduleTime) return null;
    const scheduledAtLocal = `${scheduleDate}T${scheduleTime}:00`;
    const opensLocal = minusMinutesLocal(
      scheduledAtLocal,
      registrationOpensBeforeMin,
    );
    const closesLocal = minusMinutesLocal(
      scheduledAtLocal,
      registrationClosesBeforeMin,
    );
    const fmt = (iso: string) =>
      new Date(iso).toLocaleTimeString("en-IN", {
        hour: "numeric",
        minute: "2-digit",
        hour12: true,
      });
    const fmtDate = (iso: string) =>
      new Date(iso).toLocaleDateString("en-IN", {
        month: "short",
        day: "numeric",
      });
    const scheduledEndAtLocal = scheduleEndTime
      ? `${scheduleDate}T${scheduleEndTime}:00`
      : null;
    return {
      opensTime: fmt(opensLocal),
      opensDate: fmtDate(opensLocal),
      closesTime: fmt(closesLocal),
      startsTime: fmt(scheduledAtLocal),
      startsDate: fmtDate(scheduledAtLocal),
      endsTime: scheduledEndAtLocal ? fmt(scheduledEndAtLocal) : null,
    };
  }, [
    isScheduled,
    scheduleDate,
    scheduleTime,
    scheduleEndTime,
    registrationOpensBeforeMin,
    registrationClosesBeforeMin,
  ]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedExercise) return setError("Pick an exercise");
    if (isScheduled && !scheduleDate)
      return setError("Pick a date for the scheduled start");
    if (roomMinParticipants > maxParticipants)
      return setError("Minimum players can't exceed max player capacity");

    setSubmitting(true);
    setError(null);
    try {
      const scheduledAtLocal = isScheduled
        ? `${scheduleDate}T${scheduleTime}:00`
        : undefined;
      const payload = {
        name: name.trim(),
        exerciseId: selectedExercise.id,
        exerciseName: selectedExercise.name,
        exerciseMode: selectedExercise.mode,
        rounds,
        roundDurationSeconds,
        breakDurationSeconds,
        maxParticipants,
        minParticipants: roomMinParticipants,
        description: description.trim() || undefined,
        imageUrls,
        status,
        scheduling:
          isScheduled && scheduledAtLocal
            ? {
                scheduledAtLocal,
                scheduledEndAtLocal: scheduleEndTime
                  ? `${scheduleDate}T${scheduleEndTime}:00`
                  : undefined,
                registrationOpensAtLocal: minusMinutesLocal(
                  scheduledAtLocal,
                  registrationOpensBeforeMin,
                ),
                registrationClosesAtLocal: minusMinutesLocal(
                  scheduledAtLocal,
                  registrationClosesBeforeMin,
                ),
                timezone: DEFAULT_EVENT_TIMEZONE,
                minParticipants,
                onInsufficientParticipants,
              }
            : undefined,
      };

      const saved =
        isEditing && event
          ? await updateAdminEvent(event._id, payload)
          : await createAdminEvent(payload);
      onSaved(saved);
    } catch (err: any) {
      setError(
        err.message ||
          (isEditing ? "Could not save changes" : "Could not create event"),
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto pb-16 w-full animate-in fade-in slide-in-from-bottom-4 duration-300">
      <button
        onClick={onClose}
        className="flex items-center gap-2 text-xs font-black uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors mb-6 group bg-secondary/60 px-4 py-2 rounded-full w-fit"
      >
        <ArrowLeft className="w-3.5 h-3.5 transition-transform group-hover:-translate-x-1" />
        Back to Dashboard
      </button>

      <div className="mb-8">
        <p className="text-[10px] font-mono uppercase tracking-[0.25em] text-primary mb-1.5 font-bold">
          Event Management
        </p>
        <h1 className="font-display text-3xl md:text-4xl font-extrabold tracking-tight leading-tight">
          {isEditing ? "Edit Event" : "Create New Event"}
        </h1>
        <p className="text-sm text-muted-foreground mt-1.5">
          Configure competition rules, participant limits, and scheduling
          details.
        </p>
      </div>

      <form
        onSubmit={handleSubmit}
        className="space-y-8 bg-card border border-card-border p-6 md:p-10 rounded-[2.5rem] shadow-xl"
      >
        {/* Section 1: General Details */}
        <div className="space-y-6">
          <div className="border-b border-border/60 pb-3">
            <h2 className="text-sm font-black uppercase tracking-wider text-foreground">
              1. General Details
            </h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              Basic identification information for your event.
            </p>
          </div>

          <Field label="Event name">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Elite Push-Up Championship"
              className="w-full h-13 rounded-2xl border border-input bg-background px-4 font-semibold text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 transition-all"
              required
              minLength={3}
            />
          </Field>

          <Field label="Exercise category">
            <select
              value={exerciseId}
              onChange={(e) => setExerciseId(e.target.value)}
              className="w-full h-13 rounded-2xl border border-input bg-background px-4 font-semibold text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 transition-all cursor-pointer"
            >
              {exercises.map((ex) => (
                <option key={ex.id} value={ex.id}>
                  {ex.name} ({ex.mode})
                </option>
              ))}
            </select>
          </Field>

          <Field label="Cover images (optional, up to 3)">
            <CoverImagesUploader images={imageUrls} onChange={setImageUrls} />
          </Field>

          <Field label="Description (optional)">
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              maxLength={500}
              placeholder="Provide rules, guidelines, or extra details for participants..."
              className="w-full rounded-2xl border border-input bg-background px-4 py-3 font-medium text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 resize-none transition-all"
            />
          </Field>
        </div>

        {/* Section 2: Match Rules */}
        <div className="space-y-6 pt-4">
          <div className="border-b border-border/60 pb-3">
            <h2 className="text-sm font-black uppercase tracking-wider text-foreground">
              2. Match Rules & Structure
            </h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              Configure rounds, timing configurations, and capacity limits.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
            <Field label="Total rounds">
              <input
                type="number"
                min={1}
                max={10}
                value={rounds}
                onChange={(e) => setRounds(Number(e.target.value))}
                className="w-full h-13 rounded-2xl border border-input bg-background px-4 font-semibold text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 transition-all"
              />
            </Field>
            <Field label="Max player capacity">
              <input
                type="number"
                min={2}
                max={5}
                value={maxParticipants}
                onChange={(e) => setMaxParticipants(Number(e.target.value))}
                className="w-full h-13 rounded-2xl border border-input bg-background px-4 font-semibold text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 transition-all"
              />
            </Field>
            <Field label="Min players to start early">
              <input
                type="number"
                min={1}
                max={maxParticipants}
                value={roomMinParticipants}
                onChange={(e) => setRoomMinParticipants(Number(e.target.value))}
                className="w-full h-13 rounded-2xl border border-input bg-background px-4 font-semibold text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 transition-all"
              />
              <p className="text-[11px] text-muted-foreground mt-1.5">
                A room's host can start once this many players have joined,
                instead of waiting for all {maxParticipants}.
              </p>
            </Field>
            <Field label="Round duration (seconds)">
              <input
                type="number"
                min={10}
                max={600}
                value={roundDurationSeconds}
                onChange={(e) =>
                  setRoundDurationSeconds(Number(e.target.value))
                }
                className="w-full h-13 rounded-2xl border border-input bg-background px-4 font-semibold text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 transition-all"
              />
            </Field>
            <Field label="Break duration between rounds (seconds)">
              <input
                type="number"
                min={5}
                max={300}
                value={breakDurationSeconds}
                onChange={(e) =>
                  setBreakDurationSeconds(Number(e.target.value))
                }
                className="w-full h-13 rounded-2xl border border-input bg-background px-4 font-semibold text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 transition-all"
              />
            </Field>
          </div>

          <Field label="Initial publishing status">
            <div className="flex gap-3">
              {(["live", "draft"] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setStatus(s)}
                  className={cn(
                    "flex-1 py-3 rounded-2xl text-xs font-bold uppercase tracking-wider transition-all border",
                    status === s
                      ? "bg-foreground text-background border-foreground shadow-md"
                      : "bg-secondary/50 text-muted-foreground border-border hover:bg-secondary",
                  )}
                >
                  {s === "live" ? "🟢 Live Now (Visible)" : "📁 Save as Draft"}
                </button>
              ))}
            </div>
          </Field>
        </div>

        {/* Section 3: Scheduling */}
        <div className="border-t border-border pt-8">
          <div className="flex items-center gap-2.5 mb-2">
            <div className="w-8 h-8 rounded-xl bg-primary/15 text-primary flex items-center justify-center">
              <Clock className="w-4 h-4" />
            </div>
            <div>
              <h3 className="font-display text-base font-black tracking-tight text-foreground">
                3. Event Timing & Scheduling
              </h3>
              <p className="text-xs text-muted-foreground">
                Choose whether the event triggers right away or launches on a
                fixed calendar date.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 my-6">
            <button
              type="button"
              onClick={() => setIsScheduled(false)}
              className={cn(
                "text-left rounded-2xl border p-5 transition-all flex flex-col justify-between",
                !isScheduled
                  ? "border-primary bg-primary/10 shadow-sm ring-1 ring-primary/30"
                  : "border-input bg-background/50 hover:border-primary/40",
              )}
            >
              <div className="flex items-center gap-2.5 mb-2">
                <Zap
                  className={cn(
                    "w-5 h-5",
                    !isScheduled ? "text-primary" : "text-muted-foreground",
                  )}
                />
                <span className="text-sm font-extrabold uppercase tracking-wide">
                  Start Immediately
                </span>
              </div>
              <p className="text-xs text-muted-foreground leading-relaxed">
                The countdown sequence starts the instant your room capacity
                reaches full limit.
              </p>
            </button>

            <button
              type="button"
              onClick={() => setIsScheduled(true)}
              className={cn(
                "text-left rounded-2xl border p-5 transition-all flex flex-col justify-between",
                isScheduled
                  ? "border-primary bg-primary/10 shadow-sm ring-1 ring-primary/30"
                  : "border-input bg-background/50 hover:border-primary/40",
              )}
            >
              <div className="flex items-center gap-2.5 mb-2">
                <CalendarClock
                  className={cn(
                    "w-5 h-5",
                    isScheduled ? "text-primary" : "text-muted-foreground",
                  )}
                />
                <span className="text-sm font-extrabold uppercase tracking-wide">
                  Schedule For Later
                </span>
              </div>
              <p className="text-xs text-muted-foreground leading-relaxed">
                Locked to a strict date and time. It will not start early even
                if the room fills up completely.
              </p>
            </button>
          </div>

          {isScheduled && (
            <div className="rounded-3xl border border-primary/30 bg-primary/3 p-6 md:p-8 space-y-6 animate-in fade-in duration-300">
              {/* Part A: Start Date/Time */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-black uppercase tracking-wider text-primary">
                    A. Official Start Time
                  </span>
                  <span className="text-[11px] font-mono text-muted-foreground bg-secondary/80 px-2.5 py-1 rounded-full">
                    Timezone: Asia/Kolkata
                  </span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <Field label="Start date">
                    <input
                      type="date"
                      value={scheduleDate}
                      onChange={(e) => setScheduleDate(e.target.value)}
                      required={isScheduled}
                      className="w-full h-13 rounded-2xl border border-input bg-background px-4 font-semibold text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
                    />
                  </Field>
                  <Field label="Start time">
                    <input
                      type="time"
                      value={scheduleTime}
                      onChange={(e) => setScheduleTime(e.target.value)}
                      required={isScheduled}
                      className="w-full h-13 rounded-2xl border border-input bg-background px-4 font-semibold text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
                    />
                  </Field>
                  <Field label="End time">
                    <input
                      type="time"
                      value={scheduleEndTime}
                      onChange={(e) => setScheduleEndTime(e.target.value)}
                      className="w-full h-13 rounded-2xl border border-input bg-background px-4 font-semibold text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
                    />
                  </Field>
                </div>
                <p className="text-[11px] text-muted-foreground">
                  When the event is expected to wrap up - shown to participants
                  as "{scheduleTime || "7:00 PM"} -{" "}
                  {scheduleEndTime || "11:00 PM"}". Doesn't cut rounds off
                  early.
                </p>
              </div>

              {/* Part B: Registration Window with instant clock calculations */}
              <div className="space-y-3 pt-2">
                <div>
                  <span className="text-xs font-black uppercase tracking-wider text-primary">
                    B. Registration Window Duration
                  </span>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Specify how early players can join before the main event
                    kicks off.
                  </p>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <Field label="Open registration (Minutes before start)">
                      <input
                        type="number"
                        min={1}
                        max={1440}
                        value={registrationOpensBeforeMin}
                        onChange={(e) =>
                          setRegistrationOpensBeforeMin(Number(e.target.value))
                        }
                        className="w-full h-13 rounded-2xl border border-input bg-background px-4 font-semibold text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
                      />
                    </Field>
                    {schedulePreview && (
                      <p className="text-[11px] text-primary font-bold mt-1.5 flex items-center gap-1">
                        <Clock className="w-3 h-3" /> Opens at:{" "}
                        {schedulePreview.opensTime} ({schedulePreview.opensDate}
                        )
                      </p>
                    )}
                  </div>

                  <div>
                    <Field label="Close registration (Minutes before start)">
                      <input
                        type="number"
                        min={0}
                        max={registrationOpensBeforeMin}
                        value={registrationClosesBeforeMin}
                        onChange={(e) =>
                          setRegistrationClosesBeforeMin(Number(e.target.value))
                        }
                        className="w-full h-13 rounded-2xl border border-input bg-background px-4 font-semibold text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
                      />
                    </Field>
                    {schedulePreview && (
                      <p className="text-[11px] text-destructive font-bold mt-1.5 flex items-center gap-1">
                        <Clock className="w-3 h-3" /> Closes at:{" "}
                        {schedulePreview.closesTime}
                      </p>
                    )}
                  </div>
                </div>
              </div>

              {/* Part C: Low Participant Rule */}
              <div className="space-y-3 pt-2">
                <div>
                  <span className="text-xs font-black uppercase tracking-wider text-primary">
                    C. Insufficient Turnout Handling
                  </span>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    What should happen if fewer players register than required?
                  </p>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <Field label="Minimum players required">
                    <input
                      type="number"
                      min={1}
                      max={maxParticipants}
                      value={minParticipants}
                      onChange={(e) =>
                        setMinParticipants(Number(e.target.value))
                      }
                      className="w-full h-13 rounded-2xl border border-input bg-background px-4 font-semibold text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
                    />
                  </Field>
                  <Field label="Action on low turnout">
                    <select
                      value={onInsufficientParticipants}
                      onChange={(e) =>
                        setOnInsufficientParticipants(
                          e.target.value as "cancel" | "postpone",
                        )
                      }
                      className="w-full h-13 rounded-2xl border border-input bg-background px-4 font-semibold text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 cursor-pointer"
                    >
                      <option value="cancel">
                        Cancel the event automatically
                      </option>
                      <option value="postpone">Mark event as postponed</option>
                    </select>
                  </Field>
                </div>
              </div>

              {/* Visual Schedule Timeline Card */}
              {schedulePreview && (
                <div className="rounded-2xl bg-background border border-primary/20 p-5 shadow-sm mt-4">
                  <div className="flex items-center gap-2 mb-3">
                    <Info className="w-4 h-4 text-primary shrink-0" />
                    <p className="text-xs font-black uppercase tracking-wider text-foreground">
                      Participant Timeline Preview
                    </p>
                  </div>
                  <div
                    className={cn(
                      "grid gap-2 text-center pt-2 border-t border-border/60",
                      schedulePreview.endsTime ? "grid-cols-4" : "grid-cols-3",
                    )}
                  >
                    <div className="flex flex-col items-center p-2 rounded-xl bg-secondary/30">
                      <span className="text-[10px] font-bold uppercase text-muted-foreground mb-1">
                        Registration Opens
                      </span>
                      <span className="font-mono font-bold text-xs text-foreground">
                        {schedulePreview.opensTime}
                      </span>
                    </div>
                    <div className="flex flex-col items-center p-2 rounded-xl bg-secondary/30">
                      <span className="text-[10px] font-bold uppercase text-muted-foreground mb-1">
                        Registration Closes
                      </span>
                      <span className="font-mono font-bold text-xs text-destructive">
                        {schedulePreview.closesTime}
                      </span>
                    </div>
                    <div className="flex flex-col items-center p-2 rounded-xl bg-primary/15">
                      <span className="text-[10px] font-bold uppercase text-primary mb-1 flex items-center gap-1">
                        <Rocket className="w-3 h-3" /> Event Start
                      </span>
                      <span className="font-mono font-black text-xs text-primary">
                        {schedulePreview.startsTime}
                      </span>
                    </div>
                    {schedulePreview.endsTime && (
                      <div className="flex flex-col items-center p-2 rounded-xl bg-primary/15">
                        <span className="text-[10px] font-bold uppercase text-primary mb-1 flex items-center gap-1">
                          <Clock className="w-3 h-3" /> Event Ends
                        </span>
                        <span className="font-mono font-black text-xs text-primary">
                          {schedulePreview.endsTime}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {error && (
          <div className="bg-destructive/10 border border-destructive/30 rounded-2xl p-4 flex gap-3 items-center">
            <AlertTriangle className="w-5 h-5 text-destructive shrink-0" />
            <p className="text-sm text-destructive font-bold">{error}</p>
          </div>
        )}

        <div className="pt-4">
          <button
            type="submit"
            disabled={submitting}
            className="w-full bg-primary text-primary-foreground py-4.5 rounded-2xl font-black uppercase tracking-wider hover:brightness-110 active:scale-[0.99] transition-all shadow-xl shadow-primary/25 disabled:opacity-50 text-sm flex items-center justify-center gap-2 cursor-pointer"
          >
            {submitting ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin" />
                {isEditing ? "Saving Changes..." : "Creating Event..."}
              </>
            ) : (
              <>
                <Check className="w-4 h-4" />
                {isEditing ? "Save Event Changes" : "Create Event Now"}
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}

const MAX_EVENT_IMAGES = 3;

/**
 * Up to MAX_EVENT_IMAGES cover / advertising images for an event. Each pick
 * uploads straight to Cloudinary via a signed request (see
 * lib/eventImageStore.ts) - the file never round-trips through this app's
 * own state, only the resulting secure URL does. Images the admin removes
 * before saving are best-effort deleted from Cloudinary right away so
 * nothing orphaned piles up from abandoned uploads.
 */
function CoverImagesUploader({
  images,
  onChange,
}: {
  images: string[];
  onChange: (urls: string[]) => void;
}) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Tracks the Cloudinary publicId for images uploaded *this session* so a
  // "remove" click can also clean them up server-side. Pre-existing images
  // loaded from a saved event aren't in here - we only ever persisted their
  // URL, so removing one just drops it from the array.
  const [publicIds, setPublicIds] = useState<Record<string, string>>({});
  const inputRef = React.useRef<HTMLInputElement>(null);

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const remaining = MAX_EVENT_IMAGES - images.length;
    const toUpload = Array.from(files).slice(0, remaining);
    if (toUpload.length === 0) return;

    setUploading(true);
    setError(null);
    try {
      let current = images;
      for (const file of toUpload) {
        const uploaded = await uploadEventImage(file);
        setPublicIds((prev) => ({
          ...prev,
          [uploaded.url]: uploaded.publicId,
        }));
        current = [...current, uploaded.url];
        onChange(current);
      }
    } catch (err: any) {
      if (err instanceof EventImageUploadsDisabledError) {
        setError("Cover image uploads aren't configured on this server.");
      } else {
        setError(err.message || "Upload failed - please try again");
      }
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const handleRemove = (url: string) => {
    const publicId = publicIds[url];
    if (publicId) deleteEventImage(publicId);
    onChange(images.filter((u) => u !== url));
  };

  return (
    <div>
      <div className="grid grid-cols-3 gap-3">
        {images.map((url) => (
          <div
            key={url}
            className="relative h-24 rounded-2xl overflow-hidden bg-secondary/40 border border-card-border shadow-inner group"
          >
            <img src={url} alt="Cover" className="w-full h-full object-cover" />
            <button
              type="button"
              onClick={() => handleRemove(url)}
              className="absolute top-1.5 right-1.5 w-6 h-6 rounded-full bg-black/60 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
              aria-label="Remove image"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}

        {images.length < MAX_EVENT_IMAGES && (
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={uploading}
            className="h-24 rounded-2xl border-2 border-dashed border-input flex flex-col items-center justify-center gap-1 text-muted-foreground hover:border-primary hover:text-primary transition-colors disabled:opacity-60"
          >
            {uploading ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <>
                <Upload className="w-4 h-4" />
                <span className="text-[10px] font-bold uppercase tracking-wider">
                  Add image
                </span>
              </>
            )}
          </button>
        )}
      </div>

      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        multiple
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
      />

      <p className="mt-2 text-[11px] text-muted-foreground">
        {images.length}/{MAX_EVENT_IMAGES} images - used for the event banner
        and advertising.
      </p>
      {error && (
        <p className="mt-1 text-[11px] font-semibold text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-xs font-extrabold uppercase tracking-[.12em] text-muted-foreground mb-2">
        {label}
      </label>
      {children}
    </div>
  );
}
