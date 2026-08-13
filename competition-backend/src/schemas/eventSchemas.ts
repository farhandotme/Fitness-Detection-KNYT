import { z } from "zod";

// Wall-clock time with no offset, e.g. "2026-08-20T19:00" - the admin picks
// this alongside `timezone`, and the backend converts it to UTC (see
// utils/timezone.ts) before storing. Chosen over accepting a pre-converted
// UTC string so the admin form can stay in local time end to end.
const localDateTimeRegex = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/;
const localDateTime = z
  .string()
  .trim()
  .regex(localDateTimeRegex, "Use YYYY-MM-DDTHH:mm");

const baseEventSchema = z.object({
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

  // --- Scheduling add-on (all optional unless eventType is "scheduled",
  // enforced below in createEventSchema's superRefine) ---
  eventType: z.enum(["instant", "scheduled"]).default("instant"),
  timezone: z.string().trim().min(1).max(64).default("Asia/Kolkata"),
  minParticipants: z.number().int().min(1).max(5).default(2),
  onInsufficientParticipants: z.enum(["cancel", "postpone"]).default("cancel"),
  scheduledAtLocal: localDateTime.optional(),
  registrationOpensAtLocal: localDateTime.optional(),
  registrationClosesAtLocal: localDateTime.optional(),
});

export const createEventSchema = baseEventSchema.superRefine((data, ctx) => {
  if (data.minParticipants > data.maxParticipants) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["minParticipants"],
      message: "minParticipants cannot exceed maxParticipants",
    });
  }

  if (data.eventType !== "scheduled") return;

  (
    [
      "scheduledAtLocal",
      "registrationOpensAtLocal",
      "registrationClosesAtLocal",
    ] as const
  ).forEach((field) => {
    if (!data[field]) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: [field],
        message: `${field} is required for scheduled events`,
      });
    }
  });

  if (
    data.scheduledAtLocal &&
    data.registrationOpensAtLocal &&
    data.registrationClosesAtLocal
  ) {
    // "YYYY-MM-DDTHH:mm" strings sort lexically the same as chronologically,
    // so plain string comparison is enough here.
    const opensOk =
      data.registrationOpensAtLocal < data.registrationClosesAtLocal;
    const closesOk = data.registrationClosesAtLocal <= data.scheduledAtLocal;
    if (!opensOk || !closesOk) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["registrationClosesAtLocal"],
        message:
          "Registration must open before it closes, and close at or before the competition start time",
      });
    }
  }
});

export const updateEventSchema = baseEventSchema.partial();

export type CreateEventInput = z.infer<typeof createEventSchema>;
export type UpdateEventInput = z.infer<typeof updateEventSchema>;
