import Redis from "ioredis";
import { env } from "./env.js";
import { logger } from "./logger.js";

export const redis = new Redis(env.REDIS_URL, {
  maxRetriesPerRequest: 3,
  lazyConnect: false,
  retryStrategy: (attempt) => Math.min(attempt * 200, 5000),
});

redis.on("connect", () => logger.info("Redis connected"));
redis.on("error", (err) => logger.error({ err }, "Redis connection error"));

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
