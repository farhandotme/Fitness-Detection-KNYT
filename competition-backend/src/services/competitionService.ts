import {
  CompetitionModel,
  type CompetitionDoc,
} from "../models/Competition.js";
import { AppError } from "../utils/errors.js";
import { verifyToken } from "../utils/token.js";
import {
  buildLeaderboard,
  clearRoomState,
  getCumulativeScores,
  getParticipantCount,
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
  const room = await CompetitionModel.findById(
    competitionId,
  ).lean<CompetitionDoc | null>();
  if (!room) throw AppError.notFound("Competition not found");

  const participant = room.participants.find(
    (p) => p.participantId === participantId,
  );
  if (!participant || !verifyToken(participantToken, participant.tokenHash)) {
    throw AppError.forbidden("Invalid participant credentials");
  }

  const isMember = await hasParticipant(competitionId, participantId);
  if (!isMember && room.status !== "COMPLETED") {
    // Room state expired in Redis (e.g. server restart) but the match is
    // still ongoing in Mongo - restore live membership so the leaderboard
    // and round logic keep working.
    await joinRoomAtomic(
      competitionId,
      room.maxParticipants,
      participantId,
      participant.displayName,
    );
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
const pendingKey = (competitionId: string, participantId: string) =>
  `${competitionId}:${participantId}`;

export function cancelPendingRemoval(
  competitionId: string,
  participantId: string,
): void {
  const key = pendingKey(competitionId, participantId);
  const timer = pendingRemovals.get(key);
  if (timer) {
    clearTimeout(timer);
    pendingRemovals.delete(key);
  }
}

/**
 * Shared teardown for a room nobody is left to finish: mark it ABANDONED,
 * stop any pending lifecycle timer (countdown/round/break), and drop its
 * live Redis state. Safe to call more than once - a room that's already
 * finished or already torn down is left alone. `reason` is just for the
 * server log; callers below expose their own named wrappers.
 */
async function destroyRoom(
  competitionId: string,
  reason: string,
): Promise<boolean> {
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

  logger.info({ competitionId, reason }, "room destroyed");
  return true;
}

/**
 * The room's host (whoever created it - see models/Competition.ts) is gone
 * for good, so the room itself is torn down rather than just freeing their
 * seat.
 */
export async function destroyRoomAsHostLeft(
  competitionId: string,
): Promise<boolean> {
  return destroyRoom(competitionId, "host left and never reconnected");
}

/**
 * Every single seat - host included - is now disconnected and none of them
 * came back within the grace period. Nobody is left to actually finish the
 * match, so instead of letting it run unattended to completion (and
 * lingering as "live" on the admin dashboard with no one in it), tear the
 * room down the same way a host-leave does.
 */
export async function destroyRoomAsAbandoned(
  competitionId: string,
): Promise<boolean> {
  return destroyRoom(competitionId, "every participant disconnected");
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
 * DISCONNECT_GRACE_MS. Once the room is live, their seat is kept instead
 * (so scoring/leaderboard stay consistent for a round already in
 * progress) - but we still check, once their own grace period has passed,
 * whether *every* remaining seat is now also disconnected. If so nobody is
 * actually present to finish the match, so the room is torn down
 * (onEveryoneLeft) rather than left running unattended.
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
  onEveryoneLeft: () => void | Promise<void>,
): Promise<void> {
  await setParticipantConnected(competitionId, participantId, false);

  const room = await CompetitionModel.findById(
    competitionId,
  ).lean<CompetitionDoc | null>();
  if (!room || room.status === "COMPLETED" || room.status === "ABANDONED")
    return;

  const participant = room.participants.find(
    (p) => p.participantId === participantId,
  );
  const isHost = participant?.isHost === true;

  // Non-host seats are only ever freed pre-start, same as before - but a
  // mid-match disconnect still needs its own grace-period timer scheduled
  // below so we can check the "has everyone now left" case once it expires.
  const midMatchNonHost =
    !isHost && room.status !== "WAITING" && room.status !== "FULL";

  const key = pendingKey(competitionId, participantId);
  cancelPendingRemoval(competitionId, participantId);

  const timer = setTimeout(async () => {
    pendingRemovals.delete(key);
    try {
      const backOnline = await isParticipantConnected(
        competitionId,
        participantId,
      );
      if (backOnline) return;

      const current = await CompetitionModel.findById(
        competitionId,
      ).lean<CompetitionDoc | null>();
      if (
        !current ||
        current.status === "COMPLETED" ||
        current.status === "ABANDONED"
      )
        return;
      const stillSeated = current.participants.some(
        (p) => p.participantId === participantId,
      );
      if (!stillSeated) return;

      if (isHost) {
        const destroyed = await destroyRoomAsHostLeft(competitionId);
        if (destroyed) await onHostLeft();
        return;
      }

      if (midMatchNonHost) {
        // Seat stays (scoring stays consistent) - but if literally every
        // other seat is also disconnected right now, nobody is left
        // watching or playing this match, so tear it down instead of
        // letting it run to completion unattended.
        const live = await getParticipants(competitionId);
        const anyoneStillConnected = live.some((p) => p.connected);
        if (!anyoneStillConnected) {
          const destroyed = await destroyRoomAsAbandoned(competitionId);
          if (destroyed) await onEveryoneLeft();
        }
        return;
      }

      if (current.status !== "WAITING" && current.status !== "FULL") return;

      const leaving = current.participants.find(
        (p) => p.participantId === participantId,
      );
      await removeParticipant(competitionId, participantId);
      await CompetitionModel.updateOne(
        { _id: competitionId },
        { $pull: { participants: { participantId } } },
      );
      deleteAvatarBestEffort(leaving?.avatarPublicId);
      logger.info(
        { competitionId, participantId },
        "removed participant who never reconnected after leaving the waiting room",
      );
      await onRemoved();
    } catch (err) {
      logger.error(
        { err },
        "error cleaning up disconnected waiting-room participant",
      );
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
  // True when a mid-match non-host leave turned out to be the very last
  // connected seat - nobody is left to finish the match, so the room was
  // torn down the same way an unattended disconnect grace-period expiry
  // would (see destroyRoomAsAbandoned). Distinct from hostLeft since the
  // reason shown to anyone still watching (e.g. an admin spectator) is
  // different.
  everyoneLeft: boolean;
}

export async function leaveCompetition(
  competitionId: string,
  participantId: string,
  participantToken: string,
): Promise<LeaveResult> {
  const room = await CompetitionModel.findById(
    competitionId,
  ).lean<CompetitionDoc | null>();
  if (!room) return { hostLeft: false, everyoneLeft: false };
  const participant = room.participants.find(
    (p) => p.participantId === participantId,
  );
  if (!participant || !verifyToken(participantToken, participant.tokenHash)) {
    throw AppError.forbidden("Invalid participant credentials");
  }
  cancelPendingRemoval(competitionId, participantId);

  // The host owns the room - if they leave, the room closes for everyone
  // rather than just freeing their seat, regardless of what phase it's in.
  if (participant.isHost) {
    const destroyed = await destroyRoomAsHostLeft(competitionId);
    return { hostLeft: destroyed, everyoneLeft: false };
  }

  // Only allow leaving outright before the competition has started; once
  // it's running we keep the seat (marked disconnected) so scoring/ranking
  // for the round remains consistent, matching the reconnection design.
  if (room.status === "WAITING" || room.status === "FULL") {
    await removeParticipant(competitionId, participantId);
    await CompetitionModel.updateOne(
      { _id: competitionId },
      { $pull: { participants: { participantId } } },
    );
    // Seat's actually gone (not just marked disconnected), so the photo
    // that went with it can go too.
    deleteAvatarBestEffort(participant.avatarPublicId);
    return { hostLeft: false, everyoneLeft: false };
  }

  await setParticipantConnected(competitionId, participantId, false);

  // This leave might have been the last connected seat in the room (e.g.
  // every other participant already left/dropped and only this one was
  // still here). An explicit leave doesn't go through the socket
  // "disconnect" event on this app's shared connection (see
  // lib/competitionSocket.ts), so it wouldn't otherwise trigger the
  // grace-period "everyone's gone" check handleParticipantDisconnect does -
  // check it here instead so the room doesn't linger as "live" with nobody
  // actually in it.
  const live = await getParticipants(competitionId);
  const anyoneStillConnected = live.some((p) => p.connected);
  if (!anyoneStillConnected) {
    const destroyed = await destroyRoomAsAbandoned(competitionId);
    return { hostLeft: false, everyoneLeft: destroyed };
  }

  return { hostLeft: false, everyoneLeft: false };
}

/**
 * The room's host chooses to start early - once at least minParticipants
 * have joined, they don't have to wait for the room to fill all the way to
 * maxParticipants. Reuses the exact same "lock the room and kick off the
 * countdown" path the scheduler uses to force-start a scheduled event's
 * rooms (competitionEngine.triggerScheduledStart), so the two "start
 * before naturally full" mechanisms behave identically from here on.
 */
export async function startRoomEarly(
  competitionId: string,
  participantId: string,
  participantToken: string,
): Promise<void> {
  const room = await CompetitionModel.findById(
    competitionId,
  ).lean<CompetitionDoc | null>();
  if (!room) throw AppError.notFound("Room not found");

  const participant = room.participants.find(
    (p) => p.participantId === participantId,
  );
  if (!participant || !verifyToken(participantToken, participant.tokenHash)) {
    throw AppError.forbidden("Invalid participant credentials");
  }
  if (!participant.isHost) {
    throw AppError.forbidden("Only the room's host can start it early");
  }
  if (room.status !== "WAITING" && room.status !== "FULL") {
    throw AppError.conflict("This room has already started or ended");
  }

  const liveCount = await getParticipantCount(competitionId);
  if (liveCount < room.minParticipants) {
    throw AppError.conflict(
      `Need at least ${room.minParticipants} player${room.minParticipants === 1 ? "" : "s"} to start - ${liveCount} here so far.`,
    );
  }

  await competitionEngine.triggerScheduledStart(competitionId);
}

export async function submitScore(
  competitionId: string,
  participantId: string,
  participantToken: string,
  round: number,
  score: number,
): Promise<void> {
  const room = await CompetitionModel.findById(
    competitionId,
  ).lean<CompetitionDoc | null>();
  if (!room) throw AppError.notFound("Competition not found");

  const participant = room.participants.find(
    (p) => p.participantId === participantId,
  );
  if (!participant || !verifyToken(participantToken, participant.tokenHash)) {
    throw AppError.forbidden("Invalid participant credentials");
  }

  // The frontend is never trusted as the source of truth for official
  // results - it may only push scores while its own round is officially
  // running, and only for the round the server currently has active.
  if (room.status !== "ROUND_RUNNING" || room.currentRound !== round) {
    return;
  }

  await setScore(
    competitionId,
    round,
    participantId,
    Math.max(0, Math.floor(score)),
  );
  await competitionEngine.broadcastLeaderboard(competitionId);
}

export async function getRoomSnapshot(
  competitionId: string,
): Promise<RoomStateSnapshot | null> {
  const room = await CompetitionModel.findById(
    competitionId,
  ).lean<CompetitionDoc | null>();
  if (!room) return null;

  const liveParticipants = await getParticipants(competitionId);
  // Merge Mongo (authoritative identity/history) with Redis (live connection state).
  const participants = room.participants.map((p) => {
    const live = liveParticipants.find(
      (lp) => lp.participantId === p.participantId,
    );
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

  const cumulative = await getCumulativeScores(
    competitionId,
    room.currentRound || 0,
  );
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
    minParticipants: room.minParticipants,
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
