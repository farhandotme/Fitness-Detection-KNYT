import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useRoute, useLocation, Link } from "wouter";
import { Navbar } from "@/components/Navbar";
import {
  fetchEventDetail,
  fetchEventRooms,
  revealRoom,
} from "@/lib/competitionApi";
import { useJoinCompetition } from "@/hooks/useCompetitionRoom";
import { AvatarPicker } from "@/components/AvatarPicker";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { getMyAvatar, type StoredAvatar } from "@/lib/avatarStore";
import type {
  EventDetail,
  RoomListEntry,
  RoomVisibility,
} from "@/types/competition";
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
  Search,
  Crown,
  ArrowRight,
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

  // Search & Filter state
  const [searchQuery, setSearchQuery] = useState("");
  const [filterVisibility, setFilterVisibility] = useState<
    "all" | "public" | "private"
  >("all");

  const [showCreate, setShowCreate] = useState(false);
  const [activeRoom, setActiveRoom] = useState<RoomListEntry | null>(null);

  const {
    createRoom,
    joinRoom,
    joining,
    error: actionError,
    setError: setActionError,
  } = useJoinCompetition();

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

  const filteredRooms = useMemo(() => {
    if (!rooms) return null;
    return rooms.filter((room) => {
      const matchesSearch = room.roomName
        .toLowerCase()
        .includes(searchQuery.toLowerCase().trim());
      const matchesVisibility =
        filterVisibility === "all" || room.visibility === filterVisibility;
      return matchesSearch && matchesVisibility;
    });
  }, [rooms, searchQuery, filterVisibility]);

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
    <div className="min-h-dvh bg-background text-foreground pb-20 selection:bg-primary/30 relative overflow-hidden">
      {/* Decorative ambient background blur */}
      <div className="absolute top-0 inset-x-0 h-96 bg-primary/5 blur-[120px] rounded-full pointer-events-none" />

      <Navbar />

      <main className="max-w-4xl mx-auto p-4 md:p-6 mt-4 relative z-10">
        <Link
          href={`/events/${eventId}`}
          className="inline-flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-muted-foreground hover:text-primary transition-colors mb-6 group"
        >
          <ArrowLeft className="w-4 h-4 group-hover:-translate-x-1 transition-transform" />
          Back to Event
        </Link>

        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
          <div>
            <h1 className="font-display text-3xl md:text-4xl font-black tracking-tight text-foreground drop-shadow-sm">
              {event?.name ?? "Rooms"}
            </h1>
            <p className="text-sm text-muted-foreground mt-2 font-medium">
              Join a room someone else made, or start your own.
            </p>
          </div>
          <button
            onClick={() => setShowCreate(true)}
            data-testid="button-create-room"
            className="shrink-0 inline-flex items-center justify-center gap-2 bg-primary text-primary-foreground px-6 py-3.5 rounded-2xl font-black uppercase tracking-widest text-xs hover:brightness-110 hover:shadow-[0_0_20px_rgba(var(--primary),0.3)] active:scale-[0.98] transition-all cursor-pointer border border-primary/50"
          >
            <Plus className="w-4 h-4" />
            Create Room
          </button>
        </div>

        {/* Search Bar & Visibility Filters */}
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 mb-8 bg-card/50 p-2 rounded-3xl border border-border/50 backdrop-blur-sm">
          <div className="relative flex-1">
            <Search className="w-4 h-4 absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by room name..."
              className="w-full h-12 pl-11 pr-8 rounded-2xl border-none bg-transparent text-sm font-semibold placeholder:text-muted-foreground outline-none focus:ring-0 transition-all"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery("")}
                className="absolute right-3.5 top-1/2 -translate-y-1/2 bg-secondary/80 text-muted-foreground hover:text-foreground p-1.5 rounded-full transition-colors"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          <div className="w-px h-8 bg-border/50 hidden sm:block mx-1"></div>

          <div className="flex items-center gap-1.5 p-1 shrink-0 self-start sm:self-auto">
            {(["all", "public", "private"] as const).map((type) => (
              <button
                key={type}
                onClick={() => setFilterVisibility(type)}
                className={cn(
                  "px-5 py-2.5 rounded-xl text-[11px] font-bold uppercase tracking-wider transition-all capitalize cursor-pointer",
                  filterVisibility === type
                    ? "bg-primary/10 text-primary border border-primary/20 shadow-sm"
                    : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground border border-transparent",
                )}
              >
                {type}
              </button>
            ))}
          </div>
        </div>

        {loadError && (
          <div className="bg-destructive/10 border border-destructive/20 rounded-3xl p-5 mb-8 flex gap-3 items-center shadow-sm">
            <div className="bg-destructive/20 p-2 rounded-xl">
              <AlertTriangle className="w-5 h-5 text-destructive shrink-0" />
            </div>
            <p className="text-sm text-destructive font-bold">{loadError}</p>
          </div>
        )}

        {rooms === null && !loadError && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="h-44 rounded-3xl bg-secondary/30 border border-border/30 animate-pulse"
              />
            ))}
          </div>
        )}

        {rooms !== null && filteredRooms && filteredRooms.length === 0 && (
          <div className="rounded-[2rem] border border-dashed border-border/60 bg-card/30 p-16 text-center backdrop-blur-sm flex flex-col items-center justify-center">
            <div className="w-16 h-16 bg-secondary/50 rounded-2xl flex items-center justify-center mb-4 border border-border/50 shadow-inner">
              <DoorOpen className="w-8 h-8 text-muted-foreground opacity-80" />
            </div>
            <p className="font-extrabold text-foreground text-lg tracking-tight">
              {rooms.length === 0
                ? "No rooms open yet"
                : "No matching rooms found"}
            </p>
            <p className="text-sm text-muted-foreground mt-2 max-w-sm">
              {rooms.length === 0
                ? "Be the first to create one for this event and invite others to play."
                : "Try adjusting your search query or switching your filter settings."}
            </p>
          </div>
        )}

        {/* 2 Rooms Per Row (Grid Layout) */}
        {filteredRooms !== null &&
          filteredRooms &&
          filteredRooms.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              {filteredRooms.map((room) => (
                <RoomCard
                  key={room.competitionId}
                  room={room}
                  onSelect={() => setActiveRoom(room)}
                />
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
          onCreate={async (
            roomName,
            visibility,
            displayName,
            password,
            avatar,
          ) => {
            const ack = await createRoom(
              eventId,
              roomName,
              visibility,
              displayName,
              password,
              avatar?.url,
              avatar?.publicId,
            );
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
          onJoin={async (displayName, password, avatar) => {
            const ack = await joinRoom(
              activeRoom.competitionId,
              displayName,
              password,
              avatar?.url,
              avatar?.publicId,
            );
            handleJoined(ack.competitionId);
          }}
          joining={joining}
          error={actionError}
        />
      )}
    </div>
  );
}

function RoomCard({
  room,
  onSelect,
}: {
  room: RoomListEntry;
  onSelect: () => void;
}) {
  const isFull = room.participantCount >= room.maxParticipants;
  const hostName = room.participantNames?.[0];

  return (
    <button
      onClick={onSelect}
      data-testid={`room-row-${room.competitionId}`}
      className="w-full text-left rounded-[2rem] border border-border/60 bg-card/60 backdrop-blur-md p-6 flex flex-col justify-between gap-5 hover:border-primary/50 hover:bg-card/90 hover:shadow-[0_8px_30px_rgb(0,0,0,0.12)] hover:-translate-y-1 transition-all duration-300 group cursor-pointer relative overflow-hidden"
    >
      {/* Subtle hover gradient inside card */}
      <div className="absolute inset-0 bg-gradient-to-br from-primary/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none" />

      <div className="flex items-start justify-between gap-3 relative z-10">
        <div className="flex items-center gap-4 min-w-0">
          <div
            className={cn(
              "w-12 h-12 rounded-2xl flex items-center justify-center shrink-0 border shadow-inner transition-colors duration-300",
              room.visibility === "private"
                ? "bg-secondary/80 border-border/50 text-muted-foreground group-hover:bg-secondary"
                : "bg-primary/10 border-primary/20 text-primary group-hover:bg-primary/20",
            )}
          >
            {room.visibility === "private" ? (
              <Lock className="w-5 h-5" />
            ) : (
              <Globe className="w-5 h-5" />
            )}
          </div>
          <div className="min-w-0">
            <h3 className="font-extrabold text-lg text-foreground truncate group-hover:text-primary transition-colors duration-300 tracking-tight">
              {room.roomName}
            </h3>
            {hostName ? (
              <p className="flex items-center gap-1.5 text-[13px] text-muted-foreground mt-0.5 truncate font-medium">
                <Crown className="w-3.5 h-3.5 text-primary shrink-0 drop-shadow-sm" />
                <span>
                  Created by{" "}
                  <strong className="text-foreground font-bold">
                    {hostName}
                  </strong>
                </span>
              </p>
            ) : (
              <p className="text-[13px] text-muted-foreground mt-0.5 font-medium">
                {room.visibility === "private"
                  ? "Password required"
                  : "Public room"}
              </p>
            )}
          </div>
        </div>

        <span
          className={cn(
            "text-[10px] font-black uppercase tracking-widest px-3 py-1.5 rounded-full shrink-0 border transition-colors",
            room.visibility === "private"
              ? "bg-secondary/50 text-muted-foreground border-border/50"
              : "bg-primary/10 text-primary border-primary/20 shadow-[0_0_10px_rgba(var(--primary),0.1)]",
          )}
        >
          {room.visibility}
        </span>
      </div>

      {/* Players Preview Section */}
      <div className="bg-background/60 border border-border/30 rounded-2xl p-3.5 flex items-center justify-between gap-3 relative z-10">
        {room.visibility === "public" &&
        room.participantNames &&
        room.participantNames.length > 0 ? (
          <div className="flex items-center gap-3 min-w-0">
            <div className="flex -space-x-2.5 shrink-0">
              {room.participantNames.slice(0, 4).map((name, i) => (
                <PlayerAvatar
                  key={`${name}-${i}`}
                  name={name}
                  seed={`${name}-${i}`}
                  src={room.participantAvatars?.[i]}
                  size="sm"
                  className="ring-2 ring-background drop-shadow-sm"
                />
              ))}
            </div>
            <p className="text-[13px] text-muted-foreground truncate font-semibold">
              {room.participantNames.join(", ")}
            </p>
          </div>
        ) : (
          <p className="text-[13px] text-muted-foreground font-medium flex items-center gap-2">
            {room.visibility === "private" ? (
              <>
                <KeyRound className="w-3.5 h-3.5" /> Enter password to view
                players
              </>
            ) : (
              "No players in room yet"
            )}
          </p>
        )}

        <div className="shrink-0 flex items-center gap-1.5 text-xs font-mono font-bold bg-card px-3 py-1.5 rounded-xl border border-border/50 shadow-sm">
          <Users className="w-3.5 h-3.5 text-muted-foreground" />
          <span className={isFull ? "text-destructive" : "text-foreground"}>
            {room.participantCount}/{room.maxParticipants}
          </span>
        </div>
      </div>

      {/* Action Footer */}
      <div className="flex items-center justify-between text-xs font-bold pt-1 relative z-10">
        <span
          className={cn(
            "text-[11px] font-black uppercase tracking-widest",
            isFull ? "text-destructive" : "text-primary/80",
          )}
        >
          {isFull ? "Room Full" : "Available to Join"}
        </span>
        <span className="flex items-center gap-1.5 text-primary group-hover:translate-x-1.5 transition-transform duration-300 tracking-wide">
          JOIN ROOM <ArrowRight className="w-4 h-4" />
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
  onCreate: (
    roomName: string,
    visibility: RoomVisibility,
    displayName: string,
    password: string | undefined,
    avatar: StoredAvatar | null,
  ) => Promise<void>;
  joining: boolean;
  error: string | null;
}) {
  const [roomName, setRoomName] = useState("");
  const [visibility, setVisibility] = useState<RoomVisibility>("public");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [avatar, setAvatar] = useState<StoredAvatar | null>(() =>
    getMyAvatar(),
  );

  const canSubmit =
    roomName.trim().length > 0 &&
    displayName.trim().length > 0 &&
    (visibility === "public" || password.trim().length >= 4);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit || joining) return;
    try {
      await onCreate(
        roomName.trim(),
        visibility,
        displayName.trim(),
        visibility === "private" ? password.trim() : undefined,
        avatar,
      );
    } catch {
      // error surfaced via `error` prop
    }
  };

  return (
    <ModalShell onClose={onClose} title="Create a Room">
      <form onSubmit={handleSubmit} className="space-y-6">
        <AvatarPicker name={displayName} value={avatar} onChange={setAvatar} />

        <Field label="Room Name">
          <input
            value={roomName}
            onChange={(e) => setRoomName(e.target.value.slice(0, 60))}
            placeholder="e.g. Me & Rahul"
            autoFocus
            data-testid="input-room-name"
            className="w-full h-12 rounded-2xl border border-border/50 bg-background/50 px-4 font-semibold text-sm text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary/50 transition-all placeholder:text-muted-foreground/70 shadow-sm"
          />
        </Field>

        <Field label="Visibility">
          <div className="grid grid-cols-2 gap-3">
            <button
              type="button"
              onClick={() => setVisibility("public")}
              className={cn(
                "h-12 rounded-2xl border flex items-center justify-center gap-2 text-sm font-bold transition-all cursor-pointer shadow-sm",
                visibility === "public"
                  ? "border-primary bg-primary/10 text-primary ring-1 ring-primary/20 shadow-[0_0_10px_rgba(var(--primary),0.1)]"
                  : "border-border/50 bg-background/50 text-muted-foreground hover:border-border hover:text-foreground",
              )}
            >
              <Globe className="w-4 h-4" /> Public
            </button>
            <button
              type="button"
              onClick={() => setVisibility("private")}
              className={cn(
                "h-12 rounded-2xl border flex items-center justify-center gap-2 text-sm font-bold transition-all cursor-pointer shadow-sm",
                visibility === "private"
                  ? "border-primary bg-primary/10 text-primary ring-1 ring-primary/20 shadow-[0_0_10px_rgba(var(--primary),0.1)]"
                  : "border-border/50 bg-background/50 text-muted-foreground hover:border-border hover:text-foreground",
              )}
            >
              <Lock className="w-4 h-4" /> Private
            </button>
          </div>
        </Field>

        {visibility === "private" && (
          <Field label="Room Password">
            <input
              type="text"
              value={password}
              onChange={(e) => setPassword(e.target.value.slice(0, 50))}
              placeholder="At least 4 characters"
              data-testid="input-room-password"
              className="w-full h-12 rounded-2xl border border-border/50 bg-background/50 px-4 font-semibold text-sm text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary/50 transition-all placeholder:text-muted-foreground/70 shadow-sm"
            />
          </Field>
        )}

        <Field label="Your Display Name">
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value.slice(0, 24))}
            placeholder="Enter your gamertag..."
            data-testid="input-create-display-name"
            className="w-full h-12 rounded-2xl border border-border/50 bg-background/50 px-4 font-semibold text-sm text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary/50 transition-all placeholder:text-muted-foreground/70 shadow-sm"
          />
        </Field>

        {error && (
          <div className="p-3 rounded-2xl bg-destructive/10 border border-destructive/20 text-sm text-destructive font-bold flex items-center gap-2 shadow-sm">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={!canSubmit || joining}
          data-testid="button-submit-create-room"
          className="w-full h-14 mt-2 rounded-2xl bg-primary text-primary-foreground font-black uppercase tracking-widest text-sm hover:brightness-110 active:scale-[0.98] transition-all disabled:opacity-50 disabled:hover:brightness-100 disabled:active:scale-100 flex items-center justify-center gap-2 cursor-pointer shadow-[0_4px_14px_rgba(var(--primary),0.3)] hover:shadow-[0_6px_20px_rgba(var(--primary),0.4)] border border-primary/50"
        >
          {joining && <RefreshCw className="w-4 h-4 animate-spin" />}
          {joining ? "CREATING..." : "CREATE & JOIN"}
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
  onJoin: (
    displayName: string,
    password: string | undefined,
    avatar: StoredAvatar | null,
  ) => Promise<void>;
  joining: boolean;
  error: string | null;
}) {
  const [password, setPassword] = useState("");
  const [unlocked, setUnlocked] = useState(room.visibility === "public");
  const [unlockError, setUnlockError] = useState<string | null>(null);
  const [unlocking, setUnlocking] = useState(false);
  const [participantNames, setParticipantNames] = useState<
    string[] | undefined
  >(room.participantNames);
  const [participantAvatars, setParticipantAvatars] = useState<
    (string | null)[] | undefined
  >(room.participantAvatars);
  const [displayName, setDisplayName] = useState("");
  const [avatar, setAvatar] = useState<StoredAvatar | null>(() =>
    getMyAvatar(),
  );

  const handleUnlock = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password.trim() || unlocking) return;
    setUnlocking(true);
    setUnlockError(null);
    try {
      const preview = await revealRoom(
        eventId,
        room.competitionId,
        password.trim(),
      );
      setParticipantNames(preview.participantNames);
      setParticipantAvatars(preview.participantAvatars);
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
      await onJoin(
        displayName.trim(),
        room.visibility === "private" ? password.trim() : undefined,
        avatar,
      );
    } catch {
      // error surfaced via `error` prop
    }
  };

  const isFull = room.participantCount >= room.maxParticipants;

  return (
    <ModalShell onClose={onClose} title={room.roomName}>
      {!unlocked ? (
        <form onSubmit={handleUnlock} className="space-y-6">
          <div className="bg-secondary/30 border border-border/50 rounded-2xl p-4 flex gap-3 shadow-inner">
            <div className="bg-primary/10 p-2 rounded-xl h-fit shrink-0">
              <Lock className="w-5 h-5 text-primary" />
            </div>
            <div>
              <p className="text-sm font-bold text-foreground">Private Room</p>
              <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
                This room is protected. Enter its password to see who's inside
                and join the game.
              </p>
            </div>
          </div>

          <Field label="Room Password">
            <input
              type="text"
              value={password}
              onChange={(e) => setPassword(e.target.value.slice(0, 50))}
              autoFocus
              data-testid="input-unlock-password"
              className="w-full h-12 rounded-2xl border border-border/50 bg-background/50 px-4 font-semibold text-sm text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary/50 transition-all placeholder:text-muted-foreground/70 shadow-sm"
            />
          </Field>
          {unlockError && (
            <div className="p-3 rounded-2xl bg-destructive/10 border border-destructive/20 text-sm text-destructive font-bold flex items-center gap-2 shadow-sm">
              <AlertTriangle className="w-4 h-4 shrink-0" />
              {unlockError}
            </div>
          )}
          <button
            type="submit"
            disabled={!password.trim() || unlocking}
            data-testid="button-unlock-room"
            className="w-full h-14 mt-2 rounded-2xl bg-primary text-primary-foreground font-black uppercase tracking-widest text-sm hover:brightness-110 active:scale-[0.98] transition-all disabled:opacity-50 flex items-center justify-center gap-2 cursor-pointer shadow-[0_4px_14px_rgba(var(--primary),0.3)] hover:shadow-[0_6px_20px_rgba(var(--primary),0.4)] border border-primary/50"
          >
            {unlocking && <RefreshCw className="w-4 h-4 animate-spin" />}
            {!unlocking && <KeyRound className="w-4 h-4" />}
            {unlocking ? "CHECKING..." : "UNLOCK ROOM"}
          </button>
        </form>
      ) : (
        <form onSubmit={handleJoin} className="space-y-6">
          <div className="bg-background/50 border border-border/50 rounded-2xl p-4 shadow-inner">
            <div className="flex items-center justify-between mb-3">
              <p className="text-[10px] font-black uppercase tracking-widest text-muted-foreground">
                Players inside
              </p>
              <div className="text-xs font-mono font-bold bg-secondary/80 px-2 py-0.5 rounded-md text-foreground">
                {room.participantCount} / {room.maxParticipants}
              </div>
            </div>

            {participantNames && participantNames.length > 0 ? (
              <div className="flex flex-wrap gap-2.5">
                {participantNames.map((name, i) => (
                  <span
                    key={`${name}-${i}`}
                    className="inline-flex items-center gap-2 text-xs font-bold pl-1.5 pr-3.5 py-1.5 rounded-full bg-secondary/80 border border-border/50 text-foreground shadow-sm"
                  >
                    <PlayerAvatar
                      name={name}
                      seed={`${name}-${i}`}
                      src={participantAvatars?.[i]}
                      size="sm"
                      className="shadow-sm"
                    />
                    {name}
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground font-medium italic">
                No one here yet - be the first to join.
              </p>
            )}
          </div>

          <AvatarPicker
            name={displayName}
            value={avatar}
            onChange={setAvatar}
          />

          <Field label="Your Display Name">
            <input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value.slice(0, 24))}
              placeholder="Enter your gamertag..."
              autoFocus
              disabled={isFull}
              data-testid="input-join-display-name"
              className="w-full h-12 rounded-2xl border border-border/50 bg-background/50 px-4 font-semibold text-sm text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary/50 transition-all disabled:opacity-50 shadow-sm placeholder:text-muted-foreground/70"
            />
          </Field>

          {error && (
            <div className="p-3 rounded-2xl bg-destructive/10 border border-destructive/20 text-sm text-destructive font-bold flex items-center gap-2 shadow-sm">
              <AlertTriangle className="w-4 h-4 shrink-0" />
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={!displayName.trim() || joining || isFull}
            data-testid="button-submit-join-room"
            className="w-full h-14 mt-2 rounded-2xl bg-primary text-primary-foreground font-black uppercase tracking-widest text-sm hover:brightness-110 active:scale-[0.98] transition-all disabled:opacity-50 disabled:hover:brightness-100 flex items-center justify-center gap-2 cursor-pointer shadow-[0_4px_14px_rgba(var(--primary),0.3)] hover:shadow-[0_6px_20px_rgba(var(--primary),0.4)] border border-primary/50"
          >
            {joining && <RefreshCw className="w-4 h-4 animate-spin" />}
            {isFull ? "ROOM FULL" : joining ? "JOINING..." : "JOIN ROOM"}
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
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
      <div className="bg-card border border-border/60 rounded-[24px] p-6 md:p-8 max-w-md w-full shadow-[0_0_50px_rgba(0,0,0,0.5)] animate-in fade-in zoom-in-95 duration-200 max-h-[90vh] overflow-y-auto relative">
        <div className="flex items-center justify-between mb-8">
          <h2 className="text-xl font-black tracking-tight truncate pr-4 text-foreground drop-shadow-sm">
            {title}
          </h2>
          <button
            onClick={onClose}
            data-testid="button-close-modal"
            className="shrink-0 w-8 h-8 rounded-full bg-secondary/50 flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary transition-all cursor-pointer border border-transparent hover:border-border/50"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <label className="block text-[10px] font-black uppercase tracking-widest text-muted-foreground ml-1">
        {label}
      </label>
      {children}
    </div>
  );
}
