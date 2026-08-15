import express from "express";
import cors from "cors";
import helmet from "helmet";
import compression from "compression";
import pinoHttp from "pino-http";
import { env } from "./config/env.js";
import { logger } from "./config/logger.js";
import { eventRoutes } from "./routes/eventRoutes.js";
import { roomRoutes } from "./routes/roomRoutes.js";
import { adminRoutes } from "./routes/adminRoutes.js";
import { authRoutes } from "./routes/authRoutes.js";
import { healthRoutes } from "./routes/healthRoutes.js";
import { avatarRoutes } from "./routes/avatarRoutes.js";
import { errorHandler, notFoundHandler } from "./middleware/errorHandler.js";
import { authRateLimiter, avatarRateLimiter } from "./middleware/rateLimit.js";

export function createApp() {
  const app = express();

  // Required for express-rate-limit (and any other req.ip use) to see the
  // real client IP instead of the reverse proxy's when TRUST_PROXY=true.
  if (env.TRUST_PROXY) {
    app.set("trust proxy", 1);
  }

  app.use(helmet());
  app.use(compression());
  app.use(
    cors({
      origin: env.corsOrigins,
      credentials: true,
    }),
  );
  app.use(express.json({ limit: "256kb" }));
  app.use(
    pinoHttp({
      logger,
      autoLogging: { ignore: (req) => req.url === "/health" },
    }),
  );

  app.use("/health", healthRoutes);
  app.use("/api/events", eventRoutes);
  // Nested under the same /api/events/:eventId prefix as eventRoutes -
  // browsing/creating/joining rooms for a specific event.
  app.use("/api/events/:eventId/rooms", roomRoutes);
  // Mounted before the protected /api/admin routes so register/login never
  // hit the admin-session middleware defined in adminRoutes. Rate-limited
  // since this is the endpoint most worth brute-forcing.
  app.use("/api/admin/auth", authRateLimiter, authRoutes);
  app.use("/api/admin", adminRoutes);
  // Signed Cloudinary upload/delete for player avatar photos - see
  // routes/avatarRoutes.ts and services/avatarService.ts.
  app.use("/api/avatars", avatarRateLimiter, avatarRoutes);

  app.use(notFoundHandler);
  app.use(errorHandler);

  return app;
}
