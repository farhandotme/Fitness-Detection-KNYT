import { useEffect, useRef, useState } from "react";
import { getCompetitionSocket } from "@/lib/competitionSocket";
import { getAdminToken } from "@/lib/adminApi";
import type { RoomStateSnapshot } from "@/types/competition";

/**
 * Read-only live view of a competition room for the admin dashboard. Unlike
 * useCompetitionRoom (frontend/src/hooks/useCompetitionRoom.ts), this never
 * joins as a participant - it rides the same "room:state" broadcasts every
 * participant socket already gets, via the backend's admin:spectate handler
 * (competition-backend/src/sockets/handlers.ts), so watching never occupies
 * one of the room's 5 seats or appears in the participant list.
 */
export function useAdminSpectate(competitionId: string | undefined) {
  const [room, setRoom] = useState<RoomStateSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [closedReason, setClosedReason] = useState<string | null>(null);
  const roomRef = useRef<RoomStateSnapshot | null>(null);

  useEffect(() => {
    if (!competitionId) return;
    const socket = getCompetitionSocket();
    const adminToken = getAdminToken();
    if (!adminToken) {
      setError("Your admin session has expired. Please log in again.");
      return;
    }

    const onSpectating = (payload: { room: RoomStateSnapshot }) => {
      roomRef.current = payload.room;
      setRoom(payload.room);
      setConnected(true);
      setError(null);
    };
    const onRoomState = (snapshot: RoomStateSnapshot) => {
      if (snapshot.competitionId !== competitionId) return;
      roomRef.current = snapshot;
      setRoom(snapshot);
    };
    const onError = (payload: { code: string; message: string }) => {
      setError(payload.message);
    };
    // The room was torn down server-side - either its host never
    // reconnected, or (see competition-backend/src/services/
    // competitionService.ts destroyRoomAsAbandoned) every single
    // participant disconnected and none of them came back. Without this,
    // this view would just keep showing whatever the last "room:state"
    // broadcast was forever, looking like the match is still live.
    const onClosed = (payload: { competitionId: string; reason: string }) => {
      if (payload.competitionId === competitionId) {
        setClosedReason(payload.reason);
      }
    };
    const onDisconnect = () => setConnected(false);
    const onReconnect = () => {
      socket.emit("admin:spectate", { competitionId, adminToken });
    };

    socket.on("admin:spectating", onSpectating);
    socket.on("room:state", onRoomState);
    socket.on("room:closed", onClosed);
    socket.on("error", onError);
    socket.on("disconnect", onDisconnect);
    socket.io.on("reconnect", onReconnect);

    socket.emit("admin:spectate", { competitionId, adminToken });

    return () => {
      socket.off("admin:spectating", onSpectating);
      socket.off("room:state", onRoomState);
      socket.off("room:closed", onClosed);
      socket.off("error", onError);
      socket.off("disconnect", onDisconnect);
      socket.io.off("reconnect", onReconnect);
    };
  }, [competitionId]);

  return { room, error, connected, closedReason };
}
