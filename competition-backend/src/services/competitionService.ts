import { Types } from "mongoose";
import { CompetitionModel, type CompetitionDoc } from "../models/Competition.js";
import { EventModel } from "../models/Event.js";
import { AppError } from "../utils/errors.js";
import { generateParticipantToken, generateRoomCode, hashToken, verifyToken } from "../utils/token.js";
import {
  buildLeaderboard,
  getCumulativeScores,
  getParticipantCount,
  getParticipants,
  hasParticipant,
  joinRoomAtomic,
  removeParticipant,
  setParticipantConnected,
  setScore,
} from "./redisState.js";
import { logger } from "../config/logger.js";
import type { RoomStateSnapshot } from "../types/index.js";
import { nanoid } from "nanoid";
import { competitionEngine } from "./competitionEngine.js";

const MAX_JOIN_ATTEMPTS = 5;

async function findOpenRoom(eventId: string, maxParticipants: number): Promise<CompetitionDoc | null> {
  const room = await CompetitionModel.findOne({
    eventId,
    status: "WAITING",
  })
    .sort({ createdAt: 1 })
    .lean<CompetitionDoc | null>();
  if (!room) return null;
  const liveCount = await getParticipantCount(String(room._id));
  if (liveCount >= maxParticipants) return null;
  return room;
}

async function createRoom(eventDoc: {
  _id: Types.ObjectId;
  name: string;
  exerciseId: string;
  exerciseMode: "reps" | "hold";
  rounds: number;
  roundDurationSeconds: number;
  breakDurationSeconds: number;
  maxParticipants: number;
}): Promise<CompetitionDoc> {
  const doc = await CompetitionModel.create({
    eventId: eventDoc._id,
    eventName: eventDoc.name,
    exerciseId: eventDoc.exerciseId,
    exerciseMode: eventDoc.exerciseMode,
    roomCode: generateRoomCode(),
    status: "WAITING",
    maxParticipants: eventDoc.maxParticipants,
    totalRounds: eventDoc.rounds,
    roundDurationSeconds: eventDoc.roundDurationSeconds,
    breakDurationSeconds: eventDoc.breakDurationSeconds,
    currentRound: 0,
    participants: [],
    rounds: [],
  });
  return doc.toObject() as unknown as CompetitionDoc;
}

export interface JoinResult {
  competitionId: string;
  participantId: string;
  participantToken: string;
  room: RoomStateSnapshot;
}

export async function joinEvent(eventId: string, displayName: string, deviceId: string): Promise<JoinResult> {
  const event = await EventModel.findById(eventId).lean().catch(() => null);
  if (!event || event.status !== "live") {
    throw AppError.notFound("This event is not currently live");
  }

  const deviceIdHash = hashToken(deviceId);

  // Enforce "no re-enrolling" server-side: if this device already holds an
  // active seat somewhere in this event (any room that hasn't finished or
  // been abandoned), reattach them to that exact seat instead of minting a
  // new participant. This is what stops one person from occupying multiple
  // of a room's 5 slots by re-opening the join page, and it doubles as a
  // recovery path if their browser storage (participantToken) was cleared.
  const existingRoom = await CompetitionModel.findOne({
    eventId,
    status: { $nin: ["COMPLETED", "ABANDONED"] },
    "participants.deviceIdHash": deviceIdHash,
  });

  if (existingRoom) {
    const participant = existingRoom.participants.find((p) => p.deviceIdHash === deviceIdHash);
    if (!participant) throw new AppError("INTERNAL", "Failed to locate existing seat", 500);

    // Rotate the credential - we only ever store a one-way hash of the
    // participant token, so we can't hand back the original. This also
    // safely invalidates whatever session this device previously had.
    const participantToken = generateParticipantToken();
    participant.tokenHash = hashToken(participantToken);
    participant.connected = true;
    await existingRoom.save();

    const competitionId = String(existingRoom._id);
    await setParticipantConnected(competitionId, participant.participantId, true);
    // Restore Redis membership too, in case its TTL had already expired.
    await joinRoomAtomic(
      competitionId,
      existingRoom.maxParticipants,
      participant.participantId,
      participant.displayName,
    );

    const snapshot = await getRoomSnapshot(competitionId);
    if (!snapshot) throw new AppError("INTERNAL", "Failed to build room snapshot after rejoin", 500);

    logger.info(
      { competitionId, participantId: participant.participantId, eventId },
      "device reattached to its existing competition seat (duplicate join blocked)",
    );

    return { competitionId, participantId: participant.participantId, participantToken, room: snapshot };
  }

  const participantId = nanoid(12);
  const participantToken = generateParticipantToken();

  for (let attempt = 0; attempt < MAX_JOIN_ATTEMPTS; attempt += 1) {
    let room = await findOpenRoom(String(event._id), event.maxParticipants);
    if (!room) {
      room = await createRoom({ ...event, _id: event._id });
    }
    const competitionId = String(room._id);

    const outcome = await joinRoomAtomic(competitionId, event.maxParticipants, participantId, displayName);
    if (outcome === "full") {
      // Someone else took the last slot between our read and our write - retry.
      continue;
    }

    await CompetitionModel.updateOne(
      { _id: competitionId },
      {
        $push: {
          participants: {
            participantId,
            displayName,
            tokenHash: hashToken(participantToken),
            deviceIdHash,
            joinedAt: new Date(),
            connected: true,
          },
        },
      },
    );

    const snapshot = await getRoomSnapshot(competitionId);
    if (!snapshot) throw new AppError("INTERNAL", "Failed to build room snapshot after join", 500);

    // If this join filled the room, kick off the countdown -> round lifecycle.
    await competitionEngine.onParticipantCountChanged(competitionId);

    logger.info({ competitionId, participantId, eventId }, "participant joined competition room");

    return { competitionId, participantId, participantToken, room: snapshot };
  }

  throw AppError.conflict("Could not secure a room slot, please try again");
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

  const snapshot = await getRoomSnapshot(competitionId);
  if (!snapshot) throw AppError.notFound("Competition not found");
  return snapshot;
}

export async function markParticipantDisconnected(competitionId: string, participantId: string): Promise<void> {
  await setParticipantConnected(competitionId, participantId, false);
}

export async function leaveCompetition(
  competitionId: string,
  participantId: string,
  participantToken: string,
): Promise<void> {
  const room = await CompetitionModel.findById(competitionId).lean<CompetitionDoc | null>();
  if (!room) return;
  const participant = room.participants.find((p) => p.participantId === participantId);
  if (!participant || !verifyToken(participantToken, participant.tokenHash)) {
    throw AppError.forbidden("Invalid participant credentials");
  }

  // Only allow leaving outright before the competition has started; once
  // it's running we keep the seat (marked disconnected) so scoring/ranking
  // for the round remains consistent, matching the reconnection design.
  if (room.status === "WAITING" || room.status === "FULL") {
    await removeParticipant(competitionId, participantId);
    await CompetitionModel.updateOne({ _id: competitionId }, { $pull: { participants: { participantId } } });
  } else {
    await setParticipantConnected(competitionId, participantId, false);
  }
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
    };
  });

  const cumulative = await getCumulativeScores(competitionId, room.currentRound || 0);
  const leaderboard = buildLeaderboard(participants, cumulative);

  const engineState = competitionEngine.getTimings(competitionId);

  return {
    competitionId,
    eventId: String(room.eventId),
    eventName: room.eventName,
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

// ---------------------------------------------------------------------------
// Admin: monitoring, moderation, reporting
// ---------------------------------------------------------------------------

export interface PageInput {
  page?: number;
  limit?: number;
}

function pagination({ page = 1, limit = 20 }: PageInput) {
  const safeLimit = Math.min(Math.max(limit, 1), 100);
  const safePage = Math.max(page, 1);
  return { skip: (safePage - 1) * safeLimit, limit: safeLimit, page: safePage };
}

export async function listCompetitionsForEvent(
  eventId: string,
  opts: PageInput & { status?: string } = {},
) {
  const { skip, limit, page } = pagination(opts);
  const filter: Record<string, unknown> = { eventId };
  if (opts.status) filter.status = opts.status;

  const [rows, total] = await Promise.all([
    CompetitionModel.find(filter)
      .select("-participants.tokenHash -participants.deviceIdHash")
      .sort({ createdAt: -1 })
      .skip(skip)
      .limit(limit)
      .lean(),
    CompetitionModel.countDocuments(filter),
  ]);

  return { rooms: rows, total, page, limit };
}

export async function listAllCompetitionsAdmin(
  opts: PageInput & { status?: string; eventId?: string } = {},
) {
  const { skip, limit, page } = pagination(opts);
  const filter: Record<string, unknown> = {};
  if (opts.status) filter.status = opts.status;
  if (opts.eventId) filter.eventId = opts.eventId;

  const [rows, total] = await Promise.all([
    CompetitionModel.find(filter)
      .select("-participants.tokenHash -participants.deviceIdHash")
      .sort({ createdAt: -1 })
      .skip(skip)
      .limit(limit)
      .lean(),
    CompetitionModel.countDocuments(filter),
  ]);

  return { rooms: rows, total, page, limit };
}

/** Full admin detail view: persisted history plus the live snapshot (timings, connection state) where relevant. */
export async function getAdminCompetitionDetail(competitionId: string) {
  const room = await CompetitionModel.findById(competitionId)
    .select("-participants.tokenHash -participants.deviceIdHash")
    .lean();
  if (!room) throw AppError.notFound("Competition not found");

  const snapshot = await getRoomSnapshot(competitionId);
  return { room, snapshot };
}

/**
 * Admin-initiated removal, distinct from a participant leaving themselves:
 * no token check (the admin is trusted by their session, not a participant
 * credential), and only permitted pre-start so it can never be used to
 * disrupt a round already in progress - use `abandonCompetition` for that.
 */
export async function removeParticipantAdmin(competitionId: string, participantId: string): Promise<void> {
  const room = await CompetitionModel.findById(competitionId).lean<CompetitionDoc | null>();
  if (!room) throw AppError.notFound("Competition not found");
  if (room.status !== "WAITING" && room.status !== "FULL") {
    throw AppError.conflict("Can only remove a participant before the competition starts");
  }
  const isMember = room.participants.some((p) => p.participantId === participantId);
  if (!isMember) throw AppError.notFound("Participant not found in this competition");

  await removeParticipant(competitionId, participantId);
  await CompetitionModel.updateOne({ _id: competitionId }, { $pull: { participants: { participantId } } });
  // Room may have been FULL and waiting on the countdown - removing a seat
  // means it no longer is, so re-evaluate (this also broadcasts room:state).
  await CompetitionModel.updateOne(
    { _id: competitionId, status: "FULL" },
    { status: "WAITING" },
  );
  await competitionEngine.onParticipantCountChanged(competitionId);
  logger.info({ competitionId, participantId }, "participant removed by admin");
}

export async function abandonCompetitionAdmin(competitionId: string, reason: string): Promise<void> {
  const ok = await competitionEngine.abandonCompetition(
    competitionId,
    reason || "Ended by admin",
  );
  if (!ok) {
    const exists = await CompetitionModel.exists({ _id: competitionId });
    if (!exists) throw AppError.notFound("Competition not found");
    throw AppError.conflict("This competition has already finished or been ended");
  }
}

export interface DashboardStats {
  events: { total: number; draft: number; live: number; closed: number };
  competitions: {
    total: number;
    active: number;
    completed: number;
    abandoned: number;
    liveParticipantsNow: number;
  };
  completedLast24h: number;
  mostPopularExercise: { exerciseId: string; exerciseName: string; count: number } | null;
}

export async function getDashboardStats(): Promise<DashboardStats> {
  const [eventCounts, competitionCounts, activeRooms, completedLast24h, popularExercise] = await Promise.all([
    EventModel.aggregate([{ $group: { _id: "$status", count: { $sum: 1 } } }]),
    CompetitionModel.aggregate([{ $group: { _id: "$status", count: { $sum: 1 } } }]),
    CompetitionModel.find({ status: { $in: ACTIVE_STATUSES_FOR_STATS } })
      .select("_id")
      .lean(),
    CompetitionModel.countDocuments({
      status: "COMPLETED",
      completedAt: { $gte: new Date(Date.now() - 24 * 60 * 60 * 1000) },
    }),
    CompetitionModel.aggregate([
      { $group: { _id: { exerciseId: "$exerciseId", exerciseName: "$exerciseName" }, count: { $sum: 1 } } },
      { $sort: { count: -1 } },
      { $limit: 1 },
    ]),
  ]);

  const eventsByStatus = Object.fromEntries(eventCounts.map((r) => [r._id, r.count as number]));
  const competitionsByStatus = Object.fromEntries(competitionCounts.map((r) => [r._id, r.count as number]));

  let liveParticipantsNow = 0;
  for (const room of activeRooms) {
    liveParticipantsNow += await getParticipantCount(String(room._id));
  }

  const totalEvents = eventCounts.reduce((sum, r) => sum + (r.count as number), 0);
  const totalCompetitions = competitionCounts.reduce((sum, r) => sum + (r.count as number), 0);
  const activeCompetitions = ACTIVE_STATUSES_FOR_STATS.reduce(
    (sum, s) => sum + (competitionsByStatus[s] ?? 0),
    0,
  );

  return {
    events: {
      total: totalEvents,
      draft: eventsByStatus.draft ?? 0,
      live: eventsByStatus.live ?? 0,
      closed: eventsByStatus.closed ?? 0,
    },
    competitions: {
      total: totalCompetitions,
      active: activeCompetitions,
      completed: competitionsByStatus.COMPLETED ?? 0,
      abandoned: competitionsByStatus.ABANDONED ?? 0,
      liveParticipantsNow,
    },
    completedLast24h,
    mostPopularExercise: popularExercise[0]
      ? {
          exerciseId: popularExercise[0]._id.exerciseId,
          exerciseName: popularExercise[0]._id.exerciseName,
          count: popularExercise[0].count,
        }
      : null,
  };
}

const ACTIVE_STATUSES_FOR_STATS = [
  "WAITING",
  "FULL",
  "COUNTDOWN",
  "ROUND_RUNNING",
  "ROUND_FINISHED",
  "BREAK",
];

/**
 * CSV of final results across every completed competition under an event -
 * one row per participant per room. Hand-rolled rather than pulling in a
 * CSV library: the shape is fixed and small, and RFC 4180 quoting for the
 * one free-text field (displayName) is a couple of lines.
 */
export async function exportEventResultsCsv(eventId: string): Promise<string> {
  const rooms = await CompetitionModel.find({ eventId, status: "COMPLETED" })
    .sort({ completedAt: 1 })
    .lean();

  const header = ["Room Code", "Completed At", "Rank", "Participant", "Total Score"];
  const lines = [header.join(",")];

  for (const room of rooms) {
    const sorted = [...room.finalResults].sort((a, b) => a.rank - b.rank);
    for (const result of sorted) {
      lines.push(
        [
          csvCell(room.roomCode),
          csvCell(room.completedAt ? room.completedAt.toISOString() : ""),
          csvCell(String(result.rank)),
          csvCell(result.displayName),
          csvCell(String(result.totalScore)),
        ].join(","),
      );
    }
  }

  return lines.join("\r\n");
}

function csvCell(value: string): string {
  if (/[",\r\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}
