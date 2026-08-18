import rateLimit from "express-rate-limit";
import { env } from "../config/env.js";

// Applied to /api/admin/auth/* only - this is the endpoint an attacker would
// actually brute-force (login) or abuse (register). General GET /api/events
// traffic is left unlimited since it's read-only and cacheable.
export const authRateLimiter = rateLimit({
  windowMs: env.AUTH_RATE_LIMIT_WINDOW_MINUTES * 60 * 1000,
  max: env.AUTH_RATE_LIMIT_MAX,
  standardHeaders: true,
  legacyHeaders: false,
  message: {
    code: "RATE_LIMITED",
    message: "Too many attempts, please try again later.",
  },
});

// Applied to /api/avatars/* - signing an upload and deleting one are both
// cheap Cloudinary API calls, but uncapped they'd let someone script a
// storage-filling or delete-guessing attack. A player only ever needs one
// or two of these per game.
export const avatarRateLimiter = rateLimit({
  windowMs: env.AVATAR_RATE_LIMIT_WINDOW_MINUTES * 60 * 1000,
  max: env.AVATAR_RATE_LIMIT_MAX,
  standardHeaders: true,
  legacyHeaders: false,
  message: {
    code: "RATE_LIMITED",
    message: "Too many avatar requests, please try again later.",
  },
});

// Applied to /api/discover/rooms - the "near you" search inside the Events
// page. Public, unauthenticated, and takes raw lat/lng, so without a limit
// it's a cheap way to hammer the geo index or scrape every open room's
// location across the whole app. Kept generous enough that a real person
// switching radius/region a few times a minute never notices it.
export const discoverRateLimiter = rateLimit({
  windowMs: env.DISCOVER_RATE_LIMIT_WINDOW_MINUTES * 60 * 1000,
  max: env.DISCOVER_RATE_LIMIT_MAX,
  standardHeaders: true,
  legacyHeaders: false,
  message: {
    code: "RATE_LIMITED",
    message: "Too many location searches, please slow down and try again.",
  },
});
