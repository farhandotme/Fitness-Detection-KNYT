import { Router } from "express";
import type { Request, Response, NextFunction } from "express";
import { asyncHandler, requireParam } from "../utils/asyncHandler.js";
import { AppError } from "../utils/errors.js";
import {
  createEventSchema,
  updateEventSchema,
} from "../schemas/eventSchemas.js";
import {
  createEvent,
  getAdminStats,
  listAllEventsAdmin,
  listLiveCompetitionsAdmin,
  updateEventStatus,
} from "../services/eventService.js";
import { getRoomSnapshot } from "../services/competitionService.js";
import { EventModel } from "../models/Event.js";
import { verifyAdminToken, type AdminTokenPayload } from "../utils/jwt.js";

export const adminRoutes = Router();

export interface AdminRequest extends Request {
  admin?: AdminTokenPayload;
}

adminRoutes.use((req: AdminRequest, _res: Response, next: NextFunction) => {
  const header = req.header("authorization");
  const token = header?.startsWith("Bearer ") ? header.slice(7) : null;
  if (!token) throw AppError.unauthorized("Missing admin session token");

  try {
    req.admin = verifyAdminToken(token);
  } catch {
    throw AppError.unauthorized(
      "Invalid or expired admin session, please log in again",
    );
  }
  next();
});

adminRoutes.get(
  "/me",
  asyncHandler(async (req: AdminRequest, res) => {
    res.json({ username: req.admin?.username });
  }),
);

adminRoutes.get(
  "/events",
  asyncHandler(async (_req, res) => {
    const events = await listAllEventsAdmin();
    res.json({ events });
  }),
);

adminRoutes.post(
  "/events",
  asyncHandler(async (req, res) => {
    const input = createEventSchema.parse(req.body);
    const event = await createEvent(input);
    res.status(201).json({ event });
  }),
);

adminRoutes.patch(
  "/events/:id",
  asyncHandler(async (req, res) => {
    const input = updateEventSchema.parse(req.body);
    const event = await EventModel.findByIdAndUpdate(
      requireParam(req, "id"),
      input,
      { new: true },
    );
    if (!event) throw AppError.notFound("Event not found");
    res.json({ event: event.toObject() });
  }),
);

adminRoutes.post(
  "/events/:id/status",
  asyncHandler(async (req, res) => {
    const { status } = req.body as { status: "draft" | "live" | "closed" };
    const event = await updateEventStatus(requireParam(req, "id"), status);
    res.json({ event });
  }),
);

// --- Live monitoring: what the admin dashboard's "live now" board reads ---

adminRoutes.get(
  "/stats",
  asyncHandler(async (_req, res) => {
    const stats = await getAdminStats();
    res.json({ stats });
  }),
);

adminRoutes.get(
  "/competitions/live",
  asyncHandler(async (_req, res) => {
    const rooms = await listLiveCompetitionsAdmin();
    res.json({ rooms });
  }),
);

adminRoutes.get(
  "/competitions/:id",
  asyncHandler(async (req, res) => {
    const snapshot = await getRoomSnapshot(requireParam(req, "id"));
    if (!snapshot) throw AppError.notFound("Competition room not found");
    res.json({ room: snapshot });
  }),
);
