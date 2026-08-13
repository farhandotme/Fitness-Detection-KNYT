import { createServer } from "node:http";
import { Server } from "socket.io";
import { env } from "./config/env.js";
import { logger } from "./config/logger.js";
import { connectMongo, disconnectMongo } from "./config/db.js";
import { redis } from "./config/redis.js";
import { createApp } from "./app.js";
import { registerSocketHandlers } from "./sockets/handlers.js";

async function main() {
  await connectMongo();

  const app = createApp();
  const httpServer = createServer(app);

  const io = new Server(httpServer, {
    cors: {
      origin: env.corsOrigins,
      credentials: true,
    },
  });

  registerSocketHandlers(io);

  httpServer.listen(env.PORT, () => {
    logger.info(
      `competition-backend listening on :${env.PORT} (${env.NODE_ENV})`,
    );
  });

  let shuttingDown = false;
  const shutdown = async (signal: string) => {
    if (shuttingDown) return;
    shuttingDown = true;
    logger.info({ signal }, "shutting down");

    const forceExit = setTimeout(() => {
      logger.warn("graceful shutdown timed out, forcing exit");
      process.exit(1);
    }, 10_000);
    forceExit.unref();

    try {
      io.close();
      await new Promise<void>((resolve) => httpServer.close(() => resolve()));
      await disconnectMongo();
      redis.disconnect();
      clearTimeout(forceExit);
      process.exit(0);
    } catch (err) {
      logger.error({ err }, "error during shutdown");
      process.exit(1);
    }
  };

  process.on("SIGINT", () => void shutdown("SIGINT"));
  process.on("SIGTERM", () => void shutdown("SIGTERM"));

  // Last line of defense: log and exit rather than continuing in an unknown
  // state, which is safer under a process manager that will restart us.
  process.on("uncaughtException", (err) => {
    logger.error({ err }, "uncaught exception");
    void shutdown("uncaughtException");
  });
  process.on("unhandledRejection", (reason) => {
    logger.error({ err: reason }, "unhandled promise rejection");
    void shutdown("unhandledRejection");
  });
}

main().catch((err) => {
  logger.error({ err }, "fatal startup error");
  process.exit(1);
});
