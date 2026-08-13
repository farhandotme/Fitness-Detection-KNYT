import { Router } from "express";
import type { Request, Response, NextFunction } from "express";
import { asyncHandler, requireParam } from "../utils/asyncHandler.js";
import { AppError } from "../utils/errors.js";
import {
  createEventSchema,
  updateEventSchema,
} from "../schemas/eventSchemas.js";
import {
  abandonCompetitionSchema,
  listCompetitionsQuerySchema,
} from "../schemas/adminQuerySchemas.js";
import {
  createEvent,
  deleteDraftEvent,
  getEventByIdAdmin,
  getEventStatsMap,
  listAllEventsAdmin,
  updateEvent,
  updateEventStatus,
} from "../services/eventService.js";
import {
  abandonCompetitionAdmin,
  exportEventResultsCsv,
  getAdminCompetitionDetail,
  getDashboardStats,
  listAllCompetitionsAdmin,
  listCompetitionsForEvent,
  removeParticipantAdmin,
} from "../services/competitionService.js";
import { verifyAdminToken, type AdminTokenPayload } from "../utils/jwt.js";

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

// --- Dashboard -------------------------------------------------------------

adminRoutes.get(
  "/dashboard/stats",
  asyncHandler(async (_req, res) => {
    const stats = await getDashboardStats();
    res.json({ stats });
  }),
);

// --- Events ------------------------------------------------------------

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

adminRoutes.get(
  "/events/:id",
  asyncHandler(async (req, res) => {
    const id = requireParam(req, "id");
    const event = await getEventByIdAdmin(id);
    const statsMap = await getEventStatsMap([id]);
    res.json({
      event: {
        ...event,
        stats: statsMap.get(id) ?? {
          active: 0,
          completed: 0,
          abandoned: 0,
          totalParticipants: 0,
        },
      },
    });
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

adminRoutes.post(
  "/events/:id/status",
  asyncHandler(async (req, res) => {
    const { status } = req.body as { status: "draft" | "live" | "closed" };
    const event = await updateEventStatus(requireParam(req, "id"), status);
    res.json({ event });
  }),
);

adminRoutes.delete(
  "/events/:id",
  asyncHandler(async (req, res) => {
    await deleteDraftEvent(requireParam(req, "id"));
    res.status(204).end();
  }),
);

// List every room (competition) an event has ever spawned - the admin
// event-detail page's "rooms" tab. Supports the same status filter +
// pagination as the global monitor below, scoped to one event.
adminRoutes.get(
  "/events/:id/competitions",
  asyncHandler(async (req, res) => {
    const query = listCompetitionsQuerySchema.parse(req.query);
    const result = await listCompetitionsForEvent(
      requireParam(req, "id"),
      query,
    );
    res.json(result);
  }),
);

// CSV of final results across every completed room under this event -
// downloadable straight from the admin event-detail page.
adminRoutes.get(
  "/events/:id/results.csv",
  asyncHandler(async (req, res) => {
    const id = requireParam(req, "id");
    const event = await getEventByIdAdmin(id);
    const csv = await exportEventResultsCsv(id);
    const filename = `${event.name.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}-results.csv`;
    res.setHeader("Content-Type", "text/csv; charset=utf-8");
    res.setHeader("Content-Disposition", `attachment; filename="${filename}"`);
    res.send(csv);
  }),
);

// --- Competitions (rooms) - cross-event monitoring & moderation -----------

adminRoutes.get(
  "/competitions",
  asyncHandler(async (req, res) => {
    const query = listCompetitionsQuerySchema.parse(req.query);
    const result = await listAllCompetitionsAdmin(query);
    res.json(result);
  }),
);

adminRoutes.get(
  "/competitions/:id",
  asyncHandler(async (req, res) => {
    const detail = await getAdminCompetitionDetail(requireParam(req, "id"));
    res.json(detail);
  }),
);

// Force-end a stuck/problem room. Distinct from a room finishing normally -
// no rank/results are produced, since it never legitimately completed.
adminRoutes.post(
  "/competitions/:id/abandon",
  asyncHandler(async (req, res) => {
    const { reason } = abandonCompetitionSchema.parse(req.body ?? {});
    await abandonCompetitionAdmin(
      requireParam(req, "id"),
      reason || "Ended by admin",
    );
    res.json({ ok: true });
  }),
);

// Remove a single participant pre-start (e.g. joined by mistake, or is
// disrupting the waiting room). Only allowed before the room starts -
// see removeParticipantAdmin for why.
adminRoutes.delete(
  "/competitions/:id/participants/:participantId",
  asyncHandler(async (req, res) => {
    await removeParticipantAdmin(
      requireParam(req, "id"),
      requireParam(req, "participantId"),
    );
    res.status(204).end();
  }),
);
