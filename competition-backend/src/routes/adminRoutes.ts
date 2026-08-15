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
  deleteEvent,
  getAdminStats,
  listAllEventsAdmin,
  listLiveCompetitionsAdmin,
  listRoomsForEventAdmin,
  setEventSchedulingPhase,
  updateEvent,
  updateEventStatus,
} from "../services/eventService.js";
import { getRoomSnapshot } from "../services/competitionService.js";
import { verifyAdminToken, type AdminTokenPayload } from "../utils/jwt.js";
import {
  createEventImageUploadSignature,
  deleteEventImage,
} from "../services/eventImageService.js";
import { z } from "zod";

export const adminRoutes = Router();

export interface AdminRequest extends Request {
  admin?: AdminTokenPayload;
}

// Every route below requires a valid admin session (see routes/authRoutes.ts
// for register/login, which is what issues this token). This replaces the
// earlier single shared-secret approach now that real admin accounts exist.
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
    const event = await updateEvent(requireParam(req, "id"), input);
    res.json({ event });
  }),
);

// POST /api/admin/events/image-signature - authorizes exactly one
// direct-to-Cloudinary upload for an event cover/advertising image. The
// admin dashboard then POSTs the file straight to Cloudinary with this
// payload (see frontend src/lib/eventImageStore.ts) - the image itself
// never passes through this server. Called once per image the admin adds
// (up to 3 - see services/eventImageService.ts MAX_EVENT_IMAGES). Returns
// 503 with EVENT_IMAGE_UPLOADS_DISABLED if Cloudinary isn't configured for
// this deployment.
adminRoutes.post(
  "/events/image-signature",
  asyncHandler(async (_req, res) => {
    const signature = createEventImageUploadSignature();
    res.json(signature);
  }),
);

const eventImagePublicIdSchema = z
  .string()
  .trim()
  .min(1)
  .max(300)
  .regex(/^[A-Za-z0-9_\-/]+$/, "Invalid image id");

// POST /api/admin/events/image-delete - removes a previously uploaded cover
// image from Cloudinary. Takes { publicId } rather than a URL segment since
// Cloudinary publicIds contain slashes (folder/id). Called from the admin
// dashboard when an admin removes an image from the form, whether or not
// the event itself has been saved yet.
adminRoutes.post(
  "/events/image-delete",
  asyncHandler(async (req, res) => {
    const parsed = eventImagePublicIdSchema.safeParse(req.body?.publicId);
    if (!parsed.success) throw AppError.badRequest("Invalid image id");
    await deleteEventImage(parsed.data);
    res.status(204).end();
  }),
);

adminRoutes.delete(
  "/events/:id",
  asyncHandler(async (req, res) => {
    await deleteEvent(requireParam(req, "id"));
    res.status(204).send();
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

// Manual override for a scheduled event ahead of its start time - e.g. the
// admin knows in advance it needs to be called off. The scheduler worker
// (services/eventScheduler.ts) otherwise owns every phase transition
// automatically; this is the human-in-the-loop exception.
adminRoutes.post(
  "/events/:id/scheduling/phase",
  asyncHandler(async (req, res) => {
    const { phase } = req.body as { phase: "CANCELLED" | "POSTPONED" };
    if (phase !== "CANCELLED" && phase !== "POSTPONED") {
      throw AppError.badRequest("phase must be CANCELLED or POSTPONED");
    }
    const event = await setEventSchedulingPhase(requireParam(req, "id"), phase);
    res.json({ event });
  }),
);

// Every room ever created under one event (any status), each with who
// created it and whether it's currently running - the admin's "open this
// event" drill-down instead of one giant cross-event page.
adminRoutes.get(
  "/events/:id/rooms",
  asyncHandler(async (req, res) => {
    const data = await listRoomsForEventAdmin(requireParam(req, "id"));
    res.json(data);
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

// Full snapshot of one room (participants, live leaderboard, round/timer
// state) - the same shape participants themselves receive over Socket.IO,
// used here for the admin spectator view's first paint before the socket
// subscription (see sockets/handlers.ts "admin:spectate") takes over.
adminRoutes.get(
  "/competitions/:id",
  asyncHandler(async (req, res) => {
    const snapshot = await getRoomSnapshot(requireParam(req, "id"));
    if (!snapshot) throw AppError.notFound("Competition room not found");
    res.json({ room: snapshot });
  }),
);
