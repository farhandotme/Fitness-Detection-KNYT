import { CompetitionModel, type CompetitionDoc } from "../models/Competition.js";
import { EventModel } from "../models/Event.js";
import { AppError } from "../utils/errors.js";
import { generateParticipantToken, generateRoomCode, hashToken } from "../utils/token.js";
import { hashPassword, verifyPassword } from "../utils/password.js";
import { redis } from "../config/redis.js";
import { getParticipantCount, getParticipants, joinRoomAtomic } from "./redisState.js";
import { logger } from "../config/logger.js";
import type { RoomListEntry, RoomVisibility } from "../types/index.js";
import { nanoid } from "nanoid";
import { competitionEngine } from "./competitionEngine.js";
import { cancelPendingRemoval, getRoomSnapshot, type JoinResult } from "./competitionService.js";

// Guards the "does this device already have a seat? if not, create one"
// check-then-act sequence below. Without this, two requests from the same
// device arriving close together (e.g. a double-click, or a refresh right
// after clicking) could both see "no existing seat" and both seat the
// person - one real person occupying two slots, one of which nobody is
// actually connected to.
const JOIN_LOCK_TTL_MS = 8_000;
const JOIN_LOCK_RETRY_MS = 150;
const JOIN_LOCK_MAX_WAIT_MS = 5_000;

async function acquireJoinLock(eventId: string, deviceIdHash: string): Promise<string> {
  const lockKey = `join:lock:${eventId}:${deviceIdHash}`;
  const deadline = Date.now() + JOIN_LOCK_MAX_WAIT_MS;
  do {
    const acquired = await redis.set(lockKey, "1", "PX", JOIN_LOCK_TTL_MS, "NX");
    if (acquired === "OK") return lockKey;
    await new Promise((resolve) => setTimeout(resolve, JOIN_LOCK_RETRY_MS));
  } while (Date.now() < deadline);
  throw AppError.conflict("Still processing your previous request, please wait a moment and try again.");
}

/**
 * Scheduled events only accept new rooms/joins during their registration
 * window - see services/eventScheduler.ts, which drives `scheduling.phase`
 * forward automatically based on the stored timestamps. Events with no
 * `scheduling` block at all are unaffected (unchanged v1 behaviour). This
 * is unchanged logic, just lifted out so both createRoom and joinRoom
 * enforce it the same way.
 */
function assertEventAcceptingParticipants(event: { status: string; scheduling?: { phase: string } | null }): void {
  if (event.status !== "live") {
    throw AppError.notFound("This event is not currently live");
  }
  if (event.scheduling) {
    const phase = event.scheduling.phase;
    if (phase === "DRAFT" || phase === "PUBLISHED") {
      throw AppError.badRequest("Registration for this event hasn't opened yet");
    }
    if (phase === "REGISTRATION_CLOSED" || phase === "LIVE") {
      throw AppError.badRequest("Registration for this event has closed");
    }
    if (phase === "CANCELLED" || phase === "POSTPONED" || phase === "COMPLETED") {
      throw AppError.notFound("This event is no longer accepting participants");
    }
    // phase === "REGISTRATION_OPEN" falls through.
  }
}

/**
 * If this device already holds an active seat somewhere in this event (any
 * room that hasn't finished or been abandoned), reattach them to that exact
 * seat instead of letting them create/join a second one. Doubles as a
 * recovery path if their browser storage (participantToken) was cleared.
 */
async function findExistingSeat(eventId: string, deviceIdHash: string) {
  return CompetitionModel.findOne({
    eventId,
    status: { $nin: ["COMPLETED", "ABANDONED"] },
    "participants.deviceIdHash": deviceIdHash,
  });
}

async function reattachToExistingSeat(
  existingRoom: InstanceType<typeof CompetitionModel>,
  deviceIdHash: string,
): Promise<JoinResult> {
  const participant = existingRoom.participants.find((p) => p.deviceIdHash === deviceIdHash);
  if (!participant) throw new AppError("INTERNAL", "Failed to locate existing seat", 500);

  // Rotate the credential - we only ever store a one-way hash of the
  // participant token, so we can't hand back the original.
  const participantToken = generateParticipantToken();
  participant.tokenHash = hashToken(participantToken);
  participant.connected = true;
  await existingRoom.save();

  const competitionId = String(existingRoom._id);
  cancelPendingRemoval(competitionId, participant.participantId);
  await joinRoomAtomic(competitionId, existingRoom.maxParticipants, participant.participantId, participant.displayName);

  const snapshot = await getRoomSnapshot(competitionId);
  if (!snapshot) throw new AppError("INTERNAL", "Failed to build room snapshot after rejoin", 500);

  logger.info(
    { competitionId, participantId: participant.participantId },
    "device reattached to its existing room seat",
  );

  return { competitionId, participantId: participant.participantId, participantToken, room: snapshot };
}

async function seatNewParticipant(
  competitionId: string,
  maxParticipants: number,
  displayName: string,
  deviceIdHash: string,
  isHost: boolean,
): Promise<JoinResult> {
  const participantId = nanoid(12);
  const participantToken = generateParticipantToken();

  const outcome = await joinRoomAtomic(competitionId, maxParticipants, participantId, displayName);
  if (outcome === "full") {
    throw AppError.conflict("This room just filled up, please pick another one.");
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
          isHost,
        },
      },
    },
  );

  const snapshot = await getRoomSnapshot(competitionId);
  if (!snapshot) throw new AppError("INTERNAL", "Failed to build room snapshot after join", 500);

  // If this join filled the room, kick off the countdown -> round lifecycle.
  await competitionEngine.onParticipantCountChanged(competitionId);

  return { competitionId, participantId, participantToken, room: snapshot };
}

/**
 * Every currently-open (not yet started) room under an event, for the
 * "browse rooms" lobby a participant sees before entering a display name.
 * Public rooms include who's already inside; private rooms only ever show
 * a headcount here - their participant list is revealed by `revealRoom`
 * once the correct password is supplied.
 */
export async function listRoomsForEvent(eventId: string): Promise<RoomListEntry[]> {
  const rooms = await CompetitionModel.find({
    eventId,
    status: { $in: ["WAITING", "FULL"] },
  })
    .sort({ createdAt: -1 })
    .lean<CompetitionDoc[]>();

  return Promise.all(
    rooms.map(async (room) => {
      const participants = await getParticipants(String(room._id));
      const entry: RoomListEntry = {
        competitionId: String(room._id),
        roomName: room.roomName,
        visibility: room.visibility as RoomVisibility,
        status: room.status as RoomListEntry["status"],
        participantCount: participants.length,
        maxParticipants: room.maxParticipants,
        createdAt: (room as unknown as { createdAt: Date }).createdAt.toISOString(),
      };
      if (room.visibility === "public") {
        entry.participantNames = participants.map((p) => p.displayName);
      }
      return entry;
    }),
  );
}

/**
 * Participant-facing preview of a room's occupants before joining. Public
 * rooms don't need a password. Private rooms do - this is also how the
 * frontend checks a password is correct before showing the "enter your
 * name" step.
 */
export async function revealRoom(competitionId: string, password: string | undefined): Promise<{ roomName: string; visibility: RoomVisibility; participantNames: string[]; maxParticipants: number }> {
  const room = await CompetitionModel.findById(competitionId).lean<CompetitionDoc | null>();
  if (!room || !["WAITING", "FULL"].includes(room.status)) {
    throw AppError.notFound("Room not found or no longer open");
  }
  if (room.visibility === "private") {
    if (!password || !room.passwordHash || !(await verifyPassword(password, room.passwordHash))) {
      throw AppError.forbidden("Incorrect room password");
    }
  }
  const participants = await getParticipants(competitionId);
  return {
    roomName: room.roomName,
    visibility: room.visibility as RoomVisibility,
    participantNames: participants.map((p) => p.displayName),
    maxParticipants: room.maxParticipants,
  };
}

export interface CreateRoomInput {
  eventId: string;
  roomName: string;
  visibility: RoomVisibility;
  password?: string;
  displayName: string;
  deviceId: string;
}

/** A participant creates a brand-new room and is immediately seated in it. */
export async function createRoom(input: CreateRoomInput): Promise<JoinResult> {
  const event = await EventModel.findById(input.eventId).lean().catch(() => null);
  if (!event) throw AppError.notFound("Event not found");
  assertEventAcceptingParticipants(event);

  const deviceIdHash = hashToken(input.deviceId);
  const lockKey = await acquireJoinLock(input.eventId, deviceIdHash);

  try {
    const existingSeat = await findExistingSeat(input.eventId, deviceIdHash);
    if (existingSeat) {
      return reattachToExistingSeat(existingSeat, deviceIdHash);
    }

    const passwordHash = input.visibility === "private" && input.password ? await hashPassword(input.password) : undefined;

    const doc = await CompetitionModel.create({
      eventId: event._id,
      eventName: event.name,
      roomName: input.roomName,
      visibility: input.visibility,
      passwordHash,
      exerciseId: event.exerciseId,
      exerciseMode: event.exerciseMode,
      roomCode: generateRoomCode(),
      status: "WAITING",
      maxParticipants: event.maxParticipants,
      totalRounds: event.rounds,
      roundDurationSeconds: event.roundDurationSeconds,
      breakDurationSeconds: event.breakDurationSeconds,
      currentRound: 0,
      participants: [],
      rounds: [],
    });
    const competitionId = String(doc._id);

    // The participant who creates the room is its host - see
    // models/Competition.ts and destroyRoomAsHostLeft in competitionService.ts.
    const result = await seatNewParticipant(competitionId, event.maxParticipants, input.displayName, deviceIdHash, true);
    logger.info({ competitionId, eventId: input.eventId, visibility: input.visibility }, "room created");
    return result;
  } finally {
    await redis.del(lockKey);
  }
}

export interface JoinRoomInput {
  competitionId: string;
  displayName: string;
  password?: string;
  deviceId: string;
}

/** A participant joins a specific, already-existing room they picked from the lobby. */
export async function joinRoom(input: JoinRoomInput): Promise<JoinResult> {
  const room = await CompetitionModel.findById(input.competitionId);
  if (!room) throw AppError.notFound("Room not found");

  const eventId = String(room.eventId);
  const event = await EventModel.findById(eventId).lean().catch(() => null);
  if (!event) throw AppError.notFound("Event not found");
  assertEventAcceptingParticipants(event);

  if (room.status !== "WAITING" && room.status !== "FULL") {
    throw AppError.conflict("This room has already started or ended");
  }
  if (room.visibility === "private") {
    if (!input.password || !room.passwordHash || !(await verifyPassword(input.password, room.passwordHash))) {
      throw AppError.forbidden("Incorrect room password");
    }
  }

  const deviceIdHash = hashToken(input.deviceId);
  const lockKey = await acquireJoinLock(eventId, deviceIdHash);

  try {
    const existingSeat = await findExistingSeat(eventId, deviceIdHash);
    if (existingSeat) {
      return reattachToExistingSeat(existingSeat, deviceIdHash);
    }

    const liveCount = await getParticipantCount(input.competitionId);
    if (liveCount >= room.maxParticipants) {
      throw AppError.conflict("This room is already full");
    }

    return await seatNewParticipant(input.competitionId, room.maxParticipants, input.displayName, deviceIdHash, false);
  } finally {
    await redis.del(lockKey);
  }
}
