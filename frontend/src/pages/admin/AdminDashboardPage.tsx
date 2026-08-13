import React, { useEffect, useState } from "react";
import { Link, useLocation } from "wouter";
import { Navbar } from "@/components/Navbar";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { EventFormModal } from "@/components/admin/EventFormModal";
import { ChangePasswordModal } from "@/components/admin/ChangePasswordModal";
import { StatCard } from "@/components/admin/StatCard";
import {
  type AdminEvent,
  type CreateEventInput,
  type DashboardStats,
  clearAdminSession,
  createAdminEvent,
  deleteAdminEvent,
  fetchAdminEvents,
  fetchDashboardStats,
  getAdminToken,
  getAdminUsername,
  setAdminEventStatus,
  updateAdminEvent,
} from "@/lib/adminApi";
import {
  AlertTriangle,
  CalendarDays,
  Flame,
  KeyRound,
  LogOut,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trophy,
  Users,
} from "lucide-react";
import { cn } from "@/lib/utils";

const STATUS_STYLES: Record<AdminEvent["status"], string> = {
  live: "bg-primary/15 text-primary",
  draft: "bg-secondary text-muted-foreground",
  closed: "bg-destructive/10 text-destructive",
};

export function AdminDashboardPage() {
  const [, setLocation] = useLocation();
  const username = getAdminUsername();

  const [events, setEvents] = useState<AdminEvent[] | null>(null);
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showCreate, setShowCreate] = useState(false);
  const [editingEvent, setEditingEvent] = useState<AdminEvent | null>(null);
  const [deletingEvent, setDeletingEvent] = useState<AdminEvent | null>(null);
  const [showChangePassword, setShowChangePassword] = useState(false);

  useEffect(() => {
    if (!getAdminToken()) {
      setLocation("/admin/login");
      return;
    }
    void load();
  }, []);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [eventsResult, statsResult] = await Promise.all([
        fetchAdminEvents(),
        fetchDashboardStats(),
      ]);
      setEvents(eventsResult);
      setStats(statsResult);
    } catch (err: any) {
      const message = err.message || "Could not load the dashboard";
      setError(message);
      if (
        message.toLowerCase().includes("session") ||
        message.toLowerCase().includes("token")
      ) {
        clearAdminSession();
        setLocation("/admin/login");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = () => {
    clearAdminSession();
    setLocation("/admin/login");
  };

  const handleStatusChange = async (
    id: string,
    status: AdminEvent["status"],
  ) => {
    try {
      const updated = await setAdminEventStatus(id, status);
      setEvents(
        (prev) =>
          prev?.map((e) =>
            e._id === id ? { ...updated, stats: e.stats } : e,
          ) ?? prev,
      );
    } catch (err: any) {
      setError(err.message || "Could not update event status");
    }
  };

  const handleCreate = async (input: CreateEventInput) => {
    const event = await createAdminEvent(input);
    setEvents((prev) => (prev ? [event, ...prev] : [event]));
    setShowCreate(false);
  };

  const handleEditSubmit = async (input: CreateEventInput) => {
    if (!editingEvent) return;
    const updated = await updateAdminEvent(editingEvent._id, input);
    setEvents(
      (prev) =>
        prev?.map((e) =>
          e._id === updated._id ? { ...updated, stats: e.stats } : e,
        ) ?? prev,
    );
    setEditingEvent(null);
  };

  const handleDelete = async () => {
    if (!deletingEvent) return;
    await deleteAdminEvent(deletingEvent._id);
    setEvents(
      (prev) => prev?.filter((e) => e._id !== deletingEvent._id) ?? prev,
    );
  };

  return (
    <div className="min-h-dvh bg-background text-foreground pb-20">
      <Navbar />

      <main className="max-w-5xl mx-auto p-4 mt-6 flex flex-col gap-6">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <div className="flex items-center gap-2 text-primary text-xs uppercase tracking-[.2em] font-bold mb-1">
              <ShieldCheck className="w-4 h-4" /> Admin
            </div>
            <h1 className="font-display text-2xl md:text-3xl font-extrabold tracking-tight">
              {username ? `Signed in as ${username}` : "Event management"}
            </h1>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={load}
              disabled={loading}
              data-testid="button-refresh-admin-events"
              className="flex items-center gap-2 px-4 py-2.5 rounded-full text-xs font-bold uppercase tracking-wider bg-secondary text-muted-foreground hover:bg-secondary/80 transition-colors disabled:opacity-50"
            >
              <RefreshCw
                className={loading ? "w-4 h-4 animate-spin" : "w-4 h-4"}
              />
              Refresh
            </button>
            <button
              onClick={() => setShowChangePassword(true)}
              data-testid="button-open-change-password"
              className="flex items-center gap-2 px-4 py-2.5 rounded-full text-xs font-bold uppercase tracking-wider bg-secondary text-muted-foreground hover:bg-secondary/80 transition-colors"
            >
              <KeyRound className="w-4 h-4" />
              Password
            </button>
            <button
              onClick={() => setShowCreate(true)}
              data-testid="button-open-create-event"
              className="flex items-center gap-2 px-4 py-2.5 rounded-full text-xs font-black uppercase tracking-wider bg-primary text-primary-foreground hover:brightness-110 transition-all shadow-lg shadow-primary/20"
            >
              <Plus className="w-4 h-4" />
              New event
            </button>
            <button
              onClick={handleLogout}
              data-testid="button-admin-logout"
              className="flex items-center gap-2 px-4 py-2.5 rounded-full text-xs font-bold uppercase tracking-wider bg-secondary text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-colors"
            >
              <LogOut className="w-4 h-4" />
              Log out
            </button>
          </div>
        </div>

        {error && (
          <div className="bg-destructive/10 border border-destructive/30 rounded-2xl p-4 flex gap-3 items-start">
            <AlertTriangle className="w-5 h-5 text-destructive shrink-0 mt-0.5" />
            <p className="text-sm text-destructive font-semibold">{error}</p>
          </div>
        )}

        {stats && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatCard
              label="Live events"
              value={stats.events.live}
              icon={<CalendarDays className="w-4 h-4" />}
              accent="primary"
              hint={`${stats.events.total} total`}
            />
            <StatCard
              label="Active rooms"
              value={stats.competitions.active}
              icon={<Trophy className="w-4 h-4" />}
              accent="primary"
              hint={`${stats.competitions.liveParticipantsNow} people competing now`}
            />
            <StatCard
              label="Completed"
              value={stats.competitions.completed}
              icon={<Users className="w-4 h-4" />}
              hint={`${stats.completedLast24h} in the last 24h`}
            />
            <StatCard
              label="Top exercise"
              value={stats.mostPopularExercise?.exerciseName ?? "—"}
              icon={<Flame className="w-4 h-4" />}
              hint={
                stats.mostPopularExercise
                  ? `${stats.mostPopularExercise.count} rooms all-time`
                  : "No data yet"
              }
            />
          </div>
        )}

        {loading && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[1, 2].map((i) => (
              <div
                key={i}
                className="bg-card border border-card-border rounded-3xl p-5 h-48 animate-pulse"
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
            {events.map((event) => {
              const canDelete =
                event.status === "draft" &&
                (event.stats?.active ?? 0) === 0 &&
                (event.stats?.completed ?? 0) === 0 &&
                (event.stats?.abandoned ?? 0) === 0;
              return (
                <div
                  key={event._id}
                  data-testid={`admin-event-${event._id}`}
                  className="bg-card border border-card-border rounded-3xl p-5 flex flex-col gap-3"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <Link
                        href={`/admin/events/${event._id}`}
                        data-testid={`link-manage-event-${event._id}`}
                        className="text-lg font-bold tracking-tight hover:text-primary transition-colors"
                      >
                        {event.name}
                      </Link>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {event.exerciseName} · {event.rounds} round
                        {event.rounds === 1 ? "" : "s"} ·{" "}
                        {event.roundDurationSeconds}s · {event.maxParticipants}{" "}
                        max
                      </p>
                    </div>
                    <span
                      className={cn(
                        "text-[10px] font-black uppercase tracking-widest px-2.5 py-1 rounded-md shrink-0",
                        STATUS_STYLES[event.status],
                      )}
                    >
                      {event.status}
                    </span>
                  </div>

                  {event.description && (
                    <p className="text-sm text-muted-foreground line-clamp-2">
                      {event.description}
                    </p>
                  )}

                  {event.stats && (
                    <div className="flex items-center gap-3 text-xs font-bold text-muted-foreground flex-wrap">
                      <span
                        className={
                          event.stats.active > 0 ? "text-primary" : undefined
                        }
                      >
                        {event.stats.active} active
                      </span>
                      <span>·</span>
                      <span>{event.stats.completed} completed</span>
                      <span>·</span>
                      <span>
                        {event.stats.totalParticipants} participants ever
                      </span>
                    </div>
                  )}

                  <div className="flex items-center gap-2 mt-1">
                    {(["draft", "live", "closed"] as const).map((status) => (
                      <button
                        key={status}
                        onClick={() => handleStatusChange(event._id, status)}
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

                  <div className="flex items-center gap-2">
                    <Link
                      href={`/admin/events/${event._id}`}
                      data-testid={`button-manage-event-${event._id}`}
                      className="flex-1 text-center py-2 rounded-xl text-[11px] font-bold uppercase tracking-wider bg-secondary text-muted-foreground hover:bg-secondary/80 transition-colors"
                    >
                      Manage rooms & results
                    </Link>
                    <button
                      onClick={() => setEditingEvent(event)}
                      data-testid={`button-edit-event-${event._id}`}
                      className="px-4 py-2 rounded-xl text-[11px] font-bold uppercase tracking-wider bg-secondary text-muted-foreground hover:bg-secondary/80 transition-colors"
                    >
                      Edit
                    </button>
                    {canDelete && (
                      <button
                        onClick={() => setDeletingEvent(event)}
                        data-testid={`button-delete-event-${event._id}`}
                        className="px-4 py-2 rounded-xl text-[11px] font-bold uppercase tracking-wider bg-destructive/10 text-destructive hover:bg-destructive/20 transition-colors"
                      >
                        Delete
                      </button>
                    )}
                  </div>

                  {event.status === "live" && (
                    <Link
                      href={`/events/${event._id}`}
                      className="text-xs font-bold text-primary hover:underline"
                    >
                      Open join screen →
                    </Link>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </main>

      {showCreate && (
        <EventFormModal
          onClose={() => setShowCreate(false)}
          onSubmit={handleCreate}
        />
      )}

      {editingEvent && (
        <EventFormModal
          initialEvent={editingEvent}
          onClose={() => setEditingEvent(null)}
          onSubmit={handleEditSubmit}
        />
      )}

      {deletingEvent && (
        <ConfirmDialog
          title="Delete this event?"
          description={`"${deletingEvent.name}" has never been published with any rooms, so this is permanent and can't be undone.`}
          confirmLabel="Delete event"
          danger
          onConfirm={handleDelete}
          onClose={() => setDeletingEvent(null)}
        />
      )}

      {showChangePassword && (
        <ChangePasswordModal onClose={() => setShowChangePassword(false)} />
      )}
    </div>
  );
}
