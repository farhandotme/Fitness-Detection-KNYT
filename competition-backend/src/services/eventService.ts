import { EventModel } from "../models/Event.js";
import { CompetitionModel } from "../models/Competition.js";
import { AppError } from "../utils/errors.js";
import { zonedTimeToUtc } from "../utils/timezone.js";
import type { CreateEventInput, UpdateEventInput } from "../schemas/eventSchemas.js";

/**
 * Converts the admin's local-wall-clock schedule fields to UTC Date fields
 * ready for storage, and drops the *Local strings. Shared by create and
 * update so both paths store the schedule the same way. No-op for instant
 * events / when no schedule fields are present in a partial update.
 */
function resolveScheduleFields<T extends Partial<CreateEventInput>>(
  input: T,
): Omit<T, "scheduledAtLocal" | "registrationOpensAtLocal" | "registrationClosesAtLocal"> & {
  scheduledAt?: Date;
  registrationOpensAt?: Date;
  registrationClosesAt?: Date;
} {
  const { scheduledAtLocal, registrationOpensAtLocal, registrationClosesAtLocal, ...rest } = input;
  const timezone = input.timezone ?? "Asia/Kolkata";
  const out: ReturnType<typeof resolveScheduleFields<T>> = { ...rest };

  if (scheduledAtLocal) out.scheduledAt = zonedTimeToUtc(scheduledAtLocal, timezone);
  if (registrationOpensAtLocal) out.registrationOpensAt = zonedTimeToUtc(registrationOpensAtLocal, timezone);
  if (registrationClosesAtLocal) out.registrationClosesAt = zonedTimeToUtc(registrationClosesAtLocal, timezone);

  return out;
}

export async function listLiveEvents() {
  const events = await EventModel.find({ status: "live" }).sort({ createdAt: -1 }).lean();
  const activeCounts = await CompetitionModel.aggregate([
    { $match: { status: { $nin: ["COMPLETED", "ABANDONED"] } } },
    { $group: { _id: "$eventId", rooms: { $sum: 1 } } },
  ]);
  const countsByEvent = new Map(activeCounts.map((c) => [String(c._id), c.rooms]));

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
    eventType: e.eventType,
    timezone: e.timezone,
    scheduledAt: e.scheduledAt,
    registrationOpensAt: e.registrationOpensAt,
    registrationClosesAt: e.registrationClosesAt,
    minParticipants: e.minParticipants,
    scheduleStatus: e.scheduleStatus,
    // Convenience flag so the join screen doesn't need to reimplement the
    // eventType/scheduleStatus gate that joinEvent() enforces server-side.
    registrationOpen: e.eventType !== "scheduled" || e.scheduleStatus === "REGISTRATION_OPEN",
  }));
}

export async function getEventById(eventId: string) {
  const event = await EventModel.findById(eventId).lean().catch(() => null);
  if (!event || event.status === "closed") throw AppError.notFound("Event not found or no longer available");
  return event;
}

export async function createEvent(input: CreateEventInput) {
  const resolved = resolveScheduleFields(input);
  // Scheduled events are published immediately on creation - the admin only
  // configures the schedule once, and the scheduler worker (eventScheduler.ts)
  // takes it from here (opens/closes registration, starts the competition).
  if (input.eventType === "scheduled") {
    Object.assign(resolved, { scheduleStatus: "PUBLISHED", status: "live" });
  }
  const doc = await EventModel.create(resolved);
  return doc.toObject();
}

export async function updateEvent(eventId: string, input: UpdateEventInput) {
  const resolved = resolveScheduleFields(input);
  const event = await EventModel.findByIdAndUpdate(eventId, resolved, { new: true });
  if (!event) throw AppError.notFound("Event not found");
  return event.toObject();
}

export async function listAllEventsAdmin() {
  return EventModel.find().sort({ createdAt: -1 }).lean();
}

/**
 * Dashboard summary for the admin home screen - cheap aggregate counts, not
 * full documents.
 */
export async function getAdminStats() {
  const [totalEvents, liveEvents, activeRooms, completedCompetitions, participantAgg] = await Promise.all([
    EventModel.countDocuments(),
    EventModel.countDocuments({ status: "live" }),
    CompetitionModel.countDocuments({ status: { $nin: ["COMPLETED", "ABANDONED"] } }),
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
  const rooms = await CompetitionModel.find({ status: { $nin: ["COMPLETED", "ABANDONED"] } })
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
    createdAt: r.createdAt,
  }));
}

export async function updateEventStatus(eventId: string, status: "draft" | "live" | "closed") {
  const event = await EventModel.findByIdAndUpdate(eventId, { status }, { new: true });
  if (!event) throw AppError.notFound("Event not found");
  return event.toObject();
}
