import "dotenv/config";
import { z } from "zod";

const envSchema = z.object({
  PORT: z.coerce.number().default(4000),
  NODE_ENV: z
    .enum(["development", "production", "test"])
    .default("development"),
  LOG_LEVEL: z.string().default("info"),
  CORS_ORIGIN: z.string().default("http://localhost:5173"),
  MONGODB_URI: z
    .string()
    .default("mongodb://localhost:27017/exercise_competition"),
  REDIS_URL: z.string().default("redis://localhost:6379"),
  ADMIN_API_KEY: z.string().default("change-me-admin-key"),
  MAX_PARTICIPANTS_PER_ROOM: z.coerce.number().int().min(2).max(5).default(5),

  JWT_SECRET: z.string().default("change-me-jwt-secret-please-override"),
  ADMIN_SIGNUP_CODE: z.string().default("change-me-signup-code"),
  ADMIN_REGISTRATION_ENABLED: z
    .string()
    .default("true")
    .transform((v) => v === "true" || v === "1"),

  TRUST_PROXY: z
    .string()
    .default("false")
    .transform((v) => v === "true" || v === "1"),

  AUTH_RATE_LIMIT_MAX: z.coerce.number().int().min(1).default(10),
  AUTH_RATE_LIMIT_WINDOW_MINUTES: z.coerce.number().int().min(1).default(15),
});

const parsed = envSchema.safeParse(process.env);

if (!parsed.success) {
  console.error(
    "Invalid environment configuration:",
    parsed.error.flatten().fieldErrors,
  );
  process.exit(1);
}

const data = parsed.data;

// Refuse to boot in production with secrets that are obviously still the
// placeholder defaults from .env.example - this is the single most common
// way "it worked in dev" turns into a real incident, so fail loudly here
// instead of silently running with a guessable JWT secret / admin key.
if (data.NODE_ENV === "production") {
  const weakDefaults: Record<string, string> = {
    JWT_SECRET: "change-me-jwt-secret-please-override",
    ADMIN_SIGNUP_CODE: "change-me-signup-code",
    ADMIN_API_KEY: "change-me-admin-key",
  };
  const offenders = Object.entries(weakDefaults).filter(
    ([key, placeholder]) => {
      const value = (data as Record<string, unknown>)[key];
      return typeof value === "string" && value === placeholder;
    },
  );
  if (offenders.length > 0) {
    // eslint-disable-next-line no-console
    console.error(
      `Refusing to start in production with placeholder value(s) for: ${offenders
        .map(([key]) => key)
        .join(
          ", ",
        )}. Set real secrets in your environment (e.g. \`openssl rand -hex 32\` for JWT_SECRET).`,
    );
    process.exit(1);
  }
  if (data.JWT_SECRET.length < 32) {
    // eslint-disable-next-line no-console
    console.error(
      "JWT_SECRET is too short for production - use at least 32 random characters.",
    );
    process.exit(1);
  }
  if (data.CORS_ORIGIN.includes("localhost")) {
    // eslint-disable-next-line no-console
    console.error(
      "CORS_ORIGIN still points at localhost in production - set it to your real frontend origin(s).",
    );
    process.exit(1);
  }
}

export const env = {
  ...data,
  // Allow a comma-separated list of origins.
  corsOrigins: data.CORS_ORIGIN.split(",")
    .map((o) => o.trim())
    .filter(Boolean),
};
