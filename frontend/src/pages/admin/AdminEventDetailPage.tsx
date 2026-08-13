import React, { useEffect, useState } from "react";
import { Link, useLocation, useRoute } from "wouter";
import { Navbar } from "@/components/Navbar";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { EventFormModal } from "@/components/admin/EventFormModal";
import { StatCard } from "@/components/admin/StatCard";
import {
  type AdminCompetitionRoom,
  type AdminCompetitionStatus,
  type AdminEvent,
  type CreateEventInput,
  clearAdminSession,
  deleteAdminEvent,
  downloadEventResultsCsv,
  fetchAdminEventDetail,
  fetchEventCompetitions,
  getAdminToken,
  setAdminEventStatus,
  updateAdminEvent,
} from "@/lib/adminApi";
import {
  AlertTriangle,
  ArrowLeft,
  Ban,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Download,
  Pencil,
  Trash2,
  Trophy,
  Users,
} from "lucide-react";
import { cn } from "@/lib/utils";

const STATUS_STYLES: Record<AdminCompetitionStatus, string> = {
  WAITING: "bg-secondary text-muted-foreground",
  FULL: "bg-amber-500/15 text-amber-500",
  COUNTDOWN: "bg-amber-500/15 text-amber-500",
  ROUND_RUNNING: "bg-primary/15 text-primary",
  ROUND_FINISHED: "bg-primary/15 text-primary",
  BREAK: "bg-amber-500/15 text-amber-500",
  COMPLETED: "bg-emerald-500/15 text-emerald-500",
  ABANDONED: "bg-destructive/10 text-destructive",
};

const STATUS_LABELS: Record<AdminCompetitionStatus, string> = {
  WAITING: "Waiting",
  FULL: "Full",
  COUNTDOWN: "Countdown",
  ROUND_RUNNING: "Round running",
  ROUND_FINISHED: "Round finished",
  BREAK: "Break",
  COMPLETED: "Completed",
  ABANDONED: "Abandoned",
};

const PAGE_SIZE = 10;

export function AdminEventDetailPage() {
  const [, params] = useRoute("/admin/events/:eventId");
  const eventId = params?.eventId ?? "";
  const [, setLocation] = useLocation();

  const [event, setEvent] = useState<AdminEvent | null>(null);
  const [rooms, setRooms] = useState<AdminCompetitionRoom[] | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<AdminCompetitionStatus | "">(
    "",
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showEdit, setShowEdit] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    if (!getAdminToken()) {
      setLocation("/admin/login");
      return;
    }
    if (eventId) void load();
  }, [eventId]);

  useEffect(() => {
    if (eventId) void loadRooms();
  }, [eventId, page, statusFilter]);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setEvent(await fetchAdminEventDetail(eventId));
    } catch (err: any) {
      handleError(err);
    } finally {
      setLoading(false);
    }
  };

  const loadRooms = async () => {
    try {
      const result = await fetchEventCompetitions(eventId, {
        status: statusFilter || undefined,
        page,
        limit: PAGE_SIZE,
      });
      setRooms(result.rooms);
      setTotal(result.total);
    } catch (err: any) {
      handleError(err);
    }
  };

  const handleError = (err: any) => {
    const message = err.message || "Something went wrong";
    setError(message);
    if (
      message.toLowerCase().includes("session") ||
      message.toLowerCase().includes("token")
    ) {
      clearAdminSession();
      setLocation("/admin/login");
    }
  };

  const handleStatusChange = async (status: AdminEvent["status"]) => {
    if (!event) return;
    try {
      setEvent(await setAdminEventStatus(event._id, status));
    } catch (err: any) {
      handleError(err);
    }
  };

  const handleEditSubmit = async (input: CreateEventInput) => {
    if (!event) return;
    setEvent(await updateAdminEvent(event._id, input));
    setShowEdit(false);
  };

  const handleDelete = async () => {
    await deleteAdminEvent(eventId);
    setLocation("/admin");
  };

  const handleExport = async () => {
    if (!event) return;
    setExporting(true);
    setError(null);
    try {
      await downloadEventResultsCsv(
        event._id,
        `${event.name.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}-results.csv`,
      );
    } catch (err: any) {
      handleError(err);
    } finally {
      setExporting(false);
    }
  };

  const canDelete =
    event?.status === "draft" &&
    (event.stats?.active ?? 0) === 0 &&
    (event.stats?.completed ?? 0) === 0 &&
    (event.stats?.abandoned ?? 0) === 0;

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="min-h-dvh bg-background text-foreground pb-20">
      <Navbar />

      <main className="max-w-5xl mx-auto p-4 mt-6 flex flex-col gap-6">
        <Link
          href="/admin"
          data-testid="link-back-to-dashboard"
          className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors w-fit"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> All events
        </Link>

        {error && (
          <div className="bg-destructive/10 border border-destructive/30 rounded-2xl p-4 flex gap-3 items-start">
            <AlertTriangle className="w-5 h-5 text-destructive shrink-0 mt-0.5" />
            <p className="text-sm text-destructive font-semibold">{error}</p>
          </div>
        )}

        {loading && (
          <div className="bg-card border border-card-border rounded-3xl p-8 h-40 animate-pulse" />
        )}

        {!loading && event && (
          <>
            <div className="bg-card border border-card-border rounded-3xl p-6 flex flex-col gap-4">
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div>
                  <h1 className="font-display text-2xl font-extrabold tracking-tight">
                    {event.name}
                  </h1>
                  <p className="text-sm text-muted-foreground mt-1">
                    {event.exerciseName} · {event.rounds} round
                    {event.rounds === 1 ? "" : "s"} ·{" "}
                    {event.roundDurationSeconds}s rounds ·{" "}
                    {event.breakDurationSeconds}s breaks ·{" "}
                    {event.maxParticipants} max players
                  </p>
                  {event.description && (
                    <p className="text-sm text-muted-foreground mt-2 max-w-xl">
                      {event.description}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setShowEdit(true)}
                    data-testid="button-edit-event-detail"
                    className="flex items-center gap-1.5 px-3.5 py-2 rounded-full text-xs font-bold uppercase tracking-wider bg-secondary text-muted-foreground hover:bg-secondary/80 transition-colors"
                  >
                    <Pencil className="w-3.5 h-3.5" /> Edit
                  </button>
                  {canDelete && (
                    <button
                      onClick={() => setShowDelete(true)}
                      data-testid="button-delete-event-detail"
                      className="flex items-center gap-1.5 px-3.5 py-2 rounded-full text-xs font-bold uppercase tracking-wider bg-destructive/10 text-destructive hover:bg-destructive/20 transition-colors"
                    >
                      <Trash2 className="w-3.5 h-3.5" /> Delete
                    </button>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-2">
                {(["draft", "live", "closed"] as const).map((status) => (
                  <button
                    key={status}
                    onClick={() => handleStatusChange(status)}
                    disabled={event.status === status}
                    data-testid={`button-set-status-${status}`}
                    className={cn(
                      "px-4 py-2 rounded-xl text-[11px] font-bold uppercase tracking-wider transition-colors",
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

            {event.stats && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <StatCard
                  label="Active rooms"
                  value={event.stats.active}
                  icon={<Trophy className="w-4 h-4" />}
                  accent="primary"
                />
                <StatCard
                  label="Completed"
                  value={event.stats.completed}
                  icon={<CheckCircle2 className="w-4 h-4" />}
                />
                <StatCard
                  label="Abandoned"
                  value={event.stats.abandoned}
                  icon={<Ban className="w-4 h-4" />}
                  accent={event.stats.abandoned > 0 ? "destructive" : "default"}
                />
                <StatCard
                  label="Participants ever"
                  value={event.stats.totalParticipants}
                  icon={<Users className="w-4 h-4" />}
                />
              </div>
            )}

            <div className="bg-card border border-card-border rounded-3xl p-5 md:p-6">
              <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
                <h2 className="text-lg font-black tracking-tight">
                  Competition rooms
                </h2>
                <div className="flex items-center gap-2">
                  <select
                    value={statusFilter}
                    onChange={(e) => {
                      setStatusFilter(
                        e.target.value as AdminCompetitionStatus | "",
                      );
                      setPage(1);
                    }}
                    data-testid="select-room-status-filter"
                    className="h-10 rounded-xl border border-input bg-background px-3 text-xs font-bold uppercase tracking-wider outline-none focus:border-primary"
                  >
                    <option value="">All statuses</option>
                    {(
                      Object.keys(STATUS_LABELS) as AdminCompetitionStatus[]
                    ).map((s) => (
                      <option key={s} value={s}>
                        {STATUS_LABELS[s]}
                      </option>
                    ))}
                  </select>
                  <button
                    onClick={handleExport}
                    disabled={exporting || !event.stats?.completed}
                    data-testid="button-export-results-csv"
                    className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-bold uppercase tracking-wider bg-secondary text-muted-foreground hover:bg-secondary/80 transition-colors disabled:opacity-40"
                    title={
                      !event.stats?.completed
                        ? "No completed rooms to export yet"
                        : undefined
                    }
                  >
                    <Download className="w-3.5 h-3.5" />{" "}
                    {exporting ? "Exporting..." : "Export CSV"}
                  </button>
                </div>
              </div>

              {rooms && rooms.length === 0 && (
                <p className="text-sm text-muted-foreground py-8 text-center">
                  No rooms{" "}
                  {statusFilter
                    ? `with status "${STATUS_LABELS[statusFilter]}"`
                    : "yet"}
                  .
                </p>
              )}

              {rooms && rooms.length > 0 && (
                <div className="overflow-x-auto -mx-2">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-[10px] font-black uppercase tracking-wider text-muted-foreground border-b border-card-border">
                        <th className="px-2 py-2">Room</th>
                        <th className="px-2 py-2">Status</th>
                        <th className="px-2 py-2">Players</th>
                        <th className="px-2 py-2">Round</th>
                        <th className="px-2 py-2">Created</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rooms.map((room) => (
                        <tr
                          key={room._id}
                          data-testid={`row-room-${room._id}`}
                          className="border-b border-card-border/50 last:border-0 hover:bg-secondary/40 transition-colors cursor-pointer"
                          onClick={() =>
                            setLocation(`/admin/competitions/${room._id}`)
                          }
                        >
                          <td className="px-2 py-3 font-bold tracking-wide">
                            {room.roomCode}
                          </td>
                          <td className="px-2 py-3">
                            <span
                              className={cn(
                                "text-[10px] font-black uppercase tracking-wider px-2 py-1 rounded-md",
                                STATUS_STYLES[room.status],
                              )}
                            >
                              {STATUS_LABELS[room.status]}
                            </span>
                          </td>
                          <td className="px-2 py-3 text-muted-foreground font-semibold">
                            {room.participants.length}/{room.maxParticipants}
                          </td>
                          <td className="px-2 py-3 text-muted-foreground font-semibold">
                            {room.currentRound}/{room.totalRounds}
                          </td>
                          <td className="px-2 py-3 text-muted-foreground">
                            {new Date(room.createdAt).toLocaleString()}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {total > PAGE_SIZE && (
                <div className="flex items-center justify-between mt-4 pt-4 border-t border-card-border">
                  <span className="text-xs text-muted-foreground font-semibold">
                    Page {page} of {totalPages} · {total} rooms
                  </span>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      disabled={page <= 1}
                      data-testid="button-prev-page"
                      className="p-2 rounded-full bg-secondary text-muted-foreground hover:bg-secondary/80 disabled:opacity-40 transition-colors"
                    >
                      <ChevronLeft className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() =>
                        setPage((p) => Math.min(totalPages, p + 1))
                      }
                      disabled={page >= totalPages}
                      data-testid="button-next-page"
                      className="p-2 rounded-full bg-secondary text-muted-foreground hover:bg-secondary/80 disabled:opacity-40 transition-colors"
                    >
                      <ChevronRight className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </main>

      {showEdit && event && (
        <EventFormModal
          initialEvent={event}
          onClose={() => setShowEdit(false)}
          onSubmit={handleEditSubmit}
        />
      )}

      {showDelete && event && (
        <ConfirmDialog
          title="Delete this event?"
          description={`"${event.name}" has never been published with any rooms, so this is permanent and can't be undone.`}
          confirmLabel="Delete event"
          danger
          onConfirm={handleDelete}
          onClose={() => setShowDelete(false)}
        />
      )}
    </div>
  );
}
