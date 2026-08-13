import { z } from "zod";

const COMPETITION_STATUSES = [
  "WAITING",
  "FULL",
  "COUNTDOWN",
  "ROUND_RUNNING",
  "ROUND_FINISHED",
  "BREAK",
  "COMPLETED",
  "ABANDONED",
] as const;

// Query params always arrive as strings - z.coerce handles the page/limit
// numbers, and empty string (an unset <select>) is normalized to undefined
// rather than failing enum validation.
const emptyToUndefined = (v: unknown) => (v === "" ? undefined : v);

export const listCompetitionsQuerySchema = z.object({
  status: z.preprocess(emptyToUndefined, z.enum(COMPETITION_STATUSES).optional()),
  eventId: z.preprocess(emptyToUndefined, z.string().trim().min(1).optional()),
  page: z.coerce.number().int().min(1).default(1),
  limit: z.coerce.number().int().min(1).max(100).default(20),
});

export const abandonCompetitionSchema = z.object({
  reason: z.string().trim().max(300).optional(),
});

export type ListCompetitionsQuery = z.infer<typeof listCompetitionsQuerySchema>;
