import mongoose from "mongoose";
import { env } from "./env.js";
import { logger } from "./logger.js";

export async function connectMongo(): Promise<void> {
  mongoose.set("strictQuery", true);
  // Auto-creating indexes on every boot is fine in dev but adds startup
  // latency and lock contention in production - build them once out of band
  // (`mongosh` / a migration step) and disable it here.
  mongoose.set("autoIndex", env.NODE_ENV !== "production");

  mongoose.connection.on("connected", () => logger.info("MongoDB connected"));
  mongoose.connection.on("error", (err) => logger.error({ err }, "MongoDB connection error"));
  mongoose.connection.on("disconnected", () => logger.warn("MongoDB disconnected"));

  await mongoose.connect(env.MONGODB_URI, {
    serverSelectionTimeoutMS: 8000,
    maxPoolSize: 20,
    retryWrites: true,
  });
}

export async function disconnectMongo(): Promise<void> {
  await mongoose.disconnect();
}
