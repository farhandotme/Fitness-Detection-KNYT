import { Router } from "express";
import { asyncHandler } from "../utils/asyncHandler.js";
import {
  createAvatarUploadSignature,
  deleteAvatar,
} from "../services/avatarService.js";
import { avatarPublicIdSchema } from "../schemas/avatarSchemas.js";
import { AppError } from "../utils/errors.js";

export const avatarRoutes = Router();

// POST /api/avatars/signature - authorizes exactly one direct-to-Cloudinary
// upload. The frontend then POSTs the file straight to Cloudinary with this
// payload (see frontend src/lib/avatarStore.ts uploadAvatarPhoto) - the
// image itself never passes through this server. Returns 503 with
// AVATAR_UPLOADS_DISABLED if Cloudinary isn't configured for this
// deployment, which the frontend treats as "everyone gets a generated
// avatar instead", not an error to surface to the player.
avatarRoutes.post(
  "/signature",
  asyncHandler(async (_req, res) => {
    const signature = createAvatarUploadSignature();
    res.json(signature);
  }),
);

// POST /api/avatars/delete - removes a previously uploaded photo. Takes
// { publicId } in the body rather than a URL segment since Cloudinary
// publicIds contain slashes (folder/id). Called from the frontend once a
// player's session with that photo is over (see hooks/useCompetitionRoom.ts
// leave(), CompetitionResultsPage) via a keepalive fetch so it still lands
// even mid-navigation. Also invoked internally (not through this route)
// whenever a seat is freed server-side - see services/competitionService.ts.
avatarRoutes.post(
  "/delete",
  asyncHandler(async (req, res) => {
    const parsed = avatarPublicIdSchema.safeParse(req.body?.publicId);
    if (!parsed.success) throw AppError.badRequest("Invalid avatar id");
    await deleteAvatar(parsed.data);
    res.status(204).end();
  }),
);
