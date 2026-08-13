import { z } from "zod";

export const createEventSchema = z.object({
  name: z.string().trim().min(3).max(120),
  exerciseId: z.string().trim().min(1),
  exerciseName: z.string().trim().min(1),
  exerciseMode: z.enum(["reps", "hold"]),
  rounds: z.number().int().min(1).max(10).default(2),
  roundDurationSeconds: z.number().int().min(10).max(600).default(60),
  breakDurationSeconds: z.number().int().min(5).max(300).default(15),
  maxParticipants: z.number().int().min(2).max(5).default(5),
  description: z.string().max(500).optional(),
  status: z.enum(["draft", "live", "closed"]).default("live"),
});

export const updateEventSchema = createEventSchema.partial();

export type CreateEventInput = z.infer<typeof createEventSchema>;
