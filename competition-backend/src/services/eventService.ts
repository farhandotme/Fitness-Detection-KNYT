import { EventModel } from "../models/Event.js";
import { CompetitionModel } from "../models/Competition.js";
import { AppError } from "../utils/errors.js";
import type { CreateEventInput } from "../schemas/eventSchemas.js";
import type { EventSchedulingPublic, SchedulingPhase } from "../types/index.js";

interface SchedulingLike {
  scheduledAt: Date;
  scheduledEndAt?: Date | null;
  registrationOpensAt: Date;
  registrationClosesAt: Date;
  timezone: string;
  minParticipants: number;
  onInsufficientParticipants: string;
  phase: string;
}

function toPublicScheduling(
  scheduling: SchedulingLike | null | undefined,
): EventSchedulingPublic | undefined {
  if (!scheduling) return undefined;
  return {
    scheduledAt: scheduling.scheduledAt.toISOString(),
    scheduledEndAt: scheduling.scheduledEndAt
      ? scheduling.scheduledEndAt.toISOString()
      : undefined,
    registrationOpensAt: scheduling.registrationOpensAt.toISOString(),
    registrationClosesAt: scheduling.registrationClosesAt.toISOString(),
    timezone: scheduling.timezone,
    minParticipants: scheduling.minParticipants,
    onInsufficientParticipants: scheduling.onInsufficientParticipants as
      | "cancel"
      | "postpone",
    phase: scheduling.phase as SchedulingPhase,
  };
}

export async function listLiveEvents() {
  const events = await EventModel.find({ status: "live" })
    .sort({ createdAt: -1 })
    .lean();
  const activeCounts = await CompetitionModel.aggregate([
    { $match: { status: { $nin: ["COMPLETED", "ABANDONED"] } } },
    { $group: { _id: "$eventId", rooms: { $sum: 1 } } },
  ]);
  const countsByEvent = new Map(
    activeCounts.map((c) => [String(c._id), c.rooms]),
  );

  return events.map((e) => ({
    id: String(e._id),
    name: e.name,
    exerciseId: e.exerciseId,
    exerciseName: e.exerciseName,
    exerciseMode: e.exerciseMode,
    rounds: e.rounds,
    roundDurationSeconds: e.roundDurationSeconds,
    breakDurationSeconds: e.breakDurationSeconds,
    maxParticipants: e.maxParticipants,
    description: e.description,
    imageUrl: e.imageUrl,
    activeRooms: countsByEvent.get(String(e._id)) ?? 0,
    scheduling: toPublicScheduling(e.scheduling),
    serverNow: Date.now(),
  }));
}

export async function getEventById(eventId: string) {
  const event = await EventModel.findById(eventId)
    .lean()
    .catch(() => null);
  if (!event || event.status === "closed")
    throw AppError.notFound("Event not found or no longer available");
  return event;
}

export async function createEvent(input: CreateEventInput) {
  const doc = await EventModel.create(input);
  return doc.toObject();
}

export async function listAllEventsAdmin() {
  return EventModel.find().sort({ createdAt: -1 }).lean();
}

/**
 * Dashboard summary for the admin home screen - cheap aggregate counts, not
 * full documents.
 */
export async function getAdminStats() {
  const [
    totalEvents,
    liveEvents,
    activeRooms,
    completedCompetitions,
    participantAgg,
  ] = await Promise.all([
    EventModel.countDocuments(),
    EventModel.countDocuments({ status: "live" }),
    CompetitionModel.countDocuments({
      status: { $nin: ["COMPLETED", "ABANDONED"] },
    }),
    CompetitionModel.countDocuments({ status: "COMPLETED" }),
    CompetitionModel.aggregate([
      { $match: { status: { $nin: ["COMPLETED", "ABANDONED"] } } },
      { $project: { count: { $size: "$participants" } } },
      { $group: { _id: null, total: { $sum: "$count" } } },
    ]),
  ]);

  return {
    totalEvents,
    liveEvents,
    activeRooms,
    completedCompetitions,
    playersOnlineNow: participantAgg[0]?.total ?? 0,
  };
}

/**
 * Every competition room that's currently in progress (not finished or
 * abandoned), across every event, for the admin "live now" board. Kept
 * intentionally light - just enough to render a tile and link into the full
 * spectator view (getRoomSnapshot) for any one of them.
 */
export async function listLiveCompetitionsAdmin() {
  const rooms = await CompetitionModel.find({
    status: { $nin: ["COMPLETED", "ABANDONED"] },
  })
    .sort({ createdAt: -1 })
    .lean();

  return rooms.map((r) => ({
    competitionId: String(r._id),
    eventId: String(r.eventId),
    eventName: r.eventName,
    exerciseId: r.exerciseId,
    status: r.status,
    currentRound: r.currentRound,
    totalRounds: r.totalRounds,
    participantCount: r.participants.length,
    maxParticipants: r.maxParticipants,
    participantNames: r.participants.map((p) => p.displayName),
    hostName: r.participants.find((p) => p.isHost)?.displayName ?? null,
    createdAt: r.createdAt,
  }));
}

/**
 * Every room ever spawned under one event, oldest-first status untouched -
 * for the admin's per-event "rooms" view (see routes/adminRoutes.ts GET
 * /events/:id/rooms). Unlike listLiveCompetitionsAdmin this is scoped to a
 * single event and includes finished/abandoned rooms too, since the admin
 * wants the full history of who created what, not just what's live right
 * now.
 */
export async function listRoomsForEventAdmin(eventId: string) {
  const event = await EventModel.findById(eventId).lean();
  if (!event) throw AppError.notFound("Event not found");

  const rooms = await CompetitionModel.find({ eventId }).sort({ createdAt: -1 }).lean();

  const RUNNING_STATUSES = new Set(["COUNTDOWN", "ROUND_RUNNING", "ROUND_FINISHED", "BREAK"]);
  const OPEN_STATUSES = new Set(["WAITING", "FULL"]);

  return {
    event: {
      id: String(event._id),
      name: event.name,
      exerciseName: event.exerciseName,
      status: event.status,
      maxParticipants: event.maxParticipants,
    },
    rooms: rooms.map((r) => {
      const host = r.participants.find((p) => p.isHost);
      let phase: "running" | "waiting" | "ended";
      if (r.status === "COMPLETED" || r.status === "ABANDONED") phase = "ended";
      else if (RUNNING_STATUSES.has(r.status)) phase = "running";
      else phase = "waiting";

      return {
        competitionId: String(r._id),
        roomName: r.roomName,
        visibility: r.visibility,
        status: r.status,
        phase,
        currentRound: r.currentRound,
        totalRounds: r.totalRounds,
        participantCount: r.participants.length,
        maxParticipants: r.maxParticipants,
        participantNames: r.participants.map((p) => p.displayName),
        hostName: host?.displayName ?? null,
        createdAt: r.createdAt,
        completedAt: r.completedAt ?? null,
      };
    }),
  };
}

export async function updateEventStatus(
  eventId: string,
  status: "draft" | "live" | "closed",
) {
  const event = await EventModel.findByIdAndUpdate(
    eventId,
    { status },
    { new: true },
  );
  if (!event) throw AppError.notFound("Event not found");
  return event.toObject();
}

/**
 * Manual admin override for a scheduled event's lifecycle phase - e.g.
 * cancelling a scheduled event ahead of time. The scheduler worker
 * (services/eventScheduler.ts) drives `phase` forward automatically the
 * rest of the time; this exists for the human-in-the-loop exception case.
 */
export async function setEventSchedulingPhase(
  eventId: string,
  phase: "CANCELLED" | "POSTPONED",
) {
  const event = await EventModel.findById(eventId);
  if (!event) throw AppError.notFound("Event not found");
  if (!event.scheduling)
    throw AppError.badRequest("This event does not have a schedule");
  if (
    ["COMPLETED", "CANCELLED", "POSTPONED"].includes(
      event.scheduling.phase ?? "",
    )
  ) {
    throw AppError.conflict(`Event is already ${event.scheduling.phase}`);
  }
  event.scheduling.phase = phase;
  await event.save();
  return event.toObject();
}

/**
 * Edit an event's own fields (name, exercise, rounds, scheduling, ...).
 * Deliberately does NOT touch any competition rooms already spawned from
 * it - those keep running/showing under whatever settings were in effect
 * when each room was created, same as changing a live event's status
 * today never retroactively changes an in-progress room.
 */
export async function updateEvent(
  eventId: string,
  input: Partial<CreateEventInput>,
) {
  const event = await EventModel.findByIdAndUpdate(eventId, input, {
    new: true,
    runValidators: true,
  });
  if (!event) throw AppError.notFound("Event not found");
  return event.toObject();
}

/**
 * Permanently removes an event. Refuses only while one of its competition
 * rooms actually still has someone in it - an empty WAITING room (created
 * the moment the first join attempt landed, then abandoned before it ever
 * filled) isn't a competition "in progress" and shouldn't be able to block
 * deletion forever; finished rooms are untouched and keep their own copy
 * of the event's name/settings for history (see models/Competition.ts), so
 * past results still render correctly after the event itself is gone.
 */
export async function deleteEvent(eventId: string) {
  const nonTerminalRooms = await CompetitionModel.find(
    { eventId, status: { $nin: ["COMPLETED", "ABANDONED"] } },
    { participants: 1 },
  ).lean();

  const occupiedRooms = nonTerminalRooms.filter((r) => r.participants.length > 0);
  if (occupiedRooms.length > 0) {
    throw AppError.conflict(
      "This event has a competition in progress. Close it or wait for it to finish before deleting.",
    );
  }

  // Any empty non-terminal rooms just cleared to delete alongside the event -
  // otherwise they'd linger as orphans pointing at a now-deleted eventId.
  if (nonTerminalRooms.length > 0) {
    await CompetitionModel.deleteMany({
      _id: { $in: nonTerminalRooms.map((r) => r._id) },
    });
  }

  const event = await EventModel.findByIdAndDelete(eventId);
  if (!event) throw AppError.notFound("Event not found");
  return event.toObject();
}
