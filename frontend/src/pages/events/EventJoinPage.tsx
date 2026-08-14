import React, { useEffect, useState } from "react";
import { useRoute, useLocation, Link } from "wouter";
import { Navbar } from "@/components/Navbar";
import { fetchEventDetail } from "@/lib/competitionApi";
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
  CalendarClock,
  Clock,
  DoorOpen,
} from "lucide-react";

export function EventJoinPage() {
  const [match, params] = useRoute("/events/:eventId");
  const [, setLocation] = useLocation();
  const eventId = params?.eventId;

  const [event, setEvent] = useState<EventDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [imageFailed, setImageFailed] = useState(false);

  const { scheduling, now } = useEventPhase(
    eventId,
    event?.scheduling,
    event?.serverNow,
  );

  useEffect(() => {
    if (!eventId) return;
    setLoading(true);
    fetchEventDetail(eventId)
      .then((data) => setEvent(data))
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

  const hasImage = Boolean(event?.imageUrl) && !imageFailed;
  const exercise = event ? getExerciseById(event.exerciseId) : undefined;
  const schedule = scheduling ? getScheduleStatus(scheduling, now) : null;
  const canJoin = !schedule || schedule.canJoin;

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
          <div className="bg-card border border-border rounded-[2.5rem] overflow-hidden shadow-xl animate-pulse">
            <div className="h-72 w-full bg-linear-to-br from-secondary/60 via-card to-secondary/30" />
            <div className="p-8 md:p-10 flex flex-col gap-6">
              <div className="h-9 w-2/3 rounded-lg bg-secondary/60" />
              <div className="h-4 w-full rounded bg-secondary/40" />
              <div className="h-4 w-4/5 rounded bg-secondary/40" />
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-2">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="h-24 rounded-2xl bg-secondary/40" />
                ))}
              </div>
            </div>
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
              {hasImage ? (
                <img
                  src={event.imageUrl}
                  alt={event.name}
                  onError={() => setImageFailed(true)}
                  className="w-full h-full object-cover opacity-80 group-hover:opacity-100 transition-opacity duration-700 group-hover:scale-105"
                />
              ) : (
                <div className="w-full h-full flex flex-col items-center justify-center bg-gradient-to-br from-primary/10 via-card to-secondary p-6 text-center relative overflow-hidden">
                  <div className="absolute inset-0 opacity-[0.07] bg-[radial-gradient(circle_at_1px_1px,white_1px,transparent_0)] bg-size-[24px_24px]" />
                  <div className="w-16 h-16 rounded-full bg-primary/20 flex items-center justify-center text-primary mb-3 shadow-[0_0_30px_rgba(var(--primary),0.3)] relative">
                    <Sparkles className="w-8 h-8" />
                  </div>
                  <p className="text-sm font-mono font-bold uppercase tracking-widest text-primary/80 relative">
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

              {/* Enter the lobby - rooms are created by other players, see who's inside before you join */}
              <div className="border-t border-white/5 pt-8 mt-2">
                <p className="text-xs font-medium text-muted-foreground/70 mb-4 flex items-center gap-2">
                  <Sparkles className="w-3 h-3 text-primary" />
                  Browse rooms other players have created - or start your
                  own, public or password-protected - before you pick a
                  display name.
                </p>

                <button
                  onClick={() => canJoin && setLocation(`/events/${event.id}/rooms`)}
                  disabled={!canJoin}
                  data-testid="button-browse-rooms"
                  className="w-full bg-primary text-primary-foreground h-16 rounded-2xl font-black text-xl uppercase tracking-[0.1em] flex items-center justify-center gap-3 hover:bg-primary/90 hover:scale-[1.02] active:scale-[0.98] transition-all shadow-[0_0_40px_rgba(var(--primary),0.4)] disabled:opacity-50 disabled:pointer-events-none disabled:shadow-none border border-primary/50"
                >
                  <DoorOpen className="w-6 h-6" />
                  {canJoin ? "Browse Rooms" : "Registration Closed"}
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
    <div className="rounded-2xl border border-white/5 bg-linear-to-b from-white/5 to-transparent p-5 flex flex-col gap-3 hover:bg-white/10 hover:border-primary/20 transition-colors">
      <div className="w-9 h-9 rounded-xl bg-primary/15 flex items-center justify-center">
        {icon}
      </div>
      <div>
        <p className="text-3xl font-mono font-extrabold text-foreground drop-shadow-md leading-none">
          {value}
        </p>
        <p className="text-[11px] font-black uppercase tracking-widest text-muted-foreground mt-1.5">
          {label}
        </p>
      </div>
    </div>
  );
}
