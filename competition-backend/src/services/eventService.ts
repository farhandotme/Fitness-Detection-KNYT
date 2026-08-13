import { EventModel } from "../models/Event.js";
import { CompetitionModel } from "../models/Competition.js";
import { AppError } from "../utils/errors.js";
import type { CreateEventInput } from "../schemas/eventSchemas.js";

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
    createdAt: r.createdAt,
  }));
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
