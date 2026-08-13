import React, { useEffect, useState } from "react";
import { useRoute, useLocation, Link } from "wouter";
import { Navbar } from "@/components/Navbar";
import { fetchEventDetail } from "@/lib/competitionApi";
import { useJoinCompetition } from "@/hooks/useCompetitionRoom";
import { useEventPhase } from "@/hooks/useEventPhase";
import { getScheduleStatus } from "@/utils/eventSchedule";
import type { EventDetail } from "@/types/competition";
import { getExerciseById } from "@/config/exercises";
import {
  ArrowLeft,
  Users,
  Repeat,
  Timer,
  Coffee,
  Sparkles,
  AlertTriangle,
  Play,
  CalendarClock,
  Clock,
} from "lucide-react";

export function EventJoinPage() {
  const [match, params] = useRoute("/events/:eventId");
  const [, setLocation] = useLocation();
  const eventId = params?.eventId;

  const [event, setEvent] = useState<EventDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [displayName, setDisplayName] = useState("");

  const { join, joining, error: joinError } = useJoinCompetition();
  const { scheduling, now } = useEventPhase(
    eventId,
    event?.scheduling,
    event?.serverNow,
  );

  useEffect(() => {
    if (!eventId) return;
    setLoading(true);
    fetchEventDetail(eventId)
      .then((data) => {
        console.log("Fetched Event Detail:", data);
        setEvent(data);
      })
      .catch((err) => setLoadError(err.message || "Event not found"))
      .finally(() => setLoading(false));
  }, [eventId]);

  if (!match || !eventId) {
    return (
      <div className="p-8 text-center font-bold text-destructive flex items-center justify-center min-h-[50vh]">
        <AlertTriangle className="mr-2" /> Event not found.
      </div>
    );
  }

  // Aggressive property resolvers to guarantee the image shows up
  const resolvedEventId = event ? event.id || (event as any)._id : undefined;
  const resolvedImageUrl = event
    ? event.imageUrl ||
      (event as any).image ||
      (event as any).coverUrl ||
      (event as any).thumbnailUrl
    : undefined;

  const exercise = event ? getExerciseById(event.exerciseId) : undefined;
  const schedule = scheduling ? getScheduleStatus(scheduling, now) : null;
  const canJoin = !schedule || schedule.canJoin;

  const handleJoin = async () => {
    const name = displayName.trim();
    if (!name || !resolvedEventId) return;
    try {
      const ack = await join(resolvedEventId, name);
      setLocation(`/competitions/${ack.competitionId}/waiting`);
    } catch {
      // Error is handled via joinError state
    }
  };

  return (
    <div className="min-h-dvh bg-background text-foreground pb-20 selection:bg-primary/30">
      <Navbar />

      <main className="max-w-3xl mx-auto p-4 md:p-6 mt-4">
        <Link
          href="/events"
          data-testid="link-back-events"
          className="inline-flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-muted-foreground hover:text-primary transition-colors mb-6 group"
        >
          <ArrowLeft className="w-4 h-4 group-hover:-translate-x-1 transition-transform" />
          Back to Directory
        </Link>

        {loading && (
          <div className="bg-card/50 border border-border rounded-[2.5rem] p-8 h-[500px] animate-pulse flex flex-col justify-center items-center">
            <Sparkles className="w-10 h-10 text-primary/20 animate-spin" />
          </div>
        )}

        {!loading && loadError && (
          <div className="bg-destructive/10 border border-destructive/30 rounded-3xl p-6 flex gap-4 items-start shadow-sm">
            <AlertTriangle className="w-6 h-6 text-destructive shrink-0 mt-0.5" />
            <div>
              <p className="font-bold text-destructive text-base">
                Arena Unavailable
              </p>
              <p className="text-sm text-muted-foreground mt-1">{loadError}</p>
            </div>
          </div>
        )}

        {!loading && event && (
          <div className="bg-card border border-border rounded-[2.5rem] overflow-hidden shadow-2xl shadow-black/40 ring-1 ring-white/5 relative">
            {/* Event Cover Image Banner */}
            <div className="h-72 w-full relative bg-zinc-900 overflow-hidden group">
              {resolvedImageUrl ? (
                <img
                  src={resolvedImageUrl}
                  alt={event.name}
                  className="w-full h-full object-cover opacity-80 group-hover:opacity-100 transition-opacity duration-700 group-hover:scale-105"
                />
              ) : (
                <div className="w-full h-full flex flex-col items-center justify-center bg-gradient-to-br from-primary/10 via-card to-secondary p-6 text-center">
                  <div className="w-16 h-16 rounded-full bg-primary/20 flex items-center justify-center text-primary mb-3 shadow-[0_0_30px_rgba(var(--primary),0.3)]">
                    <Sparkles className="w-8 h-8" />
                  </div>
                  <p className="text-sm font-mono font-bold uppercase tracking-widest text-primary/80">
                    {event.exerciseName || exercise?.name || "Active Training"}{" "}
                    Arena
                  </p>
                </div>
              )}
              <div className="absolute inset-0 bg-gradient-to-t from-card via-card/40 to-transparent" />
              <div className="absolute inset-0 bg-gradient-to-r from-card/80 via-transparent to-transparent" />

              {/* Enhanced Live Status Badge */}
              <div className="absolute top-5 right-5 z-10">
                {schedule ? (
                  <div
                    className={`flex items-center gap-2 px-4 py-2 rounded-full text-xs font-black uppercase tracking-widest backdrop-blur-xl shadow-2xl border ${
                      schedule.tone === "open" || schedule.tone === "live"
                        ? "bg-primary/20 text-primary border-primary/50 shadow-primary/20"
                        : schedule.tone === "cancelled"
                          ? "bg-destructive/20 text-destructive border-destructive/50"
                          : "bg-black/50 text-white border-white/10"
                    }`}
                  >
                    {schedule.tone === "live" ? (
                      <span className="relative flex h-3 w-3">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75"></span>
                        <span className="relative inline-flex rounded-full h-3 w-3 bg-primary"></span>
                      </span>
                    ) : (
                      <Clock className="h-4 w-4" />
                    )}
                    <span className="font-mono">{schedule.badge}</span>
                  </div>
                ) : (
                  <div className="flex items-center gap-2 px-4 py-2 rounded-full bg-primary/20 border border-primary/50 text-primary text-xs font-black uppercase tracking-widest shadow-lg backdrop-blur-xl">
                    <span className="relative flex h-3 w-3">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75"></span>
                      <span className="relative inline-flex rounded-full h-3 w-3 bg-primary"></span>
                    </span>
                    Live Ready
                  </div>
                )}
              </div>

              <div className="absolute bottom-6 left-8 z-10 flex flex-col gap-2">
                <span className="text-[10px] w-fit font-mono uppercase tracking-[0.3em] text-primary font-black bg-primary/10 border border-primary/20 backdrop-blur-md px-3 py-1.5 rounded-full shadow-lg">
                  {event.exerciseName || exercise?.name || "Competition"}
                </span>
              </div>
            </div>

            {/* Content Details */}
            <div className="p-8 md:p-10 flex flex-col gap-8 relative">
              <div>
                <h1 className="font-display text-4xl md:text-5xl font-extrabold tracking-tighter bg-clip-text text-transparent bg-gradient-to-br from-white to-white/60">
                  {event.name}
                </h1>
                <p className="text-base md:text-lg text-muted-foreground mt-3 leading-relaxed max-w-2xl">
                  {event.description ||
                    exercise?.tagline ||
                    `Enter the ${event.exerciseName} arena. Input your display name below and prepare to push your limits.`}
                </p>
              </div>

              {schedule && (
                <div
                  className={`rounded-2xl p-5 flex gap-4 items-center border shadow-inner ${
                    schedule.tone === "cancelled"
                      ? "bg-destructive/10 border-destructive/30"
                      : "bg-primary/10 border-primary/20"
                  }`}
                >
                  <CalendarClock
                    className={`w-6 h-6 shrink-0 ${schedule.tone === "cancelled" ? "text-destructive" : "text-primary"}`}
                  />
                  <p
                    className={`text-sm md:text-base font-bold ${schedule.tone === "cancelled" ? "text-destructive" : "text-primary/90"}`}
                  >
                    {schedule.message}
                  </p>
                </div>
              )}

              {/* Engaging Stat Grid */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <Stat
                  icon={<Users className="w-5 h-5 text-primary" />}
                  label="Capacity"
                  value={`${event.maxParticipants}`}
                />
                <Stat
                  icon={<Repeat className="w-5 h-5 text-primary" />}
                  label="Rounds"
                  value={String(event.rounds)}
                />
                <Stat
                  icon={<Timer className="w-5 h-5 text-primary" />}
                  label="Round Time"
                  value={`${event.roundDurationSeconds}s`}
                />
                <Stat
                  icon={<Coffee className="w-5 h-5 text-primary" />}
                  label="Rest"
                  value={`${event.breakDurationSeconds}s`}
                />
              </div>

              {/* Registration Form */}
              <div className="border-t border-white/5 pt-8 mt-2">
                <label className="block text-xs font-black uppercase tracking-[.2em] text-muted-foreground mb-3">
                  Athlete Display Name
                </label>
                <div className="relative group">
                  <input
                    value={displayName}
                    onChange={(e) =>
                      setDisplayName(e.target.value.slice(0, 24))
                    }
                    onKeyDown={(e) =>
                      e.key === "Enter" && canJoin && handleJoin()
                    }
                    placeholder="Enter your gamertag..."
                    data-testid="input-display-name"
                    className="w-full h-16 rounded-2xl border-2 border-white/10 bg-black/40 px-6 text-xl font-bold text-foreground outline-none transition-all focus:border-primary focus:bg-black/60 focus:ring-4 focus:ring-primary/20 disabled:opacity-50 shadow-inner placeholder:text-muted-foreground/50"
                    maxLength={24}
                    autoFocus
                    disabled={!canJoin}
                  />
                  <div className="absolute inset-0 -z-10 bg-primary/20 blur-xl opacity-0 group-focus-within:opacity-100 transition-opacity rounded-2xl" />
                </div>
                <p className="text-xs font-medium text-muted-foreground/70 mt-3 flex items-center gap-2">
                  <Sparkles className="w-3 h-3 text-primary" />
                  This name will appear on the global live leaderboard.
                </p>

                {joinError && (
                  <div className="mt-5 p-4 rounded-2xl bg-destructive/20 border border-destructive/40 text-sm text-destructive-foreground font-bold flex items-center gap-2">
                    <AlertTriangle className="w-4 h-4" />
                    {joinError}
                  </div>
                )}

                <button
                  onClick={handleJoin}
                  disabled={!displayName.trim() || joining || !canJoin}
                  data-testid="button-join-competition"
                  className="mt-8 w-full bg-primary text-primary-foreground h-16 rounded-2xl font-black text-xl uppercase tracking-[0.1em] flex items-center justify-center gap-3 hover:bg-primary/90 hover:scale-[1.02] active:scale-[0.98] transition-all shadow-[0_0_40px_rgba(var(--primary),0.4)] disabled:opacity-50 disabled:pointer-events-none disabled:shadow-none border border-primary/50"
                >
                  <Play className="fill-current w-6 h-6" />
                  {joining
                    ? "Establishing Connection..."
                    : canJoin
                      ? "Enter Arena Now"
                      : "Registration Closed"}
                </button>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

function Stat({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-2xl border border-white/5 bg-linear-to-b from-white/5 to-transparent p-5 flex flex-col justify-between hover:bg-white/10 transition-colors">
      <div className="flex items-center gap-2 text-xs font-black uppercase tracking-widest text-muted-foreground mb-3">
        {icon}
        {label}
      </div>
      <p className="text-3xl font-mono font-extrabold text-foreground drop-shadow-md">
        {value}
      </p>
    </div>
  );
}
