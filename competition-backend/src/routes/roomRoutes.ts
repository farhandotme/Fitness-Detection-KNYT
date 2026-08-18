import { Router } from "express";
import { asyncHandler, requireParam } from "../utils/asyncHandler.js";
import { listRoomsForEvent, revealRoom } from "../services/roomService.js";

export const roomRoutes = Router({ mergeParams: true });

// GET /api/events/:eventId/rooms - the lobby list: every open room under
// this event, with a headcount for everyone and participant names for
// public rooms only.
roomRoutes.get(
  "/",
  asyncHandler(async (req, res) => {
    const rooms = await listRoomsForEvent(requireParam(req, "eventId"));
    res.json({ rooms });
  }),
);

// POST /api/events/:eventId/rooms/:competitionId/reveal - preview a room's
// occupants before joining. No body needed for a public room; private
// rooms require { "password": "..." } and return 403 if it's wrong.
roomRoutes.post(
  "/:competitionId/reveal",
  asyncHandler(async (req, res) => {
    const competitionId = requireParam(req, "competitionId");
    const password = typeof req.body?.password === "string" ? req.body.password : undefined;
    const room = await revealRoom(competitionId, password);
    res.json({ room });
  }),
);
