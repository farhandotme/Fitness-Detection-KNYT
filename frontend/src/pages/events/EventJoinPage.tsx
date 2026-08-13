import React, { useEffect, useState } from "react";
import { useRoute, useLocation, Link } from "wouter";
import { Navbar } from "@/components/Navbar";
import { fetchEventDetail } from "@/lib/competitionApi";
import { useJoinCompetition } from "@/hooks/useCompetitionRoom";
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

  useEffect(() => {
    if (!eventId) return;
    setLoading(true);
    fetchEventDetail(eventId)
      .then(setEvent)
      .catch((err) => setLoadError(err.message || "Event not found"))
      .finally(() => setLoading(false));
  }, [eventId]);

  if (!match || !eventId) {
    return (
      <div className="p-8 text-center text-destructive">Event not found.</div>
    );
  }

  const exercise = event ? getExerciseById(event.exerciseId) : undefined;

  const handleJoin = async () => {
    const name = displayName.trim();
    if (!name || !event) return;
    try {
      const ack = await join(event.id, name);
      setLocation(`/competitions/${ack.competitionId}/waiting`);
    } catch {
      // error is surfaced via joinError below
    }
  };

  return (
    <div className="min-h-dvh bg-background text-foreground">
      <Navbar />

      <main className="max-w-2xl mx-auto p-4 mt-6">
        <Link
          href="/events"
          data-testid="link-back-events"
          className="inline-flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors mb-6"
        >
          <ArrowLeft className="w-4 h-4" />
          All events
        </Link>

        {loading && (
          <div className="bg-card border border-card-border rounded-3xl p-8 h-64 animate-pulse" />
        )}

        {!loading && loadError && (
          <div className="bg-destructive/10 border border-destructive/30 rounded-2xl p-5 flex gap-3 items-start">
            <AlertTriangle className="w-5 h-5 text-destructive shrink-0 mt-0.5" />
            <div>
              <p className="font-bold text-destructive text-sm">
                Couldn't load this event
              </p>
              <p className="text-sm text-muted-foreground mt-1">{loadError}</p>
            </div>
          </div>
        )}

        {!loading && event && (
          <div className="bg-card border border-card-border rounded-4xl p-6 md:p-8 shadow-sm">
            <div className="flex items-center gap-2 text-primary text-xs uppercase tracking-[.2em] font-bold mb-4">
              <Sparkles className="w-4 h-4" /> Live competition
            </div>
            <h1 className="text-3xl md:text-4xl font-black tracking-tighter mb-2">
              {event.name}
            </h1>
            <p className="text-muted-foreground mb-6 max-w-md">
              {event.description ||
                exercise?.tagline ||
                `${event.exerciseName} competition`}
            </p>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8">
              <Stat
                icon={<Users className="w-4 h-4" />}
                label="Players"
                value={`${event.maxParticipants} max`}
              />
              <Stat
                icon={<Repeat className="w-4 h-4" />}
                label="Rounds"
                value={String(event.rounds)}
              />
              <Stat
                icon={<Timer className="w-4 h-4" />}
                label="Round"
                value={`${event.roundDurationSeconds}s`}
              />
              <Stat
                icon={<Coffee className="w-4 h-4" />}
                label="Break"
                value={`${event.breakDurationSeconds}s`}
              />
            </div>

            <div className="border-t border-border pt-6">
              <label className="block text-xs font-bold uppercase tracking-[.16em] text-muted-foreground mb-3">
                Your display name
              </label>
              <input
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value.slice(0, 24))}
                onKeyDown={(e) => e.key === "Enter" && handleJoin()}
                placeholder="e.g. Farhan"
                data-testid="input-display-name"
                className="w-full h-14 rounded-2xl border border-input bg-background px-5 text-lg font-semibold text-foreground outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/15"
                maxLength={24}
                autoFocus
              />
              <p className="text-xs text-muted-foreground mt-2">
                No account needed - this name is just how other players will see
                you in this room.
              </p>

              {joinError && (
                <p className="text-sm text-destructive mt-3 font-semibold">
                  {joinError}
                </p>
              )}

              <button
                onClick={handleJoin}
                disabled={!displayName.trim() || joining}
                data-testid="button-join-competition"
                className="mt-6 w-full bg-primary text-primary-foreground py-5 rounded-2xl font-black text-xl uppercase tracking-wider flex items-center justify-center gap-3 hover:brightness-110 active:scale-[0.98] transition-all shadow-xl shadow-primary/20 disabled:opacity-50 disabled:pointer-events-none"
              >
                <Play className="fill-current w-6 h-6" />
                {joining ? "Joining..." : "Join Competition"}
              </button>
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
    <div className="rounded-2xl border border-border bg-background/60 p-4">
      <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
        {icon}
        {label}
      </div>
      <p className="text-xl font-mono font-bold text-foreground">{value}</p>
    </div>
  );
}
