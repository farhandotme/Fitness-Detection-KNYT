import { z } from "zod";
import { zonedTimeToUtc } from "../utils/timezone.js";
import { env } from "../config/env.js";

// Wall-clock local datetime with no offset, e.g. "2026-08-20T19:00" or
// "2026-08-20T19:00:00" - what a plain HTML <input type="datetime-local">
// (or a date input + time input combined client-side) produces. It is
// interpreted against `timezone` below, not the server's own local time.
const localDateTimeString = z
  .string()
  .trim()
  .regex(
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/,
    "Expected a local datetime like 2026-08-20T19:00",
  );

const schedulingInputSchema = z
  .object({
    scheduledAtLocal: localDateTimeString,
    registrationOpensAtLocal: localDateTimeString,
    registrationClosesAtLocal: localDateTimeString,
    timezone: z.string().trim().min(1).default(env.EVENT_TIMEZONE_DEFAULT),
    minParticipants: z.number().int().min(1).max(5).default(2),
    onInsufficientParticipants: z
      .enum(["cancel", "postpone"])
      .default("cancel"),
  })
  .transform((input, ctx) => {
    let scheduledAt: Date;
    let registrationOpensAt: Date;
    let registrationClosesAt: Date;
    try {
      scheduledAt = zonedTimeToUtc(input.scheduledAtLocal, input.timezone);
      registrationOpensAt = zonedTimeToUtc(
        input.registrationOpensAtLocal,
        input.timezone,
      );
      registrationClosesAt = zonedTimeToUtc(
        input.registrationClosesAtLocal,
        input.timezone,
      );
    } catch {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: `Unknown timezone: ${input.timezone}`,
      });
      return z.NEVER;
    }

    if (registrationOpensAt.getTime() >= registrationClosesAt.getTime()) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Registration must open before it closes",
        path: ["registrationOpensAtLocal"],
      });
    }
    if (registrationClosesAt.getTime() > scheduledAt.getTime()) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message:
          "Registration must close at or before the competition start time",
        path: ["registrationClosesAtLocal"],
      });
    }

    return {
      scheduledAt,
      registrationOpensAt,
      registrationClosesAt,
      timezone: input.timezone,
      minParticipants: input.minParticipants,
      onInsufficientParticipants: input.onInsufficientParticipants,
      phase: "DRAFT" as const,
    };
  });

// Base object (no cross-field refinement yet) so both the strict create
// schema and the partial update schema can be derived from the same shape -
// z.object.partial() isn't available once .superRefine() has wrapped it.
const eventBaseSchema = z.object({
  name: z.string().trim().min(3).max(120),
  exerciseId: z.string().trim().min(1),
  exerciseName: z.string().trim().min(1),
  exerciseMode: z.enum(["reps", "hold"]),
  rounds: z.number().int().min(1).max(10).default(2),
  roundDurationSeconds: z.number().int().min(10).max(600).default(60),
  breakDurationSeconds: z.number().int().min(5).max(300).default(15),
  maxParticipants: z.number().int().min(2).max(5).default(5),
  description: z.string().max(500).optional(),
  imageUrl: z
    .string()
    .trim()
    .url("Must be a valid URL")
    .max(500)
    .optional()
    .or(z.literal("")),
  status: z.enum(["draft", "live", "closed"]).default("live"),
  // Omit entirely for an immediate-start event (unchanged v1 behaviour).
  // Present only when the admin picks "schedule for later".
  scheduling: schedulingInputSchema.optional(),
});

function checkMinParticipants(
  input: {
    scheduling?: { minParticipants: number } | null;
    maxParticipants?: number;
  },
  ctx: z.RefinementCtx,
) {
  if (
    input.scheduling &&
    input.maxParticipants !== undefined &&
    input.scheduling.minParticipants > input.maxParticipants
  ) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message:
        "Minimum participants can't exceed the room's maximum participants",
      path: ["scheduling", "minParticipants"],
    });
  }
}

export const createEventSchema =
  eventBaseSchema.superRefine(checkMinParticipants);
export const updateEventSchema = eventBaseSchema
  .partial()
  .superRefine(checkMinParticipants);

export type CreateEventInput = z.infer<typeof createEventSchema>;
