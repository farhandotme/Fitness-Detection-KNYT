import React, { useEffect } from "react";
import { useRoute, useLocation, Link } from "wouter";
import { Navbar } from "@/components/Navbar";
import { useCompetitionRoom } from "@/hooks/useCompetitionRoom";
import { Users, Wifi, WifiOff, LogOut, AlertTriangle, User as UserIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export function WaitingRoomPage() {
  const [match, params] = useRoute("/competitions/:competitionId/waiting");
  const [, setLocation] = useLocation();
  const competitionId = params?.competitionId;

  const { room, identity, error, cancelled, connected, leave } = useCompetitionRoom(competitionId);

  // No stored identity for this room means the user landed here directly
  // (e.g. a stale link or refresh after clearing storage) - send them to join properly.
  useEffect(() => {
    if (competitionId && !identity) {
      const timeout = setTimeout(() => {
        if (!identity) setLocation(`/events`);
      }, 1500);
      return () => clearTimeout(timeout);
    }
  }, [competitionId, identity, setLocation]);

  // Once the room starts counting down (or has moved further along), the
  // action moves to the play screen, which owns rendering the 3-2-1 itself.
  useEffect(() => {
    if (!room) return;
    if (room.status !== "WAITING" && room.status !== "FULL") {
      setLocation(`/competitions/${room.competitionId}/play`);
    }
  }, [room, setLocation]);

  if (!match || !competitionId) {
    return <div className="p-8 text-center text-destructive">Room not found.</div>;
  }

  if (cancelled) {
    return (
      <div className="min-h-dvh bg-background text-foreground">
        <Navbar />
        <main className="max-w-2xl mx-auto p-4 mt-6">
          <div className="bg-card border border-card-border rounded-4xl p-6 md:p-8 shadow-sm text-center">
            <AlertTriangle className="w-10 h-10 text-destructive mx-auto mb-4" />
            <h1 className="text-2xl font-black tracking-tight mb-2">Event cancelled</h1>
            <p className="text-muted-foreground mb-8">{cancelled}</p>
            <Link
              href="/events"
              className="inline-flex items-center gap-2 bg-primary text-primary-foreground px-6 py-3 rounded-2xl font-black uppercase tracking-wider hover:brightness-110 transition-all"
            >
              Browse other events
            </Link>
          </div>
        </main>
      </div>
    );
  }

  const filledSeats = room?.participants.length ?? 0;
  const totalSeats = room?.maxParticipants ?? 5;
  const seats = Array.from({ length: totalSeats }, (_, i) => room?.participants[i] ?? null);

  return (
    <div className="min-h-dvh bg-background text-foreground">
      <Navbar />

      <main className="max-w-2xl mx-auto p-4 mt-6">
        {error && (
          <div className="bg-destructive/10 border border-destructive/30 rounded-2xl p-4 mb-6 flex gap-3 items-start">
            <AlertTriangle className="w-5 h-5 text-destructive shrink-0 mt-0.5" />
            <p className="text-sm text-destructive font-semibold">{error}</p>
          </div>
        )}

        <div className="bg-card border border-card-border rounded-4xl p-6 md:p-8 shadow-sm text-center">
          <div className="flex items-center justify-center gap-2 text-xs font-bold uppercase tracking-[.2em] text-primary mb-3">
            {connected ? <Wifi className="w-4 h-4" /> : <WifiOff className="w-4 h-4 text-destructive" />}
            {connected ? "Connected" : "Reconnecting..."}
          </div>

          <h1 className="text-2xl md:text-3xl font-black tracking-tight mb-1">
            {room?.eventName ?? "Loading room..."}
          </h1>
          <p className="text-muted-foreground mb-8">
            Waiting for players to fill the room
          </p>

          <div className="flex items-center justify-center gap-2 mb-8">
            <Users className="w-5 h-5 text-primary" />
            <span className="font-mono text-2xl font-black text-foreground">
              {filledSeats} / {totalSeats}
            </span>
            <span className="text-sm text-muted-foreground uppercase tracking-wider">
              players
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-8">
            {seats.map((participant, index) => (
              <div
                key={participant?.participantId ?? `empty-${index}`}
                data-testid={
                  participant ? `seat-filled-${index}` : `seat-empty-${index}`
                }
                className={cn(
                  "flex items-center gap-3 rounded-2xl border px-4 py-3 text-left transition-colors",
                  participant
                    ? "border-primary/30 bg-primary/5"
                    : "border-dashed border-border bg-background/40",
                )}
              >
                <div
                  className={cn(
                    "w-9 h-9 rounded-full flex items-center justify-center shrink-0",
                    participant ? "bg-primary text-primary-foreground" : "bg-secondary text-muted-foreground",
                  )}
                >
                  <UserIcon className="w-4 h-4" />
                </div>
                <div className="min-w-0">
                  <p
                    className={cn(
                      "font-bold truncate",
                      participant ? "text-foreground" : "text-muted-foreground",
                    )}
                  >
                    {participant?.displayName ?? "Waiting for player..."}
                  </p>
                  {participant && (
                    <p className="text-[10px] uppercase tracking-widest text-muted-foreground">
                      {participant.connected ? "Ready" : "Reconnecting"}
                      {participant.participantId === identity?.participantId ? " · You" : ""}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>

          <button
            onClick={() => {
              leave();
              setLocation("/events");
            }}
            data-testid="button-leave-waiting-room"
            className="inline-flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-muted-foreground hover:text-destructive transition-colors"
          >
            <LogOut className="w-4 h-4" />
            Leave room
          </button>
        </div>

        <p className="text-center text-xs text-muted-foreground mt-6">
          Don't want to wait? Check{" "}
          <Link href="/events" className="text-primary hover:underline">
            other live events
          </Link>
          .
        </p>
      </main>
    </div>
  );
}
