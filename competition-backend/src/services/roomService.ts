import {
  CompetitionModel,
  type CompetitionDoc,
} from "../models/Competition.js";
import { EventModel } from "../models/Event.js";
import { AppError } from "../utils/errors.js";
import {
  generateParticipantToken,
  generateRoomCode,
  hashToken,
} from "../utils/token.js";
import { hashPassword, verifyPassword } from "../utils/password.js";
import { redis } from "../config/redis.js";
import {
  getParticipantCount,
  getParticipants,
  joinRoomAtomic,
} from "./redisState.js";
import { logger } from "../config/logger.js";
import type { RoomListEntry, RoomVisibility } from "../types/index.js";
import { nanoid } from "nanoid";
import { competitionEngine } from "./competitionEngine.js";
import { haversineKm, escapeRegex } from "../utils/geo.js";
import type { DiscoverRoomsQuery } from "../schemas/discoverSchemas.js";
import {
  cancelPendingRemoval,
  getRoomSnapshot,
  type JoinResult,
} from "./competitionService.js";

// Guards the "does this device already have a seat? if not, create one"
// check-then-act sequence below. Without this, two requests from the same
// device arriving close together (e.g. a double-click, or a refresh right
// after clicking) could both see "no existing seat" and both seat the
// person - one real person occupying two slots, one of which nobody is
// actually connected to.
const JOIN_LOCK_TTL_MS = 8_000;
const JOIN_LOCK_RETRY_MS = 150;
const JOIN_LOCK_MAX_WAIT_MS = 5_000;

async function acquireJoinLock(
  eventId: string,
  deviceIdHash: string,
): Promise<string> {
  const lockKey = `join:lock:${eventId}:${deviceIdHash}`;
  const deadline = Date.now() + JOIN_LOCK_MAX_WAIT_MS;
  do {
    const acquired = await redis.set(
      lockKey,
      "1",
      "PX",
      JOIN_LOCK_TTL_MS,
      "NX",
    );
    if (acquired === "OK") return lockKey;
    await new Promise((resolve) => setTimeout(resolve, JOIN_LOCK_RETRY_MS));
  } while (Date.now() < deadline);
  throw AppError.conflict(
    "Still processing your previous request, please wait a moment and try again.",
  );
}

/**
 * Scheduled events only accept new rooms/joins during their registration
 * window - see services/eventScheduler.ts, which drives `scheduling.phase`
 * forward automatically based on the stored timestamps. Events with no
 * `scheduling` block at all are unaffected (unchanged v1 behaviour). This
 * is unchanged logic, just lifted out so both createRoom and joinRoom
 * enforce it the same way.
 */
function assertEventAcceptingParticipants(event: {
  status: string;
  scheduling?: { phase: string } | null;
}): void {
  if (event.status !== "live") {
    throw AppError.notFound("This event is not currently live");
  }
  if (event.scheduling) {
    const phase = event.scheduling.phase;
    if (phase === "DRAFT" || phase === "PUBLISHED") {
      throw AppError.badRequest(
        "Registration for this event hasn't opened yet",
      );
    }
    if (phase === "REGISTRATION_CLOSED" || phase === "LIVE") {
      throw AppError.badRequest("Registration for this event has closed");
    }
    if (
      phase === "CANCELLED" ||
      phase === "POSTPONED" ||
      phase === "COMPLETED"
    ) {
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
  const participant = existingRoom.participants.find(
    (p) => p.deviceIdHash === deviceIdHash,
  );
  if (!participant)
    throw new AppError("INTERNAL", "Failed to locate existing seat", 500);

  // Rotate the credential - we only ever store a one-way hash of the
  // participant token, so we can't hand back the original.
  const participantToken = generateParticipantToken();
  participant.tokenHash = hashToken(participantToken);
  participant.connected = true;
  await existingRoom.save();

  const competitionId = String(existingRoom._id);
  cancelPendingRemoval(competitionId, participant.participantId);
  await joinRoomAtomic(
    competitionId,
    existingRoom.maxParticipants,
    participant.participantId,
    participant.displayName,
  );

  const snapshot = await getRoomSnapshot(competitionId);
  if (!snapshot)
    throw new AppError(
      "INTERNAL",
      "Failed to build room snapshot after rejoin",
      500,
    );

  logger.info(
    { competitionId, participantId: participant.participantId },
    "device reattached to its existing room seat",
  );

  return {
    competitionId,
    participantId: participant.participantId,
    participantToken,
    room: snapshot,
  };
}

async function seatNewParticipant(
  competitionId: string,
  maxParticipants: number,
  displayName: string,
  deviceIdHash: string,
  isHost: boolean,
  avatarUrl?: string,
  avatarPublicId?: string,
): Promise<JoinResult> {
  const participantId = nanoid(12);
  const participantToken = generateParticipantToken();

  const outcome = await joinRoomAtomic(
    competitionId,
    maxParticipants,
    participantId,
    displayName,
    avatarUrl,
  );
  if (outcome === "full") {
    throw AppError.conflict(
      "This room just filled up, please pick another one.",
    );
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
          avatarUrl,
          avatarPublicId,
        },
      },
    },
  );

  const snapshot = await getRoomSnapshot(competitionId);
  if (!snapshot)
    throw new AppError(
      "INTERNAL",
      "Failed to build room snapshot after join",
      500,
    );

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
export async function listRoomsForEvent(
  eventId: string,
): Promise<RoomListEntry[]> {
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
        createdAt: (
          room as unknown as { createdAt: Date }
        ).createdAt.toISOString(),
      };
      if (room.visibility === "public") {
        entry.participantNames = participants.map((p) => p.displayName);
        entry.participantAvatars = participants.map((p) => p.avatarUrl);
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
export async function revealRoom(
  competitionId: string,
  password: string | undefined,
): Promise<{
  roomName: string;
  visibility: RoomVisibility;
  participantNames: string[];
  participantAvatars: (string | null)[];
  maxParticipants: number;
}> {
  const room = await CompetitionModel.findById(
    competitionId,
  ).lean<CompetitionDoc | null>();
  if (!room || !["WAITING", "FULL"].includes(room.status)) {
    throw AppError.notFound("Room not found or no longer open");
  }
  if (room.visibility === "private") {
    if (
      !password ||
      !room.passwordHash ||
      !(await verifyPassword(password, room.passwordHash))
    ) {
      throw AppError.forbidden("Incorrect room password");
    }
  }
  const participants = await getParticipants(competitionId);
  return {
    roomName: room.roomName,
    visibility: room.visibility as RoomVisibility,
    participantNames: participants.map((p) => p.displayName),
    participantAvatars: participants.map((p) => p.avatarUrl),
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
  avatarUrl?: string;
  avatarPublicId?: string;
  // Optional - set when the host opts in to tagging this room's location,
  // so it can be found from the "near you" / "choose a region" discovery
  // in the Events page (see discoverRooms below). Either lat+lng, country,
  // or both.
  location?: {
    lat?: number;
    lng?: number;
    country?: string;
    city?: string;
  };
}

function buildLocationDoc(location: CreateRoomInput["location"]) {
  if (!location) return undefined;
  const hasCoords = location.lat !== undefined && location.lng !== undefined;
  if (!hasCoords && !location.country) return undefined;
  return {
    country: location.country,
    city: location.city,
    geo: hasCoords
      ? { type: "Point" as const, coordinates: [location.lng!, location.lat!] }
      : undefined,
  };
}

/** A participant creates a brand-new room and is immediately seated in it. */
export async function createRoom(input: CreateRoomInput): Promise<JoinResult> {
  const event = await EventModel.findById(input.eventId)
    .lean()
    .catch(() => null);
  if (!event) throw AppError.notFound("Event not found");
  assertEventAcceptingParticipants(event);

  const deviceIdHash = hashToken(input.deviceId);
  const lockKey = await acquireJoinLock(input.eventId, deviceIdHash);

  try {
    const existingSeat = await findExistingSeat(input.eventId, deviceIdHash);
    if (existingSeat) {
      return reattachToExistingSeat(existingSeat, deviceIdHash);
    }

    const passwordHash =
      input.visibility === "private" && input.password
        ? await hashPassword(input.password)
        : undefined;

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
      minParticipants: event.minParticipants,
      totalRounds: event.rounds,
      roundDurationSeconds: event.roundDurationSeconds,
      breakDurationSeconds: event.breakDurationSeconds,
      currentRound: 0,
      participants: [],
      rounds: [],
      location: buildLocationDoc(input.location),
    });
    const competitionId = String(doc._id);

    // The participant who creates the room is its host - see
    // models/Competition.ts and destroyRoomAsHostLeft in competitionService.ts.
    const result = await seatNewParticipant(
      competitionId,
      event.maxParticipants,
      input.displayName,
      deviceIdHash,
      true,
      input.avatarUrl,
      input.avatarPublicId,
    );
    logger.info(
      { competitionId, eventId: input.eventId, visibility: input.visibility },
      "room created",
    );
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
  avatarUrl?: string;
  avatarPublicId?: string;
}

/** A participant joins a specific, already-existing room they picked from the lobby. */
export async function joinRoom(input: JoinRoomInput): Promise<JoinResult> {
  const room = await CompetitionModel.findById(input.competitionId);
  if (!room) throw AppError.notFound("Room not found");

  const eventId = String(room.eventId);
  const event = await EventModel.findById(eventId)
    .lean()
    .catch(() => null);
  if (!event) throw AppError.notFound("Event not found");
  assertEventAcceptingParticipants(event);

  if (room.status !== "WAITING" && room.status !== "FULL") {
    throw AppError.conflict("This room has already started or ended");
  }
  if (room.visibility === "private") {
    if (
      !input.password ||
      !room.passwordHash ||
      !(await verifyPassword(input.password, room.passwordHash))
    ) {
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

    return await seatNewParticipant(
      input.competitionId,
      room.maxParticipants,
      input.displayName,
      deviceIdHash,
      false,
      input.avatarUrl,
      input.avatarPublicId,
    );
  } finally {
    await redis.del(lockKey);
  }
}

// A room in the "near you" discovery list - everything RoomListEntry has,
// plus the event/exercise it belongs to (so the Events page can group it
// back under its parent event card without a second round-trip) and where
// it's located relative to the search.
export interface DiscoveredRoomEntry extends RoomListEntry {
  eventId: string;
  eventName: string;
  exerciseId: string;
  exerciseMode: string;
  country?: string;
  city?: string;
  // Only present for a "Nearby" (lat/lng) search.
  distanceKm?: number;
}

const DISCOVER_RESULT_LIMIT = 60;

/**
 * Every currently-open room anywhere that was tagged with a location on
 * creation, filtered by either a radius around a point ("near you") or a
 * country/city ("choose a region") - see schemas/discoverSchemas.ts for the
 * two accepted shapes - and optionally scoped to a single event via
 * `eventId`. Powers both the "Live near you" section embedded in the
 * Events page (frontend src/components/NearbyRoomsPanel.tsx) and the
 * "Near you" filter inside a single event's rooms lobby
 * (frontend src/pages/events/RoomsLobbyPage.tsx) - results are always
 * grouped back onto their parent event, never shown as a separate flow.
 */
export async function discoverRooms(
  query: DiscoverRoomsQuery,
): Promise<DiscoveredRoomEntry[]> {
  const baseFilter: Record<string, unknown> = {
    status: { $in: ["WAITING", "FULL"] },
  };
  // Scopes results to a single event (see discoverSchemas.ts) - used by the
  // per-event rooms lobby's "Near you" filter so a location search there
  // can never surface (or leak the existence of) rooms from other events.
  if (query.eventId) {
    baseFilter.eventId = query.eventId;
  }
  let rooms: CompetitionDoc[];

  if (query.lat !== undefined && query.lng !== undefined) {
    const radiusMeters = (query.radiusKm ?? 25) * 1000;
    rooms = await CompetitionModel.find({
      ...baseFilter,
      "location.geo": {
        $near: {
          $geometry: { type: "Point", coordinates: [query.lng, query.lat] },
          $maxDistance: radiusMeters,
        },
      },
    })
      .limit(DISCOVER_RESULT_LIMIT)
      .lean<CompetitionDoc[]>();
  } else {
    const filter: Record<string, unknown> = {
      ...baseFilter,
      "location.country": new RegExp(`^${escapeRegex(query.country!)}$`, "i"),
    };
    if (query.city) {
      filter["location.city"] = new RegExp(`^${escapeRegex(query.city)}$`, "i");
    }
    rooms = await CompetitionModel.find(filter)
      .sort({ createdAt: -1 })
      .limit(DISCOVER_RESULT_LIMIT)
      .lean<CompetitionDoc[]>();
  }

  return Promise.all(
    rooms.map(async (room) => {
      const participants = await getParticipants(String(room._id));
      const coords = room.location?.geo?.coordinates;
      // GeoJSON coordinates are always exactly [lng, lat] once present -
      // safe to destructure directly. Guarded by the `coords` truthiness
      // check above; noUncheckedIndexedAccess would otherwise widen a
      // plain coords[1]/coords[0] index to `number | undefined`.
      const distanceKm =
        query.lat !== undefined && query.lng !== undefined && coords
          ? (() => {
              const [lng, lat] = coords;
              return lat !== undefined && lng !== undefined
                ? haversineKm(query.lat!, query.lng!, lat, lng)
                : undefined;
            })()
          : undefined;

      const entry: DiscoveredRoomEntry = {
        competitionId: String(room._id),
        eventId: String(room.eventId),
        eventName: room.eventName,
        exerciseId: room.exerciseId,
        exerciseMode: room.exerciseMode,
        roomName: room.roomName,
        visibility: room.visibility as RoomVisibility,
        status: room.status as DiscoveredRoomEntry["status"],
        participantCount: participants.length,
        maxParticipants: room.maxParticipants,
        // Mongoose's lean() types an unset optional string field as
        // `string | null`, but DiscoveredRoomEntry (and the frontend) only
        // expects `string | undefined` - normalize null away here so
        // callers never have to special-case it.
        country: room.location?.country ?? undefined,
        city: room.location?.city ?? undefined,
        distanceKm,
        createdAt: (
          room as unknown as { createdAt: Date }
        ).createdAt.toISOString(),
      };
      if (room.visibility === "public") {
        entry.participantNames = participants.map((p) => p.displayName);
        entry.participantAvatars = participants.map((p) => p.avatarUrl);
      }
      return entry;
    }),
  ).then((entries) =>
    // Nearest-first for radius search; country/city search is already
    // newest-first from the query above.
    query.lat !== undefined
      ? entries.sort((a, b) => (a.distanceKm ?? 0) - (b.distanceKm ?? 0))
      : entries,
  );
}
