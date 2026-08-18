import { useCallback, useEffect, useRef, useState } from "react";
import {
  clearParticipantIdentity,
  getCompetitionSocket,
  loadParticipantIdentity,
  saveParticipantIdentity,
} from "@/lib/competitionSocket";
import { getDeviceId } from "@/lib/deviceId";
import { deleteMyAvatar } from "@/lib/avatarStore";
import type {
  JoinedAckPayload,
  ParticipantIdentity,
  RoomLocationInput,
  RoomStateSnapshot,
  RoomVisibility,
  SocketErrorPayload,
} from "@/types/competition";

/** Subscribes to a competition room's live state and exposes actions on it. */
export function useCompetitionRoom(competitionId: string | undefined) {
  const [room, setRoom] = useState<RoomStateSnapshot | null>(null);
  const [identity, setIdentity] = useState<ParticipantIdentity | null>(
    competitionId ? loadParticipantIdentity(competitionId) : null,
  );
  const [error, setError] = useState<string | null>(null);
  const [cancelled, setCancelled] = useState<string | null>(null);
  const [closed, setClosed] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!competitionId) return;
    const socket = getCompetitionSocket();
    setConnected(socket.connected);

    const onRoomState = (payload: RoomStateSnapshot) => {
      if (payload.competitionId === competitionId) setRoom(payload);
    };
    const onReconnected = (payload: { room: RoomStateSnapshot }) =>
      setRoom(payload.room);
    const onSocketError = (payload: SocketErrorPayload) =>
      setError(payload.message);
    // The scheduler (services/eventScheduler.ts) sends this if a scheduled
    // event's start time arrives without enough participants having
    // joined - the room this participant is waiting in gets called off.
    const onCancelled = (payload: {
      competitionId: string;
      reason: string;
    }) => {
      if (payload.competitionId === competitionId) {
        setCancelled(payload.reason);
        clearParticipantIdentity(competitionId);
        deleteMyAvatar();
      }
    };
    // The room's host left/disconnected for good - the whole room was torn
    // down server-side (see competitionEngine "room:closed" in
    // sockets/handlers.ts) rather than just freeing their seat.
    const onClosed = (payload: { competitionId: string; reason: string }) => {
      if (payload.competitionId === competitionId) {
        setClosed(payload.reason);
        clearParticipantIdentity(competitionId);
        deleteMyAvatar();
      }
    };
    const onConnect = () => {
      setConnected(true);
      // Rejoin the Socket.IO room after any reconnect (e.g. brief network drop).
      const stored = loadParticipantIdentity(competitionId);
      if (stored) socket.emit("competition:reconnect", stored);
    };
    const onDisconnect = () => setConnected(false);

    socket.on("room:state", onRoomState);
    socket.on("competition:reconnected", onReconnected);
    socket.on("competition:cancelled", onCancelled);
    socket.on("room:closed", onClosed);
    socket.on("error", onSocketError);
    socket.on("connect", onConnect);
    socket.on("disconnect", onDisconnect);

    const stored = loadParticipantIdentity(competitionId);
    if (stored) {
      setIdentity(stored);
      socket.emit("competition:reconnect", stored);
    }

    return () => {
      socket.off("room:state", onRoomState);
      socket.off("competition:reconnected", onReconnected);
      socket.off("competition:cancelled", onCancelled);
      socket.off("room:closed", onClosed);
      socket.off("error", onSocketError);
      socket.off("connect", onConnect);
      socket.off("disconnect", onDisconnect);
    };
  }, [competitionId]);

  const submitScore = useCallback(
    (round: number, score: number, status?: "RUNNING" | "PAUSED" | "DONE") => {
      if (!competitionId || !identity) return;
      getCompetitionSocket().emit("score:update", {
        competitionId,
        participantId: identity.participantId,
        participantToken: identity.participantToken,
        round,
        score,
        status,
      });
    },
    [competitionId, identity],
  );

  const leave = useCallback(() => {
    if (!competitionId || !identity) return;
    getCompetitionSocket().emit("competition:leave", {
      competitionId,
      participantId: identity.participantId,
      participantToken: identity.participantToken,
    });
    clearParticipantIdentity(competitionId);
    // Ends the "for the time being" avatar's lifetime along with the seat -
    // see lib/avatarStore.ts.
    deleteMyAvatar();
  }, [competitionId, identity]);

  // Host-only: start the room now instead of waiting for it to fill all
  // the way to maxParticipants. The backend rejects this below
  // room.minParticipants (see services/competitionService.ts
  // startRoomEarly) and surfaces that rejection through the same "error"
  // socket event submitScore/leave use, so it lands in `error` above.
  const startRoom = useCallback(() => {
    if (!competitionId || !identity) return;
    getCompetitionSocket().emit("room:start", {
      competitionId,
      participantId: identity.participantId,
      participantToken: identity.participantToken,
    });
  }, [competitionId, identity]);

  return {
    room,
    identity,
    error,
    cancelled,
    closed,
    connected,
    submitScore,
    leave,
    startRoom,
    setError,
  };
}

/**
 * One-shot room create/join flow used from the rooms lobby. Participants no
 * longer get auto-matched into a room - they either spin up their own
 * (createRoom) or pick one from the lobby list (joinRoom), see
 * pages/events/RoomsLobbyPage.tsx.
 */
export function useJoinCompetition() {
  const [joining, setJoining] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pendingRef = useRef(false);

  const runJoin = useCallback(
    (
      event: string,
      payload: Record<string, unknown>,
    ): Promise<JoinedAckPayload> => {
      return new Promise((resolve, reject) => {
        if (pendingRef.current) return;
        pendingRef.current = true;
        setJoining(true);
        setError(null);

        const socket = getCompetitionSocket();

        const cleanup = () => {
          socket.off("competition:joined", onJoined);
          socket.off("error", onError);
          pendingRef.current = false;
          setJoining(false);
        };

        const onJoined = (ack: JoinedAckPayload) => {
          cleanup();
          saveParticipantIdentity({
            competitionId: ack.competitionId,
            participantId: ack.participantId,
            participantToken: ack.participantToken,
          });
          resolve(ack);
        };

        const onError = (err: SocketErrorPayload) => {
          cleanup();
          setError(err.message);
          reject(new Error(err.message));
        };

        socket.on("competition:joined", onJoined);
        socket.on("error", onError);
        socket.emit(event, payload);
      });
    },
    [],
  );

  // deviceId lets the backend recognize repeat attempts from this browser
  // and reattach to the existing seat instead of creating a duplicate
  // participant - see lib/deviceId.ts.
  const createRoom = useCallback(
    (
      eventId: string,
      roomName: string,
      visibility: RoomVisibility,
      displayName: string,
      password?: string,
      avatarUrl?: string,
      avatarPublicId?: string,
      // Optional - set when the host opts in to tagging this room's
      // location, so it's findable from the "Live near you" / "choose a
      // region" search embedded in the Events page. See
      // config/countries.ts and hooks/useGeolocation.ts.
      location?: RoomLocationInput,
    ) =>
      runJoin("room:create", {
        eventId,
        roomName,
        visibility,
        password,
        displayName,
        deviceId: getDeviceId(),
        avatarUrl,
        avatarPublicId,
        location,
      }),
    [runJoin],
  );

  const joinRoom = useCallback(
    (
      competitionId: string,
      displayName: string,
      password?: string,
      avatarUrl?: string,
      avatarPublicId?: string,
    ) =>
      runJoin("room:join", {
        competitionId,
        displayName,
        password,
        deviceId: getDeviceId(),
        avatarUrl,
        avatarPublicId,
      }),
    [runJoin],
  );

  return { createRoom, joinRoom, joining, error, setError };
}
