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
  fetchAdminEvents,
  fetchAdminStats,
  fetchLiveRooms,
  getAdminToken,
  setAdminEventStatus,
} from "@/lib/adminApi";
import {
  AlertTriangle,
  Image as ImageIcon,
  Plus,
  RefreshCw,
  Trophy,
  Users,
  Radio,
  Timer,
  X,
  Zap,
  CheckCircle2,
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
  const [showCreate, setShowCreate] = useState(false);

  useEffect(() => {
    if (!getAdminToken()) {
      setLocation("/admin/login");
      return;
    }
    void loadAll(true);
    // The "Live Now" board is the operational heart of this page - keep it
    // fresh without the admin having to think about refreshing.
    const interval = window.setInterval(() => void loadAll(false), 5000);
    return () => window.clearInterval(interval);
  }, []);

  const loadAll = async (showSpinner: boolean) => {
    if (showSpinner) setLoading(true);
    try {
      const [s, rooms, evts] = await Promise.all([fetchAdminStats(), fetchLiveRooms(), fetchAdminEvents()]);
      setStats(s);
      setLiveRooms(rooms);
      setEvents(evts);
      setError(null);
    } catch (err: any) {
      const message = err.message || "Could not load dashboard data";
      setError(message);
      if (message.toLowerCase().includes("session") || message.toLowerCase().includes("token")) {
        clearAdminSession();
        setLocation("/admin/login");
      }
    } finally {
      if (showSpinner) setLoading(false);
    }
  };

  const handleStatusChange = async (id: string, status: AdminEvent["status"]) => {
    try {
      const updated = await setAdminEventStatus(id, status);
      setEvents((prev) => prev?.map((e) => (e._id === id ? updated : e)) ?? prev);
    } catch (err: any) {
      setError(err.message || "Could not update event status");
    }
  };

  return (
    <AdminShell>
      <div className="flex items-start justify-between flex-wrap gap-3 mb-8">
        <div>
          <p className="text-[10px] font-mono uppercase tracking-[0.25em] text-primary mb-1.5">Overview</p>
          <h1 className="font-display text-3xl md:text-[2.25rem] font-extrabold tracking-tight leading-none">
            Control room
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => loadAll(true)}
            disabled={loading}
            data-testid="button-refresh-admin"
            className="flex items-center gap-2 px-4 py-2.5 rounded-full text-xs font-bold uppercase tracking-wider bg-secondary text-muted-foreground hover:bg-secondary/80 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={loading ? "w-3.5 h-3.5 animate-spin" : "w-3.5 h-3.5"} />
            Refresh
          </button>
          <button
            onClick={() => setShowCreate(true)}
            data-testid="button-open-create-event"
            className="flex items-center gap-2 px-4 py-2.5 rounded-full text-xs font-black uppercase tracking-wider bg-primary text-primary-foreground hover:brightness-110 transition-all shadow-lg shadow-primary/20"
          >
            <Plus className="w-3.5 h-3.5" />
            New event
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-destructive/10 border border-destructive/30 rounded-2xl p-4 flex gap-3 items-start mb-6">
          <AlertTriangle className="w-5 h-5 text-destructive shrink-0 mt-0.5" />
          <p className="text-sm text-destructive font-semibold">{error}</p>
        </div>
      )}

      {/* Stat strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-10">
        <StatCard label="Live rooms" value={stats?.activeRooms} icon={Radio} accent="primary" loading={loading} />
        <StatCard label="Players now" value={stats?.playersOnlineNow} icon={Users} accent="foreground" loading={loading} />
        <StatCard label="Live events" value={stats?.liveEvents} icon={Zap} accent="foreground" loading={loading} />
        <StatCard
          label="Completed"
          value={stats?.completedCompetitions}
          icon={CheckCircle2}
          accent="foreground"
          loading={loading}
        />
      </div>

      {/* Live Now board - the signature element of this dashboard */}
      <section className="mb-10">
        <div className="flex items-center gap-2 mb-4">
          <h2 className="font-display text-lg font-extrabold tracking-tight">Live now</h2>
          {liveRooms && liveRooms.length > 0 && (
            <span className="w-1.5 h-1.5 rounded-full bg-destructive live-pulse" />
          )}
        </div>

        {!loading && liveRooms && liveRooms.length === 0 && (
          <div className="bg-card border border-card-border border-dashed rounded-3xl p-8 text-center">
            <Radio className="w-8 h-8 text-muted-foreground mx-auto mb-2 opacity-50" />
            <p className="text-sm font-semibold text-muted-foreground">No rooms in progress right now.</p>
            <p className="text-xs text-muted-foreground mt-1">
              Rooms appear here the moment a player joins a live event.
            </p>
          </div>
        )}

        {loading && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {[1, 2, 3].map((i) => (
              <div key={i} className="bg-card border border-card-border rounded-3xl p-5 h-44 animate-pulse" />
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

      {/* Events management */}
      <section>
        <h2 className="font-display text-lg font-extrabold tracking-tight mb-4">Events</h2>

        {loading && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[1, 2].map((i) => (
              <div key={i} className="bg-card border border-card-border rounded-3xl p-5 h-40 animate-pulse" />
            ))}
          </div>
        )}

        {!loading && events && events.length === 0 && (
          <div className="bg-card border border-card-border rounded-3xl p-10 text-center">
            <Trophy className="w-10 h-10 text-muted-foreground mx-auto mb-3" />
            <p className="font-bold text-foreground">No events yet</p>
            <p className="text-sm text-muted-foreground mt-1">Create one to test the competition flow.</p>
          </div>
        )}

        {!loading && events && events.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {events.map((event) => (
              <EventCard key={event._id} event={event} onStatusChange={handleStatusChange} />
            ))}
          </div>
        )}
      </section>

      {showCreate && (
        <CreateEventModal
          onClose={() => setShowCreate(false)}
          onCreated={(event) => {
            setEvents((prev) => (prev ? [event, ...prev] : [event]));
            setShowCreate(false);
          }}
        />
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
          accent === "primary" ? "bg-primary/15 text-primary" : "bg-secondary text-foreground",
        )}
      >
        <Icon className="w-4 h-4" />
      </div>
      <div>
        <p className="font-mono text-3xl font-bold tracking-tight tabular-nums">
          {loading || value === undefined ? "–" : value}
        </p>
        <p className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground mt-0.5">{label}</p>
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
          <span className={cn("w-2 h-2 rounded-full bg-destructive", isRunning && "live-pulse")} />
          <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-destructive font-bold">Live</span>
        </div>
        <span className="text-[11px] font-mono text-muted-foreground tabular-nums">
          Round {room.currentRound || 1}/{room.totalRounds}
        </span>
      </div>

      <div>
        <h3 className="font-bold text-base leading-tight truncate">{room.eventName}</h3>
        <p className="text-xs text-muted-foreground mt-1">{statusLabel}</p>
      </div>

      <div className="flex items-center gap-1.5 flex-wrap">
        {room.participantNames.slice(0, 5).map((name) => (
          <span
            key={name}
            className="text-[11px] font-semibold bg-secondary/70 text-foreground px-2 py-1 rounded-full truncate max-w-[100px]"
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
          data-testid={`button-watch-${room.competitionId}`}
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
}: {
  event: AdminEvent;
  onStatusChange: (id: string, status: AdminEvent["status"]) => void;
}) {
  return (
    <div className="bg-card border border-card-border rounded-3xl overflow-hidden flex flex-col">
      <div className="h-28 relative bg-secondary/40 overflow-hidden">
        {event.imageUrl ? (
          <img src={event.imageUrl} alt="" className="w-full h-full object-cover" />
        ) : (
          <div className="w-full h-full flex items-center justify-center bg-gradient-to-br from-primary/20 via-secondary/40 to-transparent">
            <Trophy className="w-8 h-8 text-muted-foreground opacity-40" />
          </div>
        )}
        <span
          className={cn(
            "absolute top-3 right-3 text-[10px] font-black uppercase tracking-widest px-2.5 py-1 rounded-md",
            STATUS_STYLES[event.status],
          )}
        >
          {event.status}
        </span>
      </div>

      <div className="p-5 flex flex-col gap-3 flex-1">
        <div>
          <h3 className="text-lg font-bold tracking-tight truncate">{event.name}</h3>
          <p className="text-xs text-muted-foreground mt-0.5 font-mono">
            {event.exerciseName} · {event.rounds}×{event.roundDurationSeconds}s · max {event.maxParticipants}
          </p>
        </div>

        {event.description && <p className="text-sm text-muted-foreground line-clamp-2">{event.description}</p>}

        <div className="flex items-center gap-2 mt-auto pt-1">
          {(["draft", "live", "closed"] as const).map((status) => (
            <button
              key={status}
              onClick={() => onStatusChange(event._id, status)}
              disabled={event.status === status}
              data-testid={`button-set-status-${status}-${event._id}`}
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
      </div>
    </div>
  );
}

function CreateEventModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (event: AdminEvent) => void;
}) {
  const [name, setName] = useState("");
  const [exerciseId, setExerciseId] = useState(exercises[0]?.id ?? "");
  const [rounds, setRounds] = useState(2);
  const [roundDurationSeconds, setRoundDurationSeconds] = useState(60);
  const [breakDurationSeconds, setBreakDurationSeconds] = useState(15);
  const [maxParticipants, setMaxParticipants] = useState(5);
  const [description, setDescription] = useState("");
  const [imageUrl, setImageUrl] = useState("");
  const [status, setStatus] = useState<"draft" | "live">("live");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedExercise = useMemo(() => exercises.find((e) => e.id === exerciseId), [exerciseId]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedExercise) {
      setError("Pick an exercise");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const event = await createAdminEvent({
        name: name.trim(),
        exerciseId: selectedExercise.id,
        exerciseName: selectedExercise.name,
        exerciseMode: selectedExercise.mode,
        rounds,
        roundDurationSeconds,
        breakDurationSeconds,
        maxParticipants,
        description: description.trim() || undefined,
        imageUrl: imageUrl.trim() || undefined,
        status,
      });
      onCreated(event);
    } catch (err: any) {
      setError(err.message || "Could not create event");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm p-0 sm:p-4">
      <div className="bg-card border border-card-border rounded-t-4xl sm:rounded-4xl w-full sm:max-w-lg max-h-[90dvh] overflow-y-auto p-6 md:p-8 shadow-2xl">
        <div className="flex items-center justify-between mb-6">
          <h2 className="font-display text-xl font-black tracking-tight">New event</h2>
          <button
            onClick={onClose}
            data-testid="button-close-create-event"
            className="p-2 rounded-full bg-secondary hover:bg-secondary/80 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <Field label="Event name">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              data-testid="input-event-name"
              placeholder="e.g. Push-Up Championship"
              className="w-full h-12 rounded-2xl border border-input bg-background px-4 font-semibold outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
              required
              minLength={3}
            />
          </Field>

          <Field label="Exercise">
            <select
              value={exerciseId}
              onChange={(e) => setExerciseId(e.target.value)}
              data-testid="select-exercise"
              className="w-full h-12 rounded-2xl border border-input bg-background px-4 font-semibold outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
            >
              {exercises.map((ex) => (
                <option key={ex.id} value={ex.id}>
                  {ex.name} ({ex.mode})
                </option>
              ))}
            </select>
          </Field>

          <Field label="Cover image URL (optional)">
            <div className="relative">
              <ImageIcon className="w-4 h-4 text-muted-foreground absolute left-4 top-1/2 -translate-y-1/2" />
              <input
                value={imageUrl}
                onChange={(e) => setImageUrl(e.target.value)}
                data-testid="input-image-url"
                placeholder="https://..."
                className="w-full h-12 rounded-2xl border border-input bg-background pl-10 pr-4 font-medium outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
              />
            </div>
            {imageUrl.trim() && (
              <div className="mt-2 h-24 rounded-xl overflow-hidden bg-secondary/40 border border-card-border">
                <img
                  src={imageUrl.trim()}
                  alt="Preview"
                  className="w-full h-full object-cover"
                  onError={(e) => ((e.target as HTMLImageElement).style.display = "none")}
                />
              </div>
            )}
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Rounds">
              <input
                type="number"
                min={1}
                max={10}
                value={rounds}
                onChange={(e) => setRounds(Number(e.target.value))}
                data-testid="input-rounds"
                className="w-full h-12 rounded-2xl border border-input bg-background px-4 font-semibold outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
              />
            </Field>
            <Field label="Max players">
              <input
                type="number"
                min={2}
                max={5}
                value={maxParticipants}
                onChange={(e) => setMaxParticipants(Number(e.target.value))}
                data-testid="input-max-participants"
                className="w-full h-12 rounded-2xl border border-input bg-background px-4 font-semibold outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
              />
            </Field>
            <Field label="Round duration (s)">
              <input
                type="number"
                min={10}
                max={600}
                value={roundDurationSeconds}
                onChange={(e) => setRoundDurationSeconds(Number(e.target.value))}
                data-testid="input-round-duration"
                className="w-full h-12 rounded-2xl border border-input bg-background px-4 font-semibold outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
              />
            </Field>
            <Field label="Break duration (s)">
              <input
                type="number"
                min={5}
                max={300}
                value={breakDurationSeconds}
                onChange={(e) => setBreakDurationSeconds(Number(e.target.value))}
                data-testid="input-break-duration"
                className="w-full h-12 rounded-2xl border border-input bg-background px-4 font-semibold outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
              />
            </Field>
          </div>

          <Field label="Description (optional)">
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              data-testid="input-description"
              rows={2}
              maxLength={500}
              className="w-full rounded-2xl border border-input bg-background px-4 py-3 font-medium outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 resize-none"
            />
          </Field>

          <Field label="Publish as">
            <div className="flex gap-2">
              {(["live", "draft"] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setStatus(s)}
                  data-testid={`button-publish-${s}`}
                  className={cn(
                    "flex-1 py-2.5 rounded-xl text-xs font-bold uppercase tracking-wider transition-colors",
                    status === s ? "bg-foreground text-background" : "bg-secondary text-muted-foreground",
                  )}
                >
                  {s === "live" ? "Live now" : "Draft"}
                </button>
              ))}
            </div>
          </Field>

          {error && (
            <div className="bg-destructive/10 border border-destructive/30 rounded-2xl p-4 flex gap-2.5 items-start">
              <AlertTriangle className="w-4 h-4 text-destructive shrink-0 mt-0.5" />
              <p className="text-sm text-destructive font-semibold">{error}</p>
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            data-testid="button-submit-create-event"
            className="w-full bg-primary text-primary-foreground py-4 rounded-2xl font-black uppercase tracking-wider hover:brightness-110 active:scale-[0.98] transition-all shadow-xl shadow-primary/20 disabled:opacity-50"
          >
            {submitting ? "Creating..." : "Create event"}
          </button>
        </form>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-bold uppercase tracking-[.16em] text-muted-foreground mb-2">
        {label}
      </label>
      {children}
    </div>
  );
}
