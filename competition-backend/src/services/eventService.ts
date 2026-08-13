import { Types } from "mongoose";
import { EventModel } from "../models/Event.js";
import { CompetitionModel } from "../models/Competition.js";
import { AppError } from "../utils/errors.js";
import type { CreateEventInput } from "../schemas/eventSchemas.js";

const ACTIVE_STATUSES = ["WAITING", "FULL", "COUNTDOWN", "ROUND_RUNNING", "ROUND_FINISHED", "BREAK"];

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
    activeRooms: countsByEvent.get(String(e._id)) ?? 0,
  }));
}

export async function getEventById(eventId: string) {
  const event = await EventModel.findById(eventId).lean().catch(() => null);
  if (!event || event.status === "closed") throw AppError.notFound("Event not found or no longer available");
  return event;
}

/** Admin variant: returns draft/closed events too (the public one deliberately hides them). */
export async function getEventByIdAdmin(eventId: string) {
  const event = await EventModel.findById(eventId).lean().catch(() => null);
  if (!event) throw AppError.notFound("Event not found");
  return event;
}

export async function createEvent(input: CreateEventInput) {
  const doc = await EventModel.create(input);
  return doc.toObject();
}

/**
 * Per-event competition counts, broken out by lifecycle bucket, plus the
 * all-time participant count across every room the event has ever spawned.
 * Backs both the admin events list (compact counts) and the event detail
 * page (full breakdown).
 */
export async function getEventStatsMap(
  eventIds?: string[],
): Promise<Map<string, { active: number; completed: number; abandoned: number; totalParticipants: number }>> {
  const match = eventIds ? { eventId: { $in: eventIds.map((id) => new Types.ObjectId(id)) } } : {};
  const rows = await CompetitionModel.aggregate([
    { $match: match },
    {
      $group: {
        _id: "$eventId",
        active: { $sum: { $cond: [{ $in: ["$status", ACTIVE_STATUSES] }, 1, 0] } },
        completed: { $sum: { $cond: [{ $eq: ["$status", "COMPLETED"] }, 1, 0] } },
        abandoned: { $sum: { $cond: [{ $eq: ["$status", "ABANDONED"] }, 1, 0] } },
        totalParticipants: { $sum: { $size: "$participants" } },
      },
    },
  ]);
  return new Map(
    rows.map((r) => [
      String(r._id),
      {
        active: r.active as number,
        completed: r.completed as number,
        abandoned: r.abandoned as number,
        totalParticipants: r.totalParticipants as number,
      },
    ]),
  );
}

export async function listAllEventsAdmin() {
  const events = await EventModel.find().sort({ createdAt: -1 }).lean();
  const statsMap = await getEventStatsMap(events.map((e) => String(e._id)));
  return events.map((e) => ({
    ...e,
    stats: statsMap.get(String(e._id)) ?? { active: 0, completed: 0, abandoned: 0, totalParticipants: 0 },
  }));
}

export async function updateEventStatus(eventId: string, status: "draft" | "live" | "closed") {
  const event = await EventModel.findByIdAndUpdate(eventId, { status }, { new: true });
  if (!event) throw AppError.notFound("Event not found");
  return event.toObject();
}

export async function updateEvent(eventId: string, input: Partial<CreateEventInput>) {
  const event = await EventModel.findByIdAndUpdate(eventId, input, { new: true });
  if (!event) throw AppError.notFound("Event not found");
  return event.toObject();
}

/**
 * Deletion is deliberately narrow: only a `draft` event that has never
 * spawned a single competition room can be deleted outright. Anything that
 * ever went live (or has history of any kind) is closed instead, via
 * updateEventStatus - deleting it would silently orphan real competition
 * history that a `Competition.eventId` still points at.
 */
export async function deleteDraftEvent(eventId: string): Promise<void> {
  const event = await EventModel.findById(eventId);
  if (!event) throw AppError.notFound("Event not found");
  if (event.status !== "draft") {
    throw AppError.conflict("Only draft events can be deleted - close this event instead of deleting it");
  }
  const hasHistory = await CompetitionModel.exists({ eventId });
  if (hasHistory) {
    throw AppError.conflict("This event already has competition rooms and can't be deleted - close it instead");
  }
  await EventModel.deleteOne({ _id: eventId });
}
