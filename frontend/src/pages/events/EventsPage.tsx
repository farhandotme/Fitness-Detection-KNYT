import React, { useEffect, useState } from "react";
import { Link } from "wouter";
import { Navbar } from "@/components/Navbar";
import { CoverImageCarousel } from "@/components/CoverImageCarousel";
import { fetchLiveEvents } from "@/lib/competitionApi";
import type { LiveEventSummary } from "@/types/competition";
import { getExerciseById } from "@/config/exercises";
import { getScheduleStatus } from "@/utils/eventSchedule";
import {
  Users,
  Repeat,
  Timer,
  ArrowUpRight,
  Trophy,
  RefreshCw,
  AlertTriangle,
  Radio,
  Zap,
  Clock,
} from "lucide-react";

export function EventsPage() {
  const [events, setEvents] = useState<LiveEventSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState(Date.now());

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchLiveEvents();
      setEvents(data);
    } catch (err: any) {
      setError(err.message || "Could not reach the competition backend.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  // Timer ticks every 1000ms (1 second) to power the live seconds countdown
  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, []);

  return (
    <div className="min-h-dvh bg-background text-foreground pb-20 selection:bg-primary/30">
      <Navbar />

      <main className="max-w-6xl mx-auto p-4 md:p-6 mt-4 flex flex-col gap-10">
        {/* Hero Section */}
        <section className="relative overflow-hidden rounded-[2.5rem] bg-linear-to-br from-[#1b2014] via-[#12160e] to-black p-8 md:p-14 text-[#f4f7f2] shadow-[0_20px_50px_rgba(0,0,0,0.5)] border border-primary/20">
          <div className="absolute -right-16 -top-24 h-96 w-96 rounded-full bg-primary/20 blur-[100px] pointer-events-none" />
          <div className="absolute right-20 -bottom-20 h-64 w-64 rounded-full bg-accent/20 blur-[80px] pointer-events-none" />

          <div className="relative max-w-xl">
            <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-primary/20 border border-primary/30 text-primary text-xs uppercase tracking-[.25em] font-black mb-6 shadow-[0_0_20px_rgba(var(--primary),0.2)]">
              <Radio className="w-4 h-4 animate-pulse" /> Live Arena Active
            </div>
            <h1 className="font-display text-5xl md:text-7xl font-black tracking-tighter leading-[1.05]">
              Compete live. <br />
              <span className="text-transparent bg-clip-text bg-linear-to-r from-primary via-accent to-white drop-shadow-sm">
                Claim the podium.
              </span>
            </h1>
            <p className="mt-6 text-base md:text-lg text-slate-300 max-w-lg leading-relaxed font-medium">
              Join active real-time rooms with players worldwide, crush your
              rounds together, and climb the live global leaderboards.
            </p>
          </div>
        </section>

        {/* Header and Refresh */}
        <div className="flex items-end justify-between border-b border-border/60 pb-5">
          <div>
            <p className="text-[11px] font-black uppercase tracking-[0.3em] text-primary mb-2">
              Directory
            </p>
            <h2 className="font-display text-3xl font-extrabold tracking-tight">
              Featured Events
            </h2>
          </div>
          <button
            onClick={load}
            disabled={loading}
            data-testid="button-refresh-events"
            className="flex items-center gap-2 px-5 py-2.5 rounded-full text-xs font-black uppercase tracking-widest bg-secondary text-foreground hover:bg-white/10 border border-white/5 transition-all disabled:opacity-50 hover:shadow-lg"
          >
            <RefreshCw
              className={
                loading
                  ? "w-4 h-4 animate-spin text-primary"
                  : "w-4 h-4 text-primary"
              }
            />
            Refresh
          </button>
        </div>

        {error && (
          <div className="bg-destructive/10 border border-destructive/30 rounded-3xl p-6 flex gap-4 items-start shadow-sm">
            <AlertTriangle className="w-6 h-6 text-destructive shrink-0 mt-0.5" />
            <div>
              <p className="font-bold text-destructive text-base">
                System Offline
              </p>
              <p className="text-sm text-muted-foreground mt-1">{error}</p>
            </div>
          </div>
        )}

        {!error && loading && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="bg-card/50 border border-border/50 rounded-4xl p-5 h-112.5 animate-pulse"
              />
            ))}
          </div>
        )}

        {/* Events Grid */}
        {!error && !loading && events && events.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
            {events.map((event: any) => {
              const exercise = getExerciseById(event.exerciseId);
              const schedule = event.scheduling
                ? getScheduleStatus(event.scheduling, now)
                : null;

              const displayImages: string[] = event.imageUrls?.length
                ? event.imageUrls
                : [
                    (event as any).image,
                    (event as any).coverUrl,
                    (event as any).thumbnailUrl,
                  ].filter(Boolean);

              return (
                <Link
                  key={event.id}
                  href={`/events/${event.id}`}
                  className="group block outline-none"
                >
                  <div
                    data-testid={`card-event-${event.id}`}
                    className="bg-card border border-white/5 rounded-4xl overflow-hidden h-full flex flex-col transition-all duration-500 hover:border-primary/50 hover:-translate-y-2 hover:shadow-[0_20px_40px_rgba(var(--primary),0.15)] relative"
                  >
                    {/* Event Banner Image */}
                    <div className="h-56 w-full relative bg-zinc-900 overflow-hidden">
                      {displayImages.length > 0 ? (
                        <CoverImageCarousel
                          images={displayImages}
                          alt={event.name}
                          imgClassName="opacity-80 group-hover:opacity-100 group-hover:scale-110 transition-all duration-700 ease-out"
                        />
                      ) : (
                        <div className="w-full h-full flex flex-col items-center justify-center bg-linear-to-br from-primary/10 via-card to-black">
                          <Trophy className="w-12 h-12 text-primary/30 mb-2" />
                          <span className="text-xs font-mono font-bold uppercase tracking-widest text-primary/40">
                            Arena
                          </span>
                        </div>
                      )}

                      <div className="absolute inset-0 bg-linear-to-t from-black/90 via-black/30 to-transparent" />

                      {/* Noticeable, normal-sized red border badge */}
                      {schedule ? (
                        <div
                          className={`absolute top-4 right-4 z-10 flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[10px] font-black uppercase tracking-widest backdrop-blur-md shadow-lg border transition-colors ${
                            schedule.tone === "open"
                              ? "bg-red-500/10 text-red-500 border-red-500 shadow-[0_0_15px_rgba(239,68,68,0.2)]"
                              : schedule.tone === "live"
                                ? "bg-primary/20 text-primary border-primary shadow-[0_0_15px_rgba(var(--primary),0.2)]"
                                : schedule.tone === "cancelled"
                                  ? "bg-destructive/20 text-destructive border-destructive"
                                  : "bg-black/60 text-white border-white/20"
                          }`}
                        >
                          {schedule.tone === "live" ? (
                            <span className="relative flex h-2 w-2">
                              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75"></span>
                              <span className="relative inline-flex rounded-full h-2 w-2 bg-primary"></span>
                            </span>
                          ) : (
                            <Clock className="h-3 w-3" />
                          )}
                          <span className="font-mono">{schedule.badge}</span>
                        </div>
                      ) : (
                        <div className="absolute top-4 right-4 z-10 flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-primary/20 border border-primary text-primary shadow-[0_0_15px_rgba(var(--primary),0.2)] backdrop-blur-md">
                          <span className="relative flex h-2 w-2">
                            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75"></span>
                            <span className="relative inline-flex rounded-full h-2 w-2 bg-primary"></span>
                          </span>
                          <span className="font-mono text-[10px] font-black uppercase tracking-widest">
                            Live Now
                          </span>
                        </div>
                      )}

                      {event.activeRooms > 0 && (
                        <div className="absolute bottom-4 left-5 z-10 flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-black/60 backdrop-blur-md text-xs font-black text-primary border border-primary/20">
                          <Zap className="w-4 h-4 fill-primary animate-pulse" />
                          {event.activeRooms} Active Room
                          {event.activeRooms === 1 ? "" : "s"}
                        </div>
                      )}
                    </div>

                    {/* Card Body Content */}
                    <div className="p-7 flex flex-col flex-1 justify-between gap-6 relative z-20 bg-card">
                      <div>
                        <div className="flex items-center gap-2 mb-3">
                          <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-primary font-black bg-primary/10 border border-primary/20 px-3 py-1 rounded-full shadow-sm">
                            {event.exerciseName ||
                              exercise?.name ||
                              "Competition"}
                          </span>
                        </div>
                        <h3 className="font-display text-2xl font-black tracking-tight group-hover:text-primary transition-colors line-clamp-1">
                          {event.name}
                        </h3>
                        <p className="text-sm text-muted-foreground mt-2 line-clamp-2 leading-relaxed font-medium">
                          {event.description ||
                            exercise?.tagline ||
                            `Join this intense ${event.rounds}-round challenge and test your absolute limits.`}
                        </p>
                      </div>

                      {/* Specs Row */}
                      <div className="pt-5 border-t border-white/5 flex items-center justify-between">
                        <div className="flex flex-wrap gap-2 text-xs font-black uppercase tracking-wider text-foreground">
                          <span className="flex items-center gap-1.5 bg-white/5 border border-white/5 px-3 py-1.5 rounded-lg shadow-inner">
                            <Repeat className="w-3.5 h-3.5 text-primary" />
                            {event.rounds}R
                          </span>
                          <span className="flex items-center gap-1.5 bg-white/5 border border-white/5 px-3 py-1.5 rounded-lg shadow-inner">
                            <Timer className="w-3.5 h-3.5 text-primary" />
                            {event.roundDurationSeconds}s
                          </span>
                        </div>

                        <div className="w-10 h-10 rounded-xl bg-white/5 border border-white/5 group-hover:bg-primary group-hover:border-primary group-hover:text-primary-foreground flex items-center justify-center transition-all shadow-sm group-hover:shadow-[0_0_20px_rgba(var(--primary),0.4)]">
                          <ArrowUpRight className="w-5 h-5 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-transform" />
                        </div>
                      </div>
                    </div>
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}
