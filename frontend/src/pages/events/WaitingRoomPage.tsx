import React, { useEffect, useState } from "react";
import { useRoute, useLocation, Link } from "wouter";
import { Navbar } from "@/components/Navbar";
import { useCompetitionRoom } from "@/hooks/useCompetitionRoom";
import {
  Users,
  Wifi,
  WifiOff,
  LogOut,
  AlertTriangle,
  Lock,
  Globe,
  Rocket,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { PlayerAvatar } from "@/components/PlayerAvatar";

export function WaitingRoomPage() {
  const [match, params] = useRoute("/competitions/:competitionId/waiting");
  const [, setLocation] = useLocation();
  const competitionId = params?.competitionId;

  const {
    room,
    identity,
    error,
    cancelled,
    closed,
    connected,
    leave,
    startRoom,
  } = useCompetitionRoom(competitionId);
  const [confirmingLeave, setConfirmingLeave] = useState(false);
  const [starting, setStarting] = useState(false);

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

  // Hitting the browser back button (or swipe-back) shouldn't silently
  // abandon the seat - the backend now frees it after a short grace period
  // either way, but that leaves everyone else staring at a "Reconnecting..."
  // ghost for ~20s. Intercept back navigation and ask first; if they
  // confirm, actually leave (so the seat opens up immediately) before
  // letting the navigation go through.
  useEffect(() => {
    if (!identity) return;
    // Push a throwaway history entry so the first back-press is ours to
    // intercept instead of immediately leaving the page.
    window.history.pushState(null, "", window.location.href);
    const onPopState = () => {
      setConfirmingLeave(true);
      window.history.pushState(null, "", window.location.href);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [identity]);

  // Closing/refreshing the tab: browsers won't run a custom dialog anymore,
  // but the built-in "Leave site?" prompt is still worth showing while a
  // seat is being held.
  useEffect(() => {
    if (!identity) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [identity]);

  // If starting failed (e.g. someone left right as the host clicked,
  // dropping the room back below minParticipants), the shared socket
  // "error" channel surfaces it here - un-stick the button so they can retry.
  useEffect(() => {
    if (error) setStarting(false);
  }, [error]);

  const confirmLeave = () => {
    leave();
    setConfirmingLeave(false);
    setLocation("/events");
  };

  const myParticipant = room?.participants.find(
    (p) => p.participantId === identity?.participantId,
  );
  const isHost = myParticipant?.isHost === true;

  const handleStart = () => {
    setStarting(true);
    startRoom();
  };

  if (!match || !competitionId) {
    return (
      <div className="p-8 text-center text-destructive">Room not found.</div>
    );
  }

  if (cancelled) {
    return (
      <div className="min-h-dvh bg-background text-foreground">
        <Navbar />
        <main className="max-w-2xl mx-auto p-4 mt-6">
          <div className="bg-card border border-card-border rounded-4xl p-6 md:p-8 shadow-sm text-center">
            <AlertTriangle className="w-10 h-10 text-destructive mx-auto mb-4" />
            <h1 className="text-2xl font-black tracking-tight mb-2">
              Event cancelled
            </h1>
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

  // The host (whoever created this room) left or disconnected for good, so
  // the whole room was torn down server-side - see useCompetitionRoom.ts.
  if (closed) {
    return (
      <div className="min-h-dvh bg-background text-foreground">
        <Navbar />
        <main className="max-w-2xl mx-auto p-4 mt-6">
          <div className="bg-card border border-card-border rounded-4xl p-6 md:p-8 shadow-sm text-center">
            <AlertTriangle className="w-10 h-10 text-destructive mx-auto mb-4" />
            <h1 className="text-2xl font-black tracking-tight mb-2">
              Room closed
            </h1>
            <p className="text-muted-foreground mb-8">{closed}</p>
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
  const seats = Array.from(
    { length: totalSeats },
    (_, i) => room?.participants[i] ?? null,
  );
  const canStartEarly =
    isHost &&
    room?.status === "WAITING" &&
    room.minParticipants > 0 &&
    filledSeats >= room.minParticipants &&
    filledSeats < room.maxParticipants;

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
            {connected ? (
              <Wifi className="w-4 h-4" />
            ) : (
              <WifiOff className="w-4 h-4 text-destructive" />
            )}
            {connected ? "Connected" : "Reconnecting..."}
          </div>

          <h1 className="text-2xl md:text-3xl font-black tracking-tight mb-1">
            {room?.roomName ?? "Loading room..."}
          </h1>
          {room && (
            <div className="flex items-center justify-center gap-2 mb-2">
              <span
                className={cn(
                  "inline-flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider px-2.5 py-1 rounded-full",
                  room.visibility === "private"
                    ? "bg-secondary text-muted-foreground"
                    : "bg-primary/15 text-primary",
                )}
              >
                {room.visibility === "private" ? (
                  <Lock className="w-3 h-3" />
                ) : (
                  <Globe className="w-3 h-3" />
                )}
                {room.visibility}
              </span>
              <span className="text-xs text-muted-foreground font-medium">
                {room.eventName}
              </span>
            </div>
          )}
          <p className="text-muted-foreground mb-8">
            {canStartEarly
              ? `You can start now, or wait for up to ${totalSeats} players`
              : isHost &&
                  room?.status === "WAITING" &&
                  room.minParticipants > filledSeats
                ? `Need ${room.minParticipants - filledSeats} more to be able to start early`
                : "Waiting for players to fill the room"}
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
                {participant ? (
                  <PlayerAvatar
                    name={participant.displayName}
                    src={participant.avatarUrl}
                    seed={participant.participantId}
                    isSelf={
                      participant.participantId === identity?.participantId
                    }
                  />
                ) : (
                  <div className="w-9 h-9 rounded-full border border-dashed border-border shrink-0" />
                )}
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
                      {participant.isHost ? " · Host" : ""}
                      {participant.participantId === identity?.participantId
                        ? " · You"
                        : ""}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>

          {canStartEarly && (
            <button
              onClick={handleStart}
              disabled={starting}
              data-testid="button-start-room-early"
              className="w-full h-13 mb-4 rounded-2xl bg-primary text-primary-foreground font-black uppercase tracking-wider text-sm hover:brightness-110 active:scale-[0.98] transition-all disabled:opacity-60 flex items-center justify-center gap-2"
            >
              <Rocket className="w-4 h-4" />
              {starting
                ? "Starting..."
                : `Start Now (${filledSeats}/${totalSeats})`}
            </button>
          )}

          <button
            onClick={() => setConfirmingLeave(true)}
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

      {confirmingLeave && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="bg-card border border-card-border rounded-3xl p-6 md:p-8 max-w-sm w-full shadow-2xl animate-in fade-in zoom-in-95 duration-200">
            <div className="w-11 h-11 rounded-2xl bg-destructive/15 text-destructive flex items-center justify-center mb-4">
              <LogOut className="w-5 h-5" />
            </div>
            <h2 className="text-lg font-black tracking-tight mb-1.5">
              Leave this room?
            </h2>
            <p className="text-sm text-muted-foreground mb-6">
              {isHost
                ? "You created this room, so leaving will close it for everyone still in it - not just free your seat."
                : "Your seat will open up for someone else, and you'll need to rejoin from the event page to get back in."}
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => setConfirmingLeave(false)}
                className="flex-1 py-3 rounded-2xl text-sm font-bold uppercase tracking-wider bg-secondary text-foreground hover:bg-secondary/80 transition-colors"
              >
                Stay
              </button>
              <button
                onClick={confirmLeave}
                data-testid="button-confirm-leave-waiting-room"
                className="flex-1 py-3 rounded-2xl text-sm font-black uppercase tracking-wider bg-destructive text-destructive-foreground hover:brightness-110 transition-all"
              >
                Leave
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
