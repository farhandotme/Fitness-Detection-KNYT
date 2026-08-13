import { Router } from "express";
import mongoose from "mongoose";
import { redis } from "../config/redis.js";

export const healthRoutes = Router();

healthRoutes.get("/", async (_req, res) => {
  const mongoOk = mongoose.connection.readyState === 1;
  let redisOk = false;
  try {
    redisOk = (await redis.ping()) === "PONG";
  } catch {
    redisOk = false;
  }
  const ok = mongoOk && redisOk;
  res.status(ok ? 200 : 503).json({ ok, mongo: mongoOk, redis: redisOk });
});
