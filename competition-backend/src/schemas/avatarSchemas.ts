import { z } from "zod";

// Cloudinary publicIds are folder-segments joined with "/" - allow that
// plus the usual URL-safe nanoid alphabet. Deliberately conservative: this
// only needs to match what services/avatarService.ts itself generates.
export const avatarPublicIdSchema = z
  .string()
  .trim()
  .min(1)
  .max(300)
  .regex(/^[A-Za-z0-9_\-/]+$/, "Invalid avatar id");
