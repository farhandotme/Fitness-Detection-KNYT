import { Router } from "express";
import { asyncHandler } from "../utils/asyncHandler.js";
import { discoverRooms } from "../services/roomService.js";
import { discoverRoomsQuerySchema } from "../schemas/discoverSchemas.js";

export const discoverRoutes = Router();

// GET /api/discover/rooms - open rooms anywhere, filtered by either a
// lat/lng + radius ("near you") or a country (+ optional city) ("choose a
// region"). Distinct from the per-event /api/events/:eventId/rooms lobby,
// but surfaced inline inside the Events page's "Live near you" section
// rather than as a separate screen - see
// frontend src/components/NearbyRoomsPanel.tsx.
discoverRoutes.get(
  "/rooms",
  asyncHandler(async (req, res) => {
    const query = discoverRoomsQuerySchema.parse(req.query);
    const rooms = await discoverRooms(query);
    res.json({ rooms });
  }),
);
