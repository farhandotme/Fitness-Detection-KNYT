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
