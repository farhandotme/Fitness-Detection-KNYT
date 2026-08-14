import React, { useCallback, useEffect, useState } from "react";
import { useRoute, useLocation, Link } from "wouter";
import { Navbar } from "@/components/Navbar";
import { fetchEventDetail, fetchEventRooms, revealRoom } from "@/lib/competitionApi";
import { useJoinCompetition } from "@/hooks/useCompetitionRoom";
import type { EventDetail, RoomListEntry, RoomVisibility } from "@/types/competition";
import {
  ArrowLeft,
  Users,
  Lock,
  Globe,
  Plus,
  RefreshCw,
  AlertTriangle,
  X,
  DoorOpen,
  KeyRound,
} from "lucide-react";
import { cn } from "@/lib/utils";

const ROOM_LIST_POLL_MS = 4000;

export function RoomsLobbyPage() {
  const [match, params] = useRoute("/events/:eventId/rooms");
  const [, setLocation] = useLocation();
  const eventId = params?.eventId;

  const [event, setEvent] = useState<EventDetail | null>(null);
  const [rooms, setRooms] = useState<RoomListEntry[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [showCreate, setShowCreate] = useState(false);
  const [activeRoom, setActiveRoom] = useState<RoomListEntry | null>(null);

  const { createRoom, joinRoom, joining, error: actionError, setError: setActionError } = useJoinCompetition();

  const refreshRooms = useCallback(() => {
    if (!eventId) return;
    fetchEventRooms(eventId)
      .then((data) => setRooms(data))
      .catch((err) => setLoadError(err.message || "Could not load rooms"));
  }, [eventId]);

  useEffect(() => {
    if (!eventId) return;
    fetchEventDetail(eventId)
      .then(setEvent)
      .catch((err) => setLoadError(err.message || "Event not found"));
  }, [eventId]);

  useEffect(() => {
    refreshRooms();
    const interval = window.setInterval(refreshRooms, ROOM_LIST_POLL_MS);
    return () => window.clearInterval(interval);
  }, [refreshRooms]);

  if (!match || !eventId) {
    return (
      <div className="p-8 text-center font-bold text-destructive flex items-center justify-center min-h-[50vh]">
        <AlertTriangle className="mr-2" /> Event not found.
      </div>
    );
  }

  const handleCreated = (competitionId: string) => {
    setShowCreate(false);
    setLocation(`/competitions/${competitionId}/waiting`);
  };
  const handleJoined = (competitionId: string) => {
    setActiveRoom(null);
    setLocation(`/competitions/${competitionId}/waiting`);
  };

  return (
    <div className="min-h-dvh bg-background text-foreground pb-20 selection:bg-primary/30">
      <Navbar />

      <main className="max-w-3xl mx-auto p-4 md:p-6 mt-4">
        <Link
          href={`/events/${eventId}`}
          className="inline-flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-muted-foreground hover:text-primary transition-colors mb-6 group"
        >
          <ArrowLeft className="w-4 h-4 group-hover:-translate-x-1 transition-transform" />
          Back to Event
        </Link>

        <div className="flex items-center justify-between gap-4 mb-6">
          <div>
            <h1 className="font-display text-2xl md:text-3xl font-extrabold tracking-tight">
              {event?.name ?? "Rooms"}
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              Join a room someone else made, or start your own.
            </p>
          </div>
          <button
            onClick={() => setShowCreate(true)}
            data-testid="button-create-room"
            className="shrink-0 inline-flex items-center gap-2 bg-primary text-primary-foreground px-5 py-3 rounded-2xl font-black uppercase tracking-wider text-sm hover:brightness-110 active:scale-[0.98] transition-all shadow-lg shadow-primary/20"
          >
            <Plus className="w-4 h-4" />
            Create Room
          </button>
        </div>

        {loadError && (
          <div className="bg-destructive/10 border border-destructive/30 rounded-2xl p-4 mb-6 flex gap-3 items-center">
            <AlertTriangle className="w-5 h-5 text-destructive shrink-0" />
            <p className="text-sm text-destructive font-bold">{loadError}</p>
          </div>
        )}

        {rooms === null && !loadError && (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="h-24 rounded-3xl bg-secondary/40 animate-pulse" />
            ))}
          </div>
        )}

        {rooms !== null && rooms.length === 0 && (
          <div className="rounded-3xl border border-dashed border-border bg-card/40 p-10 text-center">
            <DoorOpen className="w-8 h-8 text-muted-foreground mx-auto mb-3" />
            <p className="font-bold text-foreground">No rooms open yet</p>
            <p className="text-sm text-muted-foreground mt-1">
              Be the first to create one for this event.
            </p>
          </div>
        )}

        {rooms !== null && rooms.length > 0 && (
          <div className="space-y-3">
            {rooms.map((room) => (
              <RoomRow key={room.competitionId} room={room} onSelect={() => setActiveRoom(room)} />
            ))}
          </div>
        )}
      </main>

      {showCreate && (
        <CreateRoomModal
          onClose={() => {
            setShowCreate(false);
            setActionError(null);
          }}
          onCreate={async (roomName, visibility, displayName, password) => {
            const ack = await createRoom(eventId, roomName, visibility, displayName, password);
            handleCreated(ack.competitionId);
          }}
          joining={joining}
          error={actionError}
        />
      )}

      {activeRoom && (
        <JoinRoomModal
          eventId={eventId}
          room={activeRoom}
          onClose={() => {
            setActiveRoom(null);
            setActionError(null);
          }}
          onJoin={async (displayName, password) => {
            const ack = await joinRoom(activeRoom.competitionId, displayName, password);
            handleJoined(ack.competitionId);
          }}
          joining={joining}
          error={actionError}
        />
      )}
    </div>
  );
}

function RoomRow({ room, onSelect }: { room: RoomListEntry; onSelect: () => void }) {
  const isFull = room.participantCount >= room.maxParticipants;
  return (
    <button
      onClick={onSelect}
      data-testid={`room-row-${room.competitionId}`}
      className="w-full text-left rounded-3xl border border-border bg-card p-5 flex items-center gap-4 hover:border-primary/40 hover:bg-card/80 transition-all shadow-sm"
    >
      <div
        className={cn(
          "w-11 h-11 rounded-2xl flex items-center justify-center shrink-0",
          room.visibility === "private" ? "bg-secondary text-muted-foreground" : "bg-primary/15 text-primary",
        )}
      >
        {room.visibility === "private" ? <Lock className="w-5 h-5" /> : <Globe className="w-5 h-5" />}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="font-black text-foreground truncate">{room.roomName}</p>
          <span
            className={cn(
              "text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full shrink-0",
              room.visibility === "private"
                ? "bg-secondary text-muted-foreground"
                : "bg-primary/15 text-primary",
            )}
          >
            {room.visibility}
          </span>
        </div>
        {room.visibility === "public" && room.participantNames && room.participantNames.length > 0 ? (
          <p className="text-xs text-muted-foreground truncate mt-1">
            {room.participantNames.join(", ")}
          </p>
        ) : (
          <p className="text-xs text-muted-foreground mt-1">
            {room.visibility === "private" ? "Password required to view players" : "No one here yet"}
          </p>
        )}
      </div>

      <div className="shrink-0 flex items-center gap-1.5 text-sm font-mono font-bold">
        <Users className="w-4 h-4 text-muted-foreground" />
        <span className={isFull ? "text-destructive" : "text-foreground"}>
          {room.participantCount}/{room.maxParticipants}
        </span>
      </div>
    </button>
  );
}

function CreateRoomModal({
  onClose,
  onCreate,
  joining,
  error,
}: {
  onClose: () => void;
  onCreate: (roomName: string, visibility: RoomVisibility, displayName: string, password?: string) => Promise<void>;
  joining: boolean;
  error: string | null;
}) {
  const [roomName, setRoomName] = useState("");
  const [visibility, setVisibility] = useState<RoomVisibility>("public");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");

  const canSubmit =
    roomName.trim().length > 0 &&
    displayName.trim().length > 0 &&
    (visibility === "public" || password.trim().length >= 4);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit || joining) return;
    try {
      await onCreate(roomName.trim(), visibility, displayName.trim(), visibility === "private" ? password.trim() : undefined);
    } catch {
      // error surfaced via `error` prop
    }
  };

  return (
    <ModalShell onClose={onClose} title="Create a Room">
      <form onSubmit={handleSubmit} className="space-y-5">
        <Field label="Room name">
          <input
            value={roomName}
            onChange={(e) => setRoomName(e.target.value.slice(0, 60))}
            placeholder="e.g. Me & Rahul"
            autoFocus
            data-testid="input-room-name"
            className="w-full h-12 rounded-2xl border border-input bg-background px-4 font-semibold text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
          />
        </Field>

        <Field label="Visibility">
          <div className="grid grid-cols-2 gap-3">
            <button
              type="button"
              onClick={() => setVisibility("public")}
              className={cn(
                "rounded-2xl border p-3 flex items-center justify-center gap-2 text-sm font-bold transition-all",
                visibility === "public"
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-input text-muted-foreground hover:border-primary/40",
              )}
            >
              <Globe className="w-4 h-4" /> Public
            </button>
            <button
              type="button"
              onClick={() => setVisibility("private")}
              className={cn(
                "rounded-2xl border p-3 flex items-center justify-center gap-2 text-sm font-bold transition-all",
                visibility === "private"
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-input text-muted-foreground hover:border-primary/40",
              )}
            >
              <Lock className="w-4 h-4" /> Private
            </button>
          </div>
        </Field>

        {visibility === "private" && (
          <Field label="Room password">
            <input
              type="text"
              value={password}
              onChange={(e) => setPassword(e.target.value.slice(0, 50))}
              placeholder="At least 4 characters"
              data-testid="input-room-password"
              className="w-full h-12 rounded-2xl border border-input bg-background px-4 font-semibold text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
            />
          </Field>
        )}

        <Field label="Your display name">
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value.slice(0, 24))}
            placeholder="Enter your gamertag..."
            data-testid="input-create-display-name"
            className="w-full h-12 rounded-2xl border border-input bg-background px-4 font-semibold text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
          />
        </Field>

        {error && (
          <div className="p-3 rounded-2xl bg-destructive/10 border border-destructive/30 text-sm text-destructive font-bold flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={!canSubmit || joining}
          data-testid="button-submit-create-room"
          className="w-full h-13 rounded-2xl bg-primary text-primary-foreground font-black uppercase tracking-wider text-sm hover:brightness-110 active:scale-[0.98] transition-all disabled:opacity-50 flex items-center justify-center gap-2"
        >
          {joining && <RefreshCw className="w-4 h-4 animate-spin" />}
          {joining ? "Creating..." : "Create & Join"}
        </button>
      </form>
    </ModalShell>
  );
}

function JoinRoomModal({
  eventId,
  room,
  onClose,
  onJoin,
  joining,
  error,
}: {
  eventId: string;
  room: RoomListEntry;
  onClose: () => void;
  onJoin: (displayName: string, password?: string) => Promise<void>;
  joining: boolean;
  error: string | null;
}) {
  const [password, setPassword] = useState("");
  const [unlocked, setUnlocked] = useState(room.visibility === "public");
  const [unlockError, setUnlockError] = useState<string | null>(null);
  const [unlocking, setUnlocking] = useState(false);
  const [participantNames, setParticipantNames] = useState<string[] | undefined>(room.participantNames);
  const [displayName, setDisplayName] = useState("");

  const handleUnlock = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password.trim() || unlocking) return;
    setUnlocking(true);
    setUnlockError(null);
    try {
      const preview = await revealRoom(eventId, room.competitionId, password.trim());
      setParticipantNames(preview.participantNames);
      setUnlocked(true);
    } catch (err: any) {
      setUnlockError(err.message || "Incorrect password");
    } finally {
      setUnlocking(false);
    }
  };

  const handleJoin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!displayName.trim() || joining) return;
    try {
      await onJoin(displayName.trim(), room.visibility === "private" ? password.trim() : undefined);
    } catch {
      // error surfaced via `error` prop
    }
  };

  const isFull = room.participantCount >= room.maxParticipants;

  return (
    <ModalShell onClose={onClose} title={room.roomName}>
      {!unlocked ? (
        <form onSubmit={handleUnlock} className="space-y-5">
          <p className="text-sm text-muted-foreground flex items-center gap-2">
            <Lock className="w-4 h-4 text-primary shrink-0" />
            This room is private. Enter its password to see who's inside and join.
          </p>
          <Field label="Room password">
            <input
              type="text"
              value={password}
              onChange={(e) => setPassword(e.target.value.slice(0, 50))}
              autoFocus
              data-testid="input-unlock-password"
              className="w-full h-12 rounded-2xl border border-input bg-background px-4 font-semibold text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
            />
          </Field>
          {unlockError && (
            <div className="p-3 rounded-2xl bg-destructive/10 border border-destructive/30 text-sm text-destructive font-bold flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0" />
              {unlockError}
            </div>
          )}
          <button
            type="submit"
            disabled={!password.trim() || unlocking}
            data-testid="button-unlock-room"
            className="w-full h-13 rounded-2xl bg-primary text-primary-foreground font-black uppercase tracking-wider text-sm hover:brightness-110 active:scale-[0.98] transition-all disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {unlocking && <RefreshCw className="w-4 h-4 animate-spin" />}
            <KeyRound className="w-4 h-4" />
            {unlocking ? "Checking..." : "Unlock Room"}
          </button>
        </form>
      ) : (
        <form onSubmit={handleJoin} className="space-y-5">
          <div>
            <p className="text-xs font-black uppercase tracking-wider text-muted-foreground mb-2">
              Players here now ({room.participantCount}/{room.maxParticipants})
            </p>
            {participantNames && participantNames.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {participantNames.map((name, i) => (
                  <span
                    key={`${name}-${i}`}
                    className="text-xs font-bold px-3 py-1.5 rounded-full bg-secondary text-foreground"
                  >
                    {name}
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No one here yet - be the first to join.</p>
            )}
          </div>

          <Field label="Your display name">
            <input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value.slice(0, 24))}
              placeholder="Enter your gamertag..."
              autoFocus
              disabled={isFull}
              data-testid="input-join-display-name"
              className="w-full h-12 rounded-2xl border border-input bg-background px-4 font-semibold text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 disabled:opacity-50"
            />
          </Field>

          {error && (
            <div className="p-3 rounded-2xl bg-destructive/10 border border-destructive/30 text-sm text-destructive font-bold flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0" />
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={!displayName.trim() || joining || isFull}
            data-testid="button-submit-join-room"
            className="w-full h-13 rounded-2xl bg-primary text-primary-foreground font-black uppercase tracking-wider text-sm hover:brightness-110 active:scale-[0.98] transition-all disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {joining && <RefreshCw className="w-4 h-4 animate-spin" />}
            {isFull ? "Room Full" : joining ? "Joining..." : "Join Room"}
          </button>
        </form>
      )}
    </ModalShell>
  );
}

function ModalShell({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="bg-card border border-card-border rounded-3xl p-6 md:p-8 max-w-md w-full shadow-2xl animate-in fade-in zoom-in-95 duration-200 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-lg font-black tracking-tight truncate pr-4">{title}</h2>
          <button
            onClick={onClose}
            data-testid="button-close-modal"
            className="shrink-0 w-8 h-8 rounded-full bg-secondary flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-black uppercase tracking-wider text-muted-foreground mb-2">
        {label}
      </label>
      {children}
    </div>
  );
}
