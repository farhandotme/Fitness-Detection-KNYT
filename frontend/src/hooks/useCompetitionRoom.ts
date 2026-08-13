import { useCallback, useEffect, useRef, useState } from "react";
import {
  clearParticipantIdentity,
  getCompetitionSocket,
  loadParticipantIdentity,
  saveParticipantIdentity,
} from "@/lib/competitionSocket";
import { getDeviceId } from "@/lib/deviceId";
import type {
  JoinedAckPayload,
  ParticipantIdentity,
  RoomStateSnapshot,
  SocketErrorPayload,
} from "@/types/competition";

/** Subscribes to a competition room's live state and exposes actions on it. */
export function useCompetitionRoom(competitionId: string | undefined) {
  const [room, setRoom] = useState<RoomStateSnapshot | null>(null);
  const [identity, setIdentity] = useState<ParticipantIdentity | null>(
    competitionId ? loadParticipantIdentity(competitionId) : null,
  );
  const [error, setError] = useState<string | null>(null);
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
    const onConnect = () => {
      setConnected(true);
      // Rejoin the Socket.IO room after any reconnect (e.g. brief network drop).
      const stored = loadParticipantIdentity(competitionId);
      if (stored) socket.emit("competition:reconnect", stored);
    };
    const onDisconnect = () => setConnected(false);

    socket.on("room:state", onRoomState);
    socket.on("competition:reconnected", onReconnected);
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
  }, [competitionId, identity]);

  return { room, identity, error, connected, submitScore, leave, setError };
}

/** One-shot join flow used from the event lobby / join screen. */
export function useJoinCompetition() {
  const [joining, setJoining] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pendingRef = useRef(false);

  const join = useCallback(
    (eventId: string, displayName: string): Promise<JoinedAckPayload> => {
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

        const onJoined = (payload: JoinedAckPayload) => {
          cleanup();
          saveParticipantIdentity({
            competitionId: payload.competitionId,
            participantId: payload.participantId,
            participantToken: payload.participantToken,
          });
          resolve(payload);
        };

        const onError = (payload: SocketErrorPayload) => {
          cleanup();
          setError(payload.message);
          reject(new Error(payload.message));
        };

        socket.on("competition:joined", onJoined);
        socket.on("error", onError);
        // deviceId lets the backend recognize repeat join attempts from this
        // browser and reattach to the existing seat instead of creating a
        // duplicate participant - see lib/deviceId.ts.
        socket.emit("competition:join", {
          eventId,
          displayName,
          deviceId: getDeviceId(),
        });
      });
    },
    [],
  );

  return { join, joining, error };
}
