import { Schema, model, type InferSchemaType } from "mongoose";

// Fine-grained lifecycle for *scheduled* events only (see `scheduling`
// below). Plain immediate-start events never touch this - they just flip
// the top-level `status` between draft/live/closed as they always have.
export const SCHEDULING_PHASES = [
  "DRAFT",
  "PUBLISHED",
  "REGISTRATION_OPEN",
  "REGISTRATION_CLOSED",
  "LIVE",
  "COMPLETED",
  "CANCELLED",
  "POSTPONED",
] as const;

const schedulingSchema = new Schema(
  {
    // All three are absolute UTC instants - the admin enters wall-clock
    // time + an IANA zone, and the API layer (see schemas/eventSchemas.ts)
    // converts that to UTC once, at creation time, using utils/timezone.ts.
    scheduledAt: { type: Date, required: true },
    // Optional - when the event is expected to wrap up (e.g. "7 PM - 11
    // PM"). Display-only: nothing force-stops a room at this time, rounds
    // still just run to completion via competitionEngine.
    scheduledEndAt: { type: Date, required: false },
    registrationOpensAt: { type: Date, required: true },
    registrationClosesAt: { type: Date, required: true },
    // Display-only after creation (the UTC fields above are what the
    // scheduler actually compares against) but kept so the admin UI and
    // participant-facing pages can render times back in the zone the event
    // was created in, e.g. "7:00 PM IST" instead of a raw UTC timestamp.
    timezone: { type: String, required: true, default: "Asia/Kolkata" },
    // How many participants must have joined by `scheduledAt` for the
    // competition to actually start. Below this, the scheduler cancels
    // (or postpones) the event instead of starting an under-filled room.
    minParticipants: {
      type: Number,
      required: true,
      min: 1,
      max: 5,
      default: 2,
    },
    onInsufficientParticipants: {
      type: String,
      enum: ["cancel", "postpone"],
      default: "cancel",
    },
    phase: { type: String, enum: SCHEDULING_PHASES, default: "DRAFT" },
  },
  { _id: false },
);

const eventSchema = new Schema(
  {
    name: { type: String, required: true, trim: true, maxlength: 120 },
    // Must match an `id` in the existing frontend's src/config/exercises.ts catalog,
    // e.g. "pushup", "squat", "jumping_jack", "skipping". The competition backend
    // never interprets this itself - it is passed straight to the client and to
    // whatever reports scores back, so new exercises need zero backend changes.
    exerciseId: { type: String, required: true, trim: true },
    exerciseName: { type: String, required: true, trim: true },
    exerciseMode: { type: String, enum: ["reps", "hold"], required: true },
    rounds: { type: Number, required: true, min: 1, max: 10, default: 2 },
    roundDurationSeconds: {
      type: Number,
      required: true,
      min: 10,
      max: 600,
      default: 60,
    },
    breakDurationSeconds: {
      type: Number,
      required: true,
      min: 5,
      max: 300,
      default: 15,
    },
    maxParticipants: {
      type: Number,
      required: true,
      min: 2,
      max: 5,
      default: 5,
    },
    // How many players a room under this event needs before its host is
    // allowed to start it manually, without waiting for the room to fill
    // to maxParticipants. Distinct from scheduling.minParticipants above,
    // which governs a *scheduled* event's own auto-cancel/postpone check -
    // this one applies to every room (scheduled or not) and is purely
    // about letting a host of an under-filled private/public room go early.
    minParticipants: {
      type: Number,
      required: true,
      min: 1,
      max: 5,
      default: 2,
    },
    status: {
      type: String,
      enum: ["draft", "live", "closed"],
      default: "live",
    },
    description: { type: String, default: "" },
    // Optional cover image shown on event cards (join screen + admin
    // dashboard). Just a URL - no upload/storage pipeline in v1, matching
    // how lean the rest of the anonymous-participant system is kept.
    imageUrl: { type: String, default: "" },
    // Absent entirely for a normal "starts as soon as a room fills" event -
    // that keeps every existing event working exactly as before. Present
    // only for events created with a scheduled start; see
    // services/eventScheduler.ts for the worker that drives `phase` forward.
    scheduling: { type: schedulingSchema, required: false, default: undefined },
  },
  { timestamps: true },
);

eventSchema.index({ status: 1, createdAt: -1 });
eventSchema.index({ "scheduling.scheduledAt": 1, "scheduling.phase": 1 });

export type EventDoc = InferSchemaType<typeof eventSchema>;
export const EventModel = model("Event", eventSchema);
