import { io, type Socket } from "socket.io-client";
import type { ParticipantIdentity } from "@/types/competition";

function getWsBase(): string {
  return (
    import.meta.env.VITE_COMPETITION_WS_URL ||
    localStorage.getItem("COMPETITION_API_BASE_OVERRIDE") ||
    "http://localhost:4000"
  ).replace(/\/+$/, "");
}

let socket: Socket | null = null;

/**
 * One Socket.IO connection is shared across every competition page
 * (join → waiting room → play → results) so the participant is never
 * silently dropped from Socket.IO's room just because React navigated.
 */
export function getCompetitionSocket(): Socket {
  if (!socket) {
    socket = io(getWsBase(), {
      autoConnect: true,
      transports: ["websocket", "polling"],
      reconnection: true,
    });
  }
  return socket;
}

function identityKey(competitionId: string) {
  return `competition_identity:${competitionId}`;
}

export function saveParticipantIdentity(identity: ParticipantIdentity): void {
  localStorage.setItem(identityKey(identity.competitionId), JSON.stringify(identity));
}

export function loadParticipantIdentity(competitionId: string): ParticipantIdentity | null {
  const raw = localStorage.getItem(identityKey(competitionId));
  if (!raw) return null;
  try {
    return JSON.parse(raw) as ParticipantIdentity;
  } catch {
    return null;
  }
}

export function clearParticipantIdentity(competitionId: string): void {
  localStorage.removeItem(identityKey(competitionId));
}
