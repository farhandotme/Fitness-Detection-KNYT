import { Router } from "express";
import { asyncHandler, requireParam } from "../utils/asyncHandler.js";
import { getEventById, listLiveEvents } from "../services/eventService.js";

export const eventRoutes = Router();

// GET /api/events - every currently live event a visitor can join
eventRoutes.get(
  "/",
  asyncHandler(async (_req, res) => {
    const events = await listLiveEvents();
    res.json({ events });
  }),
);

// GET /api/events/:id - details for the join screen
eventRoutes.get(
  "/:id",
  asyncHandler(async (req, res) => {
    const event = await getEventById(requireParam(req, "id"));
    res.json({
      event: {
        id: String(event._id),
        name: event.name,
        exerciseId: event.exerciseId,
        exerciseName: event.exerciseName,
        exerciseMode: event.exerciseMode,
        rounds: event.rounds,
        roundDurationSeconds: event.roundDurationSeconds,
        breakDurationSeconds: event.breakDurationSeconds,
        maxParticipants: event.maxParticipants,
        minParticipants: event.minParticipants,
        description: event.description,
        imageUrls: event.imageUrls ?? [],
        scheduling: event.scheduling
          ? {
              scheduledAt: event.scheduling.scheduledAt.toISOString(),
              scheduledEndAt: event.scheduling.scheduledEndAt
                ? event.scheduling.scheduledEndAt.toISOString()
                : undefined,
              registrationOpensAt:
                event.scheduling.registrationOpensAt.toISOString(),
              registrationClosesAt:
                event.scheduling.registrationClosesAt.toISOString(),
              timezone: event.scheduling.timezone,
              minParticipants: event.scheduling.minParticipants,
              onInsufficientParticipants:
                event.scheduling.onInsufficientParticipants,
              phase: event.scheduling.phase,
            }
          : undefined,
        serverNow: Date.now(),
      },
    });
  }),
);
