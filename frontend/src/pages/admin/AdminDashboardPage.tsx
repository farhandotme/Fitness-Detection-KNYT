import React, { useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "wouter";
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
  Activity,
  AlertTriangle,
  Calendar,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  Dumbbell,
  Image as ImageIcon,
  Info,
  LayoutGrid,
  PlayCircle,
  Plus,
  Radio,
  RefreshCw,
  Settings2,
  Timer,
  Trophy,
  Users,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";

const STATUS_STYLES: Record<AdminEvent["status"], string> = {
  live: "bg-primary/15 text-primary border-primary/20",
  draft: "bg-secondary text-muted-foreground border-border",
  closed: "bg-destructive/10 text-destructive border-destructive/20",
};

const ROOM_STATUS_LABEL: Record<string, string> = {
  WAITING: "Waiting for players to join",
  FULL: "Room full, preparing to start",
  COUNTDOWN: "Starting countdown",
  ROUND_RUNNING: "Round in progress",
  ROUND_FINISHED: "Round finished, calculating scores",
  BREAK: "Players are on a break",
};

export function AdminDashboardPage() {
  const [, setLocation] = useLocation();

  const [stats, setStats] = useState<AdminStats | null>(null);
  const [liveRooms, setLiveRooms] = useState<LiveRoomSummary[] | null>(null);
  const [events, setEvents] = useState<AdminEvent[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Controls inline section visibility on this exact page
  const [showCreateSection, setShowCreateSection] = useState(false);
  const createSectionRef = useRef<HTMLDivElement>(null);

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
    try {
      const updated = await setAdminEventStatus(id, status);
      setEvents(
        (prev) => prev?.map((e) => (e._id === id ? updated : e)) ?? prev,
      );
    } catch (err: any) {
      setError(err.message || "Could not update event status");
    }
  };

  const toggleCreateSection = () => {
    setShowCreateSection((prev) => {
      const next = !prev;
      if (next) {
        setTimeout(() => {
          createSectionRef.current?.scrollIntoView({ behavior: "smooth" });
        }, 100);
      }
      return next;
    });
  };

  return (
    <AdminShell>
      {/* Page Header */}
      <div className="flex items-start justify-between flex-wrap gap-4 mb-8">
        <div>
          <div className="flex items-center gap-2 mb-1.5">
            <LayoutGrid className="w-4 h-4 text-primary" />
            <p className="text-[10px] font-mono uppercase tracking-[0.25em] text-primary">
              Overview
            </p>
          </div>
          <h1 className="font-display text-3xl md:text-[2.25rem] font-extrabold tracking-tight leading-none mb-2">
            Control Room
          </h1>
          <p className="text-sm text-muted-foreground max-w-xl">
            Monitor live competitions in real-time, manage your event roster,
            and track platform engagement metrics.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => loadAll(true)}
            disabled={loading}
            data-testid="button-refresh-admin"
            className="flex items-center gap-2 px-4 py-2.5 rounded-full text-xs font-bold uppercase tracking-wider bg-secondary text-muted-foreground hover:bg-secondary/80 transition-colors disabled:opacity-50"
          >
            <RefreshCw
              className={loading ? "w-3.5 h-3.5 animate-spin" : "w-3.5 h-3.5"}
            />
            Refresh
          </button>

          <button
            onClick={toggleCreateSection}
            data-testid="button-open-create-event"
            className={cn(
              "flex items-center gap-2 px-5 py-2.5 rounded-full text-xs font-black uppercase tracking-wider transition-all shadow-lg",
              showCreateSection
                ? "bg-secondary text-foreground hover:bg-secondary/80"
                : "bg-primary text-primary-foreground hover:brightness-110 shadow-primary/20",
            )}
          >
            {showCreateSection ? (
              <>
                <ChevronUp className="w-4 h-4" />
                Hide Form
              </>
            ) : (
              <>
                <Plus className="w-4 h-4" />
                New Event
              </>
            )}
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-destructive/10 border border-destructive/30 rounded-2xl p-4 flex gap-3 items-start mb-6 shadow-sm">
          <AlertTriangle className="w-5 h-5 text-destructive shrink-0 mt-0.5" />
          <div className="flex flex-col">
            <p className="text-sm text-destructive font-bold">System Error</p>
            <p className="text-sm text-destructive/80 font-medium">{error}</p>
          </div>
        </div>
      )}

      {/* Stat Strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-10">
        <StatCard
          label="Live Rooms"
          description="Active matches right now"
          value={stats?.activeRooms}
          icon={Radio}
          accent="primary"
          loading={loading}
        />
        <StatCard
          label="Players Online"
          description="Users currently competing"
          value={stats?.playersOnlineNow}
          icon={Users}
          accent="foreground"
          loading={loading}
        />
        <StatCard
          label="Live Events"
          description="Events open for joining"
          value={stats?.liveEvents}
          icon={Zap}
          accent="foreground"
          loading={loading}
        />
        <StatCard
          label="Matches Completed"
          description="Total historical matches"
          value={stats?.completedCompetitions}
          icon={CheckCircle2}
          accent="foreground"
          loading={loading}
        />
      </div>

      {/* INLINE SECTION: Create New Event Form */}
      {showCreateSection && (
        <div ref={createSectionRef} className="mb-12">
          <CreateEventInlineSection
            onClose={() => setShowCreateSection(false)}
            onCreated={(event) => {
              setEvents((prev) => (prev ? [event, ...prev] : [event]));
              setShowCreateSection(false);
            }}
          />
        </div>
      )}

      {/* Live Now Tracker */}
      <section className="mb-12">
        <div className="flex flex-col mb-6">
          <div className="flex items-center gap-2">
            <h2 className="font-display text-xl font-extrabold tracking-tight">
              Live Tracker
            </h2>
            {liveRooms && liveRooms.length > 0 && (
              <span className="flex h-2.5 w-2.5 relative">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-destructive opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-destructive"></span>
              </span>
            )}
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            Real-time feed of active competition rooms across all live events.
          </p>
        </div>

        {!loading && liveRooms && liveRooms.length === 0 && (
          <div className="bg-card border border-card-border border-dashed rounded-3xl p-10 text-center flex flex-col items-center justify-center">
            <div className="w-16 h-16 rounded-full bg-secondary/50 flex items-center justify-center mb-4">
              <Radio className="w-8 h-8 text-muted-foreground opacity-50" />
            </div>
            <p className="text-base font-bold text-foreground">
              No matches currently in progress
            </p>
            <p className="text-sm text-muted-foreground mt-2 max-w-sm">
              Rooms will automatically appear here the moment a player joins an
              active live event.
            </p>
          </div>
        )}

        {loading && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="bg-card border border-card-border rounded-3xl p-6 h-56 animate-pulse"
              />
            ))}
          </div>
        )}

        {!loading && liveRooms && liveRooms.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {liveRooms.map((room) => (
              <LiveRoomTile key={room.competitionId} room={room} />
            ))}
          </div>
        )}
      </section>

      {/* Events Roster Section */}
      <section>
        <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
          <div>
            <h2 className="font-display text-xl font-extrabold tracking-tight">
              Event Roster
            </h2>
            <p className="text-sm text-muted-foreground mt-1">
              Manage your catalog of challenges. Set events to "Live" to open
              them up for players.
            </p>
          </div>
          {!showCreateSection && (
            <button
              onClick={toggleCreateSection}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold uppercase tracking-wider bg-secondary hover:bg-secondary/80 text-foreground transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
              Add Event
            </button>
          )}
        </div>

        {loading && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            {[1, 2].map((i) => (
              <div
                key={i}
                className="bg-card border border-card-border rounded-3xl p-5 h-48 animate-pulse"
              />
            ))}
          </div>
        )}

        {!loading && events && events.length === 0 && (
          <div className="bg-card border border-card-border rounded-3xl p-12 text-center flex flex-col items-center">
            <div className="w-20 h-20 rounded-full bg-secondary flex items-center justify-center mb-5">
              <Trophy className="w-10 h-10 text-muted-foreground" />
            </div>
            <p className="font-bold text-lg text-foreground mb-2">
              No events created yet
            </p>
            <p className="text-sm text-muted-foreground max-w-md mb-6">
              Create an event to define the rules, exercises, and round
              structures for your players to compete in.
            </p>
            <button
              onClick={toggleCreateSection}
              className="px-6 py-3 rounded-full text-sm font-bold bg-primary text-primary-foreground hover:brightness-110 transition-all shadow-lg"
            >
              Create Your First Event
            </button>
          </div>
        )}

        {!loading && events && events.length > 0 && (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
            {events.map((event) => (
              <EventCard
                key={event._id}
                event={event}
                onStatusChange={handleStatusChange}
              />
            ))}
          </div>
        )}
      </section>
    </AdminShell>
  );
}

// ==========================================
// INLINE CREATE EVENT SECTION (On same page)
// ==========================================

function CreateEventInlineSection({
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

  const selectedExercise = useMemo(
    () => exercises.find((e) => e.id === exerciseId),
    [exerciseId],
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedExercise) {
      setError("Please select a valid exercise from the list.");
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
      setError(err.message || "Failed to create the event. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="bg-card border-2 border-primary/30 rounded-3xl p-6 md:p-8 shadow-xl relative overflow-hidden">
      {/* Decorative Accent Line */}
      <div className="absolute top-0 left-0 right-0 h-1.5 bg-linear-to-r from-primary via-primary/50 to-secondary" />

      {/* Section Header */}
      <div className="flex items-center justify-between pb-6 mb-6 border-b border-border">
        <div>
          <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-primary font-bold">
            Inline Action
          </span>
          <h2 className="font-display text-2xl font-black tracking-tight mt-0.5">
            Create New Event
          </h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="px-4 py-2 rounded-xl text-xs font-bold uppercase tracking-wider bg-secondary hover:bg-secondary/80 text-muted-foreground hover:text-foreground transition-colors"
        >
          Cancel
        </button>
      </div>

      <form onSubmit={handleSubmit} className="space-y-8">
        {/* Section 1: Basic Info */}
        <section>
          <div className="flex items-center gap-2 mb-3">
            <Info className="w-4 h-4 text-primary" />
            <h3 className="text-xs font-bold uppercase tracking-wider text-foreground">
              Basic Details
            </h3>
          </div>
          <div className="space-y-5 bg-secondary/10 p-5 rounded-2xl border border-border/50">
            <Field
              label="Event Name"
              helperText="A catchy title players will see on the lobby screen."
            >
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                data-testid="input-event-name"
                placeholder="e.g. Weekend Push-Up Challenge"
                className="w-full h-12 rounded-xl border border-input bg-background px-4 font-semibold outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all"
                required
                minLength={3}
              />
            </Field>

            <Field
              label="Description (Optional)"
              helperText="Briefly explain the rules or theme of this event."
            >
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                data-testid="input-description"
                placeholder="Join us for a test of endurance..."
                rows={2}
                maxLength={500}
                className="w-full rounded-xl border border-input bg-background px-4 py-3 font-medium outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 resize-none transition-all"
              />
            </Field>

            <Field
              label="Cover Image URL (Optional)"
              helperText="Provide a public URL to an image. Leave blank for default cover."
            >
              <div className="relative">
                <ImageIcon className="w-4 h-4 text-muted-foreground absolute left-4 top-1/2 -translate-y-1/2" />
                <input
                  value={imageUrl}
                  onChange={(e) => setImageUrl(e.target.value)}
                  data-testid="input-image-url"
                  placeholder="https://example.com/image.png"
                  className="w-full h-12 rounded-xl border border-input bg-background pl-10 pr-4 font-medium outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all"
                />
              </div>
            </Field>
          </div>
        </section>

        {/* Section 2: Game Setup */}
        <section>
          <div className="flex items-center gap-2 mb-3">
            <Settings2 className="w-4 h-4 text-primary" />
            <h3 className="text-xs font-bold uppercase tracking-wider text-foreground">
              Game Setup & Rules
            </h3>
          </div>
          <div className="space-y-5 bg-secondary/10 p-5 rounded-2xl border border-border/50">
            <Field
              label="Exercise Type"
              helperText="The pose or movement the AI will detect."
            >
              <select
                value={exerciseId}
                onChange={(e) => setExerciseId(e.target.value)}
                data-testid="select-exercise"
                className="w-full h-12 rounded-xl border border-input bg-background px-4 font-semibold outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all"
              >
                {exercises.map((ex) => (
                  <option key={ex.id} value={ex.id}>
                    {ex.name} (Tracks {ex.mode})
                  </option>
                ))}
              </select>
            </Field>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <Field label="Rounds" helperText="Rounds per match">
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={rounds}
                  onChange={(e) => setRounds(Number(e.target.value))}
                  data-testid="input-rounds"
                  className="w-full h-12 rounded-xl border border-input bg-background px-4 font-semibold outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all"
                />
              </Field>
              <Field label="Max Players" helperText="Players per room (2-5)">
                <input
                  type="number"
                  min={2}
                  max={5}
                  value={maxParticipants}
                  onChange={(e) => setMaxParticipants(Number(e.target.value))}
                  data-testid="input-max-participants"
                  className="w-full h-12 rounded-xl border border-input bg-background px-4 font-semibold outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all"
                />
              </Field>
              <Field label="Round Duration" helperText="Duration (seconds)">
                <input
                  type="number"
                  min={10}
                  max={600}
                  value={roundDurationSeconds}
                  onChange={(e) =>
                    setRoundDurationSeconds(Number(e.target.value))
                  }
                  data-testid="input-round-duration"
                  className="w-full h-12 rounded-xl border border-input bg-background px-4 font-semibold outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all"
                />
              </Field>
              <Field label="Break Duration" helperText="Rest time (seconds)">
                <input
                  type="number"
                  min={5}
                  max={300}
                  value={breakDurationSeconds}
                  onChange={(e) =>
                    setBreakDurationSeconds(Number(e.target.value))
                  }
                  data-testid="input-break-duration"
                  className="w-full h-12 rounded-xl border border-input bg-background px-4 font-semibold outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all"
                />
              </Field>
            </div>
          </div>
        </section>

        {/* Section 3: Visibility */}
        <section>
          <Field
            label="Initial Status"
            helperText="Live events are immediately open to players. Drafts remain hidden."
          >
            <div className="flex gap-3 bg-secondary/20 p-2 rounded-2xl max-w-sm">
              {(["live", "draft"] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setStatus(s)}
                  data-testid={`button-publish-${s}`}
                  className={cn(
                    "flex-1 py-3 rounded-xl text-xs font-bold uppercase tracking-wider transition-all",
                    status === s
                      ? "bg-foreground text-background shadow-md"
                      : "text-muted-foreground hover:bg-secondary hover:text-foreground",
                  )}
                >
                  {s === "live" ? "Publish Live" : "Save Draft"}
                </button>
              ))}
            </div>
          </Field>
        </section>

        {error && (
          <div className="bg-destructive/10 border border-destructive/30 rounded-2xl p-4 flex gap-3 items-start">
            <AlertTriangle className="w-5 h-5 text-destructive shrink-0 mt-0.5" />
            <p className="text-sm text-destructive font-semibold">{error}</p>
          </div>
        )}

        {/* Submit Actions */}
        <div className="pt-4 border-t border-border flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="px-6 py-3.5 rounded-2xl font-bold text-xs uppercase tracking-wider text-foreground bg-secondary hover:bg-secondary/80 transition-colors"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={submitting}
            data-testid="button-submit-create-event"
            className="px-8 bg-primary text-primary-foreground py-3.5 rounded-2xl font-black text-xs uppercase tracking-wider hover:brightness-110 active:scale-[0.98] transition-all shadow-xl shadow-primary/20 disabled:opacity-50"
          >
            {submitting ? "Creating Event..." : "Create Event"}
          </button>
        </div>
      </form>
    </div>
  );
}

// ==========================================
// SHARED COMPONENTS
// ==========================================

function StatCard({
  label,
  description,
  value,
  icon: Icon,
  accent,
  loading,
}: {
  label: string;
  description: string;
  value: number | undefined;
  icon: React.ComponentType<{ className?: string }>;
  accent: "primary" | "foreground";
  loading: boolean;
}) {
  return (
    <div className="bg-card border border-card-border rounded-3xl p-6 flex flex-col gap-4 shadow-sm hover:shadow-md transition-shadow">
      <div className="flex justify-between items-start">
        <div
          className={cn(
            "w-12 h-12 rounded-2xl flex items-center justify-center shadow-sm",
            accent === "primary"
              ? "bg-primary/15 text-primary"
              : "bg-secondary text-foreground",
          )}
        >
          <Icon className="w-5 h-5" />
        </div>
      </div>
      <div>
        <p className="font-mono text-4xl font-black tracking-tight tabular-nums text-foreground">
          {loading || value === undefined ? "–" : value}
        </p>
        <p className="text-sm font-bold text-card-foreground mt-1">{label}</p>
        <p className="text-xs text-muted-foreground mt-0.5 font-medium line-clamp-1">
          {description}
        </p>
      </div>
    </div>
  );
}

function LiveRoomTile({ room }: { room: LiveRoomSummary }) {
  const statusLabel = ROOM_STATUS_LABEL[room.status] ?? room.status;
  const isRunning = room.status === "ROUND_RUNNING";
  const progressPercent = Math.min(
    100,
    ((room.currentRound || 1) / (room.totalRounds || 1)) * 100,
  );

  return (
    <div className="bg-card border border-card-border rounded-3xl p-6 flex flex-col gap-5 relative overflow-hidden group hover:border-primary/30 transition-colors">
      {isRunning && (
        <div className="absolute -top-10 -right-10 w-32 h-32 bg-destructive/5 rounded-full blur-3xl pointer-events-none" />
      )}
      <div className="flex items-start justify-between z-10">
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "w-2.5 h-2.5 rounded-full",
                isRunning ? "bg-destructive live-pulse" : "bg-primary",
              )}
            />
            <span
              className={cn(
                "text-[10px] font-mono uppercase tracking-[0.2em] font-bold",
                isRunning ? "text-destructive" : "text-primary",
              )}
            >
              {isRunning ? "Live Action" : "Room Active"}
            </span>
          </div>
          <h3
            className="font-bold text-lg leading-tight truncate max-w-50"
            title={room.eventName}
          >
            {room.eventName}
          </h3>
          <p className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
            <Activity className="w-3.5 h-3.5" />
            {statusLabel}
          </p>
        </div>
      </div>
      <div className="space-y-1.5 z-10">
        <div className="flex justify-between text-xs font-semibold">
          <span className="text-muted-foreground">Round Progress</span>
          <span className="font-mono tabular-nums">
            {room.currentRound || 1} / {room.totalRounds}
          </span>
        </div>
        <div className="w-full h-2 bg-secondary rounded-full overflow-hidden">
          <div
            className="h-full bg-primary transition-all duration-500 ease-in-out rounded-full"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
      </div>
      <div className="z-10">
        <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-2 block">
          Competitors ({room.participantCount}/{room.maxParticipants})
        </span>
        <div className="flex items-center gap-2 flex-wrap">
          {room.participantNames.length > 0 ? (
            room.participantNames.slice(0, 4).map((name, i) => (
              <div
                key={i}
                className="flex items-center gap-1.5 px-2.5 py-1.5 bg-secondary/80 rounded-lg border border-border"
                title={name}
              >
                <div className="w-4 h-4 rounded-full bg-foreground flex items-center justify-center text-background text-[9px] font-bold uppercase">
                  {name.charAt(0)}
                </div>
                <span className="text-xs font-semibold truncate max-w-[80px]">
                  {name}
                </span>
              </div>
            ))
          ) : (
            <span className="text-xs text-muted-foreground italic">
              Waiting for players...
            </span>
          )}
          {room.participantNames.length > 4 && (
            <div className="px-2.5 py-1.5 bg-secondary/50 rounded-lg text-xs font-bold text-muted-foreground">
              +{room.participantNames.length - 4} more
            </div>
          )}
        </div>
      </div>
      <div className="mt-auto pt-2 z-10">
        <a
          href={`/admin/rooms/${room.competitionId}`}
          data-testid={`button-watch-${room.competitionId}`}
          className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-2xl text-xs font-black uppercase tracking-wider bg-foreground text-background hover:bg-foreground/90 transition-all"
        >
          <PlayCircle className="w-4 h-4" />
          Spectate Match
        </a>
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
    <div className="bg-card border border-card-border rounded-3xl overflow-hidden flex flex-col sm:flex-row shadow-sm hover:shadow-md transition-shadow">
      <div className="h-40 sm:h-auto sm:w-1/3 relative bg-secondary overflow-hidden shrink-0">
        {event.imageUrl ? (
          <img
            src={event.imageUrl}
            alt={event.name}
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="w-full h-full flex flex-col items-center justify-center bg-linear-to-br from-primary/10 via-secondary to-background border-r border-border/50">
            <Calendar className="w-10 h-10 text-muted-foreground mb-2 opacity-50" />
            <span className="text-xs font-semibold text-muted-foreground/60 uppercase tracking-widest">
              No Cover
            </span>
          </div>
        )}
        <div className="absolute top-3 left-3 flex gap-2">
          <span
            className={cn(
              "text-[10px] font-black uppercase tracking-widest px-3 py-1.5 rounded-lg border backdrop-blur-md",
              STATUS_STYLES[event.status],
            )}
          >
            {event.status}
          </span>
        </div>
      </div>
      <div className="p-5 flex flex-col flex-1">
        <div className="mb-4">
          <h3 className="text-xl font-bold tracking-tight text-foreground line-clamp-1 mb-1">
            {event.name}
          </h3>
          {event.description ? (
            <p className="text-sm text-muted-foreground line-clamp-2">
              {event.description}
            </p>
          ) : (
            <p className="text-sm text-muted-foreground italic">
              No description provided.
            </p>
          )}
        </div>
        <div className="grid grid-cols-2 gap-2 mb-6">
          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground bg-secondary/50 p-2 rounded-lg">
            <Dumbbell className="w-3.5 h-3.5 text-foreground" />
            <span className="truncate">{event.exerciseName}</span>
          </div>
          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground bg-secondary/50 p-2 rounded-lg">
            <Timer className="w-3.5 h-3.5 text-foreground" />
            <span>
              {event.rounds} rds × {event.roundDurationSeconds}s
            </span>
          </div>
          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground bg-secondary/50 p-2 rounded-lg">
            <Users className="w-3.5 h-3.5 text-foreground" />
            <span>Max {event.maxParticipants} players</span>
          </div>
          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground bg-secondary/50 p-2 rounded-lg">
            <Clock className="w-3.5 h-3.5 text-foreground" />
            <span>{event.breakDurationSeconds}s breaks</span>
          </div>
        </div>
        <div className="mt-auto pt-4 border-t border-border">
          <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-2">
            Change Event Status
          </p>
          <div className="flex items-center gap-2 bg-secondary/30 p-1.5 rounded-2xl">
            {(["draft", "live", "closed"] as const).map((status) => {
              const isActive = event.status === status;
              return (
                <button
                  key={status}
                  onClick={() => onStatusChange(event._id, status)}
                  disabled={isActive}
                  data-testid={`button-set-status-${status}-${event._id}`}
                  className={cn(
                    "flex-1 py-2.5 rounded-xl text-[11px] font-bold uppercase tracking-wider transition-all",
                    isActive
                      ? "bg-background text-foreground shadow-sm ring-1 ring-border"
                      : "text-muted-foreground hover:bg-secondary hover:text-foreground",
                  )}
                >
                  {status}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  helperText,
  children,
}: {
  label: string;
  helperText?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs font-bold uppercase tracking-[.1em] text-foreground">
        {label}
      </label>
      {helperText && (
        <span className="text-[11px] text-muted-foreground mb-1 leading-snug">
          {helperText}
        </span>
      )}
      {children}
    </div>
  );
}
