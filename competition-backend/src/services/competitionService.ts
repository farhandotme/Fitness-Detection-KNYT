import { CompetitionModel, type CompetitionDoc } from "../models/Competition.js";
import { AppError } from "../utils/errors.js";
import { verifyToken } from "../utils/token.js";
import {
  buildLeaderboard,
  clearRoomState,
  getCumulativeScores,
  getParticipants,
  hasParticipant,
  isParticipantConnected,
  joinRoomAtomic,
  removeParticipant,
  setParticipantConnected,
  setScore,
} from "./redisState.js";
import { logger } from "../config/logger.js";
import type { RoomStateSnapshot } from "../types/index.js";
import { competitionEngine } from "./competitionEngine.js";
import { deleteAvatarBestEffort } from "./avatarService.js";

// Room creation/joining now lives in services/roomService.ts - participants
// pick or create a specific room from the event's lobby rather than being
// auto-matched into one. This file keeps everything that operates on a
// room *after* someone is already seated in it (reconnect, leave, score,
// snapshot) plus the disconnect-grace-period bookkeeping shared by both.
export interface JoinResult {
  competitionId: string;
  participantId: string;
  participantToken: string;
  room: RoomStateSnapshot;
}

export async function reconnectToCompetition(
  competitionId: string,
  participantId: string,
  participantToken: string,
): Promise<RoomStateSnapshot> {
  const room = await CompetitionModel.findById(competitionId).lean<CompetitionDoc | null>();
  if (!room) throw AppError.notFound("Competition not found");

  const participant = room.participants.find((p) => p.participantId === participantId);
  if (!participant || !verifyToken(participantToken, participant.tokenHash)) {
    throw AppError.forbidden("Invalid participant credentials");
  }

  const isMember = await hasParticipant(competitionId, participantId);
  if (!isMember && room.status !== "COMPLETED") {
    // Room state expired in Redis (e.g. server restart) but the match is
    // still ongoing in Mongo - restore live membership so the leaderboard
    // and round logic keep working.
    await joinRoomAtomic(competitionId, room.maxParticipants, participantId, participant.displayName);
  }
  await setParticipantConnected(competitionId, participantId, true);
  cancelPendingRemoval(competitionId, participantId);

  const snapshot = await getRoomSnapshot(competitionId);
  if (!snapshot) throw AppError.notFound("Competition not found");
  return snapshot;
}

// How long a dropped connection gets before we treat it as an actual
// departure. Covers the "closed the tab / hit back / phone locked" case
// without punishing a normal refresh or a few seconds of flaky wifi - both
// of those reconnect (via socket "connect" -> competition:reconnect) well
// inside this window, which calls cancelPendingRemoval below.
const DISCONNECT_GRACE_MS = 20_000;

// In-memory only (single process) - if the server restarts mid-grace-period
// the timer is simply lost, which just means that one participant lingers
// as "disconnected" a little longer than usual; nothing is corrupted.
const pendingRemovals = new Map<string, ReturnType<typeof setTimeout>>();
const pendingKey = (competitionId: string, participantId: string) => `${competitionId}:${participantId}`;

export function cancelPendingRemoval(competitionId: string, participantId: string): void {
  const key = pendingKey(competitionId, participantId);
  const timer = pendingRemovals.get(key);
  if (timer) {
    clearTimeout(timer);
    pendingRemovals.delete(key);
  }
}

/**
 * The room's host (whoever created it - see models/Competition.ts) is gone
 * for good, so the room itself is torn down rather than just freeing their
 * seat: mark it ABANDONED, stop any pending lifecycle timer
 * (countdown/round/break), and drop its live Redis state. Safe to call more
 * than once - a room that's already finished or already torn down is left
 * alone.
 */
export async function destroyRoomAsHostLeft(competitionId: string): Promise<boolean> {
  const room = await CompetitionModel.findById(competitionId);
  if (!room) return false;
  if (room.status === "COMPLETED" || room.status === "ABANDONED") return false;

  room.status = "ABANDONED";
  await room.save();

  competitionEngine.cancelRoom(competitionId);
  await clearRoomState(competitionId);

  // The room is gone for good, so every photo anyone in it uploaded goes
  // with it - nobody left to show it to (see services/avatarService.ts).
  for (const participant of room.participants) {
    deleteAvatarBestEffort(participant.avatarPublicId);
  }

  logger.info({ competitionId }, "room destroyed - host left");
  return true;
}

/**
 * Called when a participant's socket disconnects.
 *
 * For an ordinary participant: if the room hasn't started yet
 * (WAITING/FULL), a still-empty seat left behind by a closed tab is worse
 * than a freed one - it blocks the room from filling and can stall a
 * scheduled event's minimum-participant check. So: mark them disconnected
 * immediately (existing "Reconnecting..." UI for everyone else), then
 * actually free the seat if they haven't come back within
 * DISCONNECT_GRACE_MS. Once the room is live, the old "just mark
 * disconnected, keep the seat for scoring" behavior is unchanged.
 *
 * For the room's host (see models/Competition.ts): the same grace period
 * applies, but at *any* room status short of COMPLETED - if they don't
 * reconnect, the whole room is destroyed (onHostLeft) rather than just
 * freeing their seat, since the room only exists because they made it.
 */
export async function handleParticipantDisconnect(
  competitionId: string,
  participantId: string,
  onRemoved: () => void | Promise<void>,
  onHostLeft: () => void | Promise<void>,
): Promise<void> {
  await setParticipantConnected(competitionId, participantId, false);

  const room = await CompetitionModel.findById(competitionId).lean<CompetitionDoc | null>();
  if (!room || room.status === "COMPLETED" || room.status === "ABANDONED") return;

  const participant = room.participants.find((p) => p.participantId === participantId);
  const isHost = participant?.isHost === true;

  // Non-host seats are only ever freed pre-start, same as before.
  if (!isHost && room.status !== "WAITING" && room.status !== "FULL") return;

  const key = pendingKey(competitionId, participantId);
  cancelPendingRemoval(competitionId, participantId);

  const timer = setTimeout(async () => {
    pendingRemovals.delete(key);
    try {
      const backOnline = await isParticipantConnected(competitionId, participantId);
      if (backOnline) return;

      const current = await CompetitionModel.findById(competitionId).lean<CompetitionDoc | null>();
      if (!current || current.status === "COMPLETED" || current.status === "ABANDONED") return;
      const stillSeated = current.participants.some((p) => p.participantId === participantId);
      if (!stillSeated) return;

      if (isHost) {
        const destroyed = await destroyRoomAsHostLeft(competitionId);
        if (destroyed) await onHostLeft();
        return;
      }

      if (current.status !== "WAITING" && current.status !== "FULL") return;

      const leaving = current.participants.find((p) => p.participantId === participantId);
      await removeParticipant(competitionId, participantId);
      await CompetitionModel.updateOne({ _id: competitionId }, { $pull: { participants: { participantId } } });
      deleteAvatarBestEffort(leaving?.avatarPublicId);
      logger.info(
        { competitionId, participantId },
        "removed participant who never reconnected after leaving the waiting room",
      );
      await onRemoved();
    } catch (err) {
      logger.error({ err }, "error cleaning up disconnected waiting-room participant");
    }
  }, DISCONNECT_GRACE_MS);

  pendingRemovals.set(key, timer);
}

export interface LeaveResult {
  // True when leaving destroyed the room outright because the leaver was
  // its host - see destroyRoomAsHostLeft. Callers (sockets/handlers.ts)
  // use this to tell everyone else the room is gone instead of just
  // broadcasting an updated room:state.
  hostLeft: boolean;
}

export async function leaveCompetition(
  competitionId: string,
  participantId: string,
  participantToken: string,
): Promise<LeaveResult> {
  const room = await CompetitionModel.findById(competitionId).lean<CompetitionDoc | null>();
  if (!room) return { hostLeft: false };
  const participant = room.participants.find((p) => p.participantId === participantId);
  if (!participant || !verifyToken(participantToken, participant.tokenHash)) {
    throw AppError.forbidden("Invalid participant credentials");
  }
  cancelPendingRemoval(competitionId, participantId);

  // The host owns the room - if they leave, the room closes for everyone
  // rather than just freeing their seat, regardless of what phase it's in.
  if (participant.isHost) {
    const destroyed = await destroyRoomAsHostLeft(competitionId);
    return { hostLeft: destroyed };
  }

  // Only allow leaving outright before the competition has started; once
  // it's running we keep the seat (marked disconnected) so scoring/ranking
  // for the round remains consistent, matching the reconnection design.
  if (room.status === "WAITING" || room.status === "FULL") {
    await removeParticipant(competitionId, participantId);
    await CompetitionModel.updateOne({ _id: competitionId }, { $pull: { participants: { participantId } } });
    // Seat's actually gone (not just marked disconnected), so the photo
    // that went with it can go too.
    deleteAvatarBestEffort(participant.avatarPublicId);
  } else {
    await setParticipantConnected(competitionId, participantId, false);
  }
  return { hostLeft: false };
}

export async function submitScore(
  competitionId: string,
  participantId: string,
  participantToken: string,
  round: number,
  score: number,
): Promise<void> {
  const room = await CompetitionModel.findById(competitionId).lean<CompetitionDoc | null>();
  if (!room) throw AppError.notFound("Competition not found");

  const participant = room.participants.find((p) => p.participantId === participantId);
  if (!participant || !verifyToken(participantToken, participant.tokenHash)) {
    throw AppError.forbidden("Invalid participant credentials");
  }

  // The frontend is never trusted as the source of truth for official
  // results - it may only push scores while its own round is officially
  // running, and only for the round the server currently has active.
  if (room.status !== "ROUND_RUNNING" || room.currentRound !== round) {
    return;
  }

  await setScore(competitionId, round, participantId, Math.max(0, Math.floor(score)));
  await competitionEngine.broadcastLeaderboard(competitionId);
}

export async function getRoomSnapshot(competitionId: string): Promise<RoomStateSnapshot | null> {
  const room = await CompetitionModel.findById(competitionId).lean<CompetitionDoc | null>();
  if (!room) return null;

  const liveParticipants = await getParticipants(competitionId);
  // Merge Mongo (authoritative identity/history) with Redis (live connection state).
  const participants = room.participants.map((p) => {
    const live = liveParticipants.find((lp) => lp.participantId === p.participantId);
    return {
      participantId: p.participantId,
      displayName: p.displayName,
      connected: live?.connected ?? false,
      isHost: p.isHost === true,
      // Mongo is authoritative for identity/history (see file header
      // comment) so avatarUrl comes from there too, not the Redis copy -
      // it just needs to be broadcast, not merged with anything live.
      avatarUrl: p.avatarUrl ?? null,
    };
  });

  const cumulative = await getCumulativeScores(competitionId, room.currentRound || 0);
  const leaderboard = buildLeaderboard(participants, cumulative);

  const engineState = competitionEngine.getTimings(competitionId);

  return {
    competitionId,
    eventId: String(room.eventId),
    eventName: room.eventName,
    roomName: room.roomName,
    visibility: room.visibility as RoomStateSnapshot["visibility"],
    exerciseId: room.exerciseId,
    exerciseMode: room.exerciseMode as "reps" | "hold",
    status: room.status as RoomStateSnapshot["status"],
    maxParticipants: room.maxParticipants,
    totalRounds: room.totalRounds,
    currentRound: room.currentRound,
    roundDurationSeconds: room.roundDurationSeconds,
    breakDurationSeconds: room.breakDurationSeconds,
    participants,
    leaderboard,
    countdownEndAt: engineState.countdownEndAt,
    roundStartAt: engineState.roundStartAt,
    roundEndAt: engineState.roundEndAt,
    breakEndAt: engineState.breakEndAt,
    serverNow: Date.now(),
  };
}
