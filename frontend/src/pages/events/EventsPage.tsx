import React, { useEffect, useState } from "react";
import { Link } from "wouter";
import { Navbar } from "@/components/Navbar";
import { fetchLiveEvents } from "@/lib/competitionApi";
import type { LiveEventSummary } from "@/types/competition";
import { getExerciseById } from "@/config/exercises";
import {
  Users,
  Repeat,
  Timer,
  ArrowUpRight,
  Trophy,
  RefreshCw,
  AlertTriangle,
  Radio,
} from "lucide-react";

export function EventsPage() {
  const [events, setEvents] = useState<LiveEventSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

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

  return (
    <div className="min-h-dvh bg-background text-foreground pb-20">
      <Navbar />

      <main className="max-w-6xl mx-auto p-4 mt-6 flex flex-col gap-7">
        <section className="relative overflow-hidden rounded-4xl bg-[#1b2014] p-7 md:p-10 text-[#f4f7f2] shadow-2xl shadow-black/25 border border-primary/15">
          <div className="absolute -right-16 -top-24 h-72 w-72 rounded-full border-42 border-primary/15 ambient-pulse" />
          <div className="absolute right-10 -bottom-20 h-48 w-48 rounded-full border-26 border-accent/20 ambient-pulse" />
          <div className="relative max-w-xl">
            <div className="flex items-center gap-2 text-accent text-xs uppercase tracking-[.22em] font-bold">
              <Radio className="w-4 h-4" /> Live now
            </div>
            <h2 className="font-display text-4xl md:text-6xl font-extrabold tracking-tighter leading-[.95] mt-5">
              Compete in
              <br />
              real time.
            </h2>
            <p className="mt-5 text-sm md:text-base text-slate-300 max-w-md leading-relaxed">
              Join a live room with up to 5 players, complete every round
              together, and see who comes out on top.
            </p>
          </div>
        </section>

        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs font-bold uppercase tracking-[.24em] text-primary">
              Competitions
            </p>
            <h2 className="mt-2 font-display text-2xl font-extrabold tracking-tight">
              Available events
            </h2>
          </div>
          <button
            onClick={load}
            disabled={loading}
            data-testid="button-refresh-events"
            className="flex items-center gap-2 px-4 py-2 rounded-full text-xs font-bold uppercase tracking-wider bg-secondary text-muted-foreground hover:bg-secondary/80 transition-colors disabled:opacity-50"
          >
            <RefreshCw
              className={loading ? "w-4 h-4 animate-spin" : "w-4 h-4"}
            />
            Refresh
          </button>
        </div>

        {error && (
          <div className="bg-destructive/10 border border-destructive/30 rounded-2xl p-5 flex gap-3 items-start">
            <AlertTriangle className="w-5 h-5 text-destructive shrink-0 mt-0.5" />
            <div>
              <p className="font-bold text-destructive text-sm">
                Couldn't load events
              </p>
              <p className="text-sm text-muted-foreground mt-1">{error}</p>
              <p className="text-xs text-muted-foreground mt-2">
                Make sure the competition backend is running and{" "}
                <code className="font-mono text-primary/80">
                  VITE_COMPETITION_API_URL
                </code>{" "}
                points at it.
              </p>
            </div>
          </div>
        )}

        {!error && loading && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="bg-card border border-card-border rounded-3xl p-5 h-56 animate-pulse"
              />
            ))}
          </div>
        )}

        {!error && !loading && events && events.length === 0 && (
          <div className="bg-card border border-card-border rounded-3xl p-10 text-center">
            <Trophy className="w-10 h-10 text-muted-foreground mx-auto mb-3" />
            <p className="font-bold text-foreground">
              No live events right now
            </p>
            <p className="text-sm text-muted-foreground mt-1">
              Check back soon, or ask an admin to publish one.
            </p>
          </div>
        )}

        {!error && !loading && events && events.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {events.map((event) => {
              const exercise = getExerciseById(event.exerciseId);
              return (
                <Link
                  key={event.id}
                  href={`/events/${event.id}`}
                  className="group block"
                >
                  <div
                    data-testid={`card-event-${event.id}`}
                    className="bg-card border border-card-border rounded-3xl p-5 h-full min-h-56 transition-all duration-300 hover:border-primary/50 hover:-translate-y-1 hover:shadow-xl hover:shadow-primary/10 relative overflow-hidden flex flex-col justify-between"
                  >
                    <div className="absolute top-4 right-4 z-10 flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-primary/15 text-primary text-[10px] font-black uppercase tracking-widest">
                      <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
                      Live
                    </div>

                    <div className="mb-6">
                      <div className="w-12 h-1 rounded-full bg-accent mb-6 transition-all group-hover:w-20" />
                      <h2 className="text-2xl font-bold tracking-tight mb-1 pr-16 group-hover:text-primary transition-colors">
                        {event.name}
                      </h2>
                      <p className="text-sm text-muted-foreground line-clamp-2">
                        {event.description ||
                          exercise?.tagline ||
                          `${event.exerciseName} competition`}
                      </p>
                    </div>

                    <div className="flex flex-wrap gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      <span className="flex items-center gap-1.5 bg-secondary px-2.5 py-1 rounded-md">
                        <Repeat className="w-3.5 h-3.5" />
                        {event.rounds} {event.rounds === 1 ? "round" : "rounds"}
                      </span>
                      <span className="flex items-center gap-1.5 bg-secondary px-2.5 py-1 rounded-md">
                        <Timer className="w-3.5 h-3.5" />
                        {event.roundDurationSeconds}s
                      </span>
                      <span className="flex items-center gap-1.5 bg-secondary px-2.5 py-1 rounded-md">
                        <Users className="w-3.5 h-3.5" />
                        {event.maxParticipants} max
                      </span>
                    </div>

                    {event.activeRooms > 0 && (
                      <p className="mt-3 text-xs text-primary font-bold uppercase tracking-wider">
                        {event.activeRooms} room
                        {event.activeRooms === 1 ? "" : "s"} in progress
                      </p>
                    )}

                    <ArrowUpRight className="absolute right-5 bottom-5 w-5 h-5 text-muted-foreground group-hover:text-primary transition-colors" />
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
