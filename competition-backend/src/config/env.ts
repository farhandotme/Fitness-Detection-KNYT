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
  // Legacy shared-secret admin auth. Superseded by real admin accounts
  // (register/login below) but left here in case it's still referenced.
  ADMIN_API_KEY: z.string().default("change-me-admin-key"),
  MAX_PARTICIPANTS_PER_ROOM: z.coerce.number().int().min(2).max(5).default(5),

  // Admin accounts: register/login instead of a single shared key.
  // JWT_SECRET signs admin session tokens - must be a long random string in production.
  JWT_SECRET: z.string().default("change-me-jwt-secret-please-override"),
  // A simple invite code required to self-register a new admin account. This
  // keeps event creation from being wide open to any visitor while still
  // letting you (the developer) create your own admin login for testing,
  // without building a full user-management system.
  ADMIN_SIGNUP_CODE: z.string().default("change-me-signup-code"),
  // Once you've created the admin account(s) you need, set this to "false"
  // and redeploy to close registration entirely - defense in depth beyond
  // just the signup code above.
  ADMIN_REGISTRATION_ENABLED: z
    .string()
    .default("true")
    .transform((v) => v === "true" || v === "1"),

  // Set to "true" when running behind a reverse proxy / load balancer (nginx,
  // Caddy, an ALB, etc.) so Express reads the real client IP from
  // X-Forwarded-For instead of the proxy's own address. This matters for the
  // rate limiter below - without it every request looks like it comes from
  // the proxy and the limiter either blocks everyone or no one.
  TRUST_PROXY: z
    .string()
    .default("false")
    .transform((v) => v === "true" || v === "1"),

  // Auth rate limiting (login/register) - protects against credential
  // stuffing / brute force on the admin login form.
  AUTH_RATE_LIMIT_MAX: z.coerce.number().int().min(1).default(10),
  AUTH_RATE_LIMIT_WINDOW_MINUTES: z.coerce.number().int().min(1).default(15),

  // How often (ms) the event scheduler worker re-derives "what phase should
  // each scheduled event be in right now" from its stored timestamps. See
  // services/eventScheduler.ts. Kept well under a minute so a registration
  // window or start time is never missed by more than a few seconds.
  SCHEDULER_TICK_MS: z.coerce.number().int().min(1000).default(5000),
  // Default IANA zone applied to a scheduled event when the admin doesn't
  // pick one explicitly - matches this deployment's primary audience.
  EVENT_TIMEZONE_DEFAULT: z.string().default("Asia/Kolkata"),

  // Player avatar photos (see services/avatarService.ts) are stored in
  // Cloudinary, never on this server or in MongoDB - we only ever persist
  // the resulting URL/publicId. All three are optional: with any of them
  // unset, POST /api/avatars/signature responds 503 and the frontend falls
  // back to generated cartoon avatars for everyone (see config/cloudinary.ts).
  CLOUDINARY_CLOUD_NAME: z.string().optional(),
  CLOUDINARY_API_KEY: z.string().optional(),
  CLOUDINARY_API_SECRET: z.string().optional(),
  // Every avatar upload is signed into this folder, and deletion requests
  // are only ever honored for publicIds under it - see avatarRoutes.ts -
  // so a compromised/guessed publicId from elsewhere in the account can't
  // be used to delete unrelated assets.
  CLOUDINARY_AVATAR_FOLDER: z.string().default("fitness-competition/avatars"),
  AVATAR_RATE_LIMIT_MAX: z.coerce.number().int().min(1).default(20),
  AVATAR_RATE_LIMIT_WINDOW_MINUTES: z.coerce.number().int().min(1).default(10),
  // Event cover/advertising images (see services/eventImageService.ts) live in
  // their own Cloudinary folder, separate from avatars, so deletion requests
  // for one can never be aimed at the other.
  CLOUDINARY_EVENT_IMAGE_FOLDER: z
    .string()
    .default("fitness-competition/events"),
});

const parsed = envSchema.safeParse(process.env);

if (!parsed.success) {
  // eslint-disable-next-line no-console
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

// Cloudinary is all-or-nothing: a partially set trio is almost always a
// typo'd/half-pasted .env rather than an intentional "disabled" state, so
// fail loudly instead of quietly running with avatar uploads half-broken.
const cloudinaryVars = [
  data.CLOUDINARY_CLOUD_NAME,
  data.CLOUDINARY_API_KEY,
  data.CLOUDINARY_API_SECRET,
];
const cloudinaryConfigured = cloudinaryVars.every(Boolean);
if (!cloudinaryConfigured && cloudinaryVars.some(Boolean)) {
  // eslint-disable-next-line no-console
  console.error(
    "Incomplete Cloudinary configuration - CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET must all be set together (or all left unset to disable photo avatars).",
  );
  process.exit(1);
}

export const env = {
  ...data,
  // Allow a comma-separated list of origins.
  corsOrigins: data.CORS_ORIGIN.split(",")
    .map((o) => o.trim())
    .filter(Boolean),
  cloudinaryConfigured,
};
