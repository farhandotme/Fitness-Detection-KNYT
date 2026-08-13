import Redis from "ioredis";
import { env } from "./env.js";
import { logger } from "./logger.js";

export const redis = new Redis(env.REDIS_URL, {
  maxRetriesPerRequest: 3,
  lazyConnect: false,
  // Exponential backoff (capped at 5s) instead of the default fixed retry,
  // so a brief Redis restart in production doesn't hammer it with reconnects.
  retryStrategy: (attempt) => Math.min(attempt * 200, 5000),
});

redis.on("connect", () => logger.info("Redis connected"));
redis.on("error", (err) => logger.error({ err }, "Redis connection error"));

/**
 * Atomically add a participant to a room's participant hash if, and only if,
 * the room is not already at capacity. This is what makes the 5-participant
 * cap safe against two people taking the last slot at the same instant -
 * Redis executes the whole script single-threaded, so there is no
 * check-then-act race condition between two concurrent join requests.
 *
 * KEYS[1] = participants hash key  (comp:{id}:participants)
 * ARGV[1] = maxParticipants
 * ARGV[2] = participantId
 * ARGV[3] = participant JSON payload
 *
 * Returns: 1 (joined), 0 (room full), 2 (already a member - idempotent)
 */
const JOIN_ROOM_SCRIPT = `
local key = KEYS[1]
local max = tonumber(ARGV[1])
local participantId = ARGV[2]
local payload = ARGV[3]

if redis.call("HEXISTS", key, participantId) == 1 then
  redis.call("HSET", key, participantId, payload)
  return 2
end

local count = redis.call("HLEN", key)
if count >= max then
  return 0
end

redis.call("HSET", key, participantId, payload)
return 1
`;

redis.defineCommand("joinRoom", {
  numberOfKeys: 1,
  lua: JOIN_ROOM_SCRIPT,
});

declare module "ioredis" {
  interface RedisCommander<Context> {
    joinRoom(
      participantsKey: string,
      max: number,
      participantId: string,
      payload: string,
    ): Promise<number>;
  }
}
