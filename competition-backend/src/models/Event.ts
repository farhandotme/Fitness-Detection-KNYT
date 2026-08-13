import { Schema, model, type InferSchemaType } from "mongoose";

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
    status: {
      type: String,
      enum: ["draft", "live", "closed"],
      default: "live",
    },
    description: { type: String, default: "" },
    imageUrl: { type: String, default: "" },

    eventType: {
      type: String,
      enum: ["instant", "scheduled"],
      default: "instant",
    },
    timezone: { type: String, default: "Asia/Kolkata" },
    scheduledAt: { type: Date },
    registrationOpensAt: { type: Date },
    registrationClosesAt: { type: Date },
    minParticipants: { type: Number, min: 1, max: 5, default: 2 },
    onInsufficientParticipants: {
      type: String,
      enum: ["cancel", "postpone"],
      default: "cancel",
    },
    scheduleStatus: {
      type: String,
      enum: [
        "DRAFT",
        "PUBLISHED",
        "REGISTRATION_OPEN",
        "REGISTRATION_CLOSED",
        "LIVE",
        "COMPLETED",
        "CANCELLED",
        "POSTPONED",
      ],
      default: "DRAFT",
    },
  },
  { timestamps: true },
);

eventSchema.index({ status: 1, createdAt: -1 });
// Scheduler worker's core query pattern: "find scheduled events sitting in
// scheduleStatus X whose trigger timestamp has arrived".
eventSchema.index({ eventType: 1, scheduleStatus: 1, registrationOpensAt: 1 });
eventSchema.index({ eventType: 1, scheduleStatus: 1, registrationClosesAt: 1 });
eventSchema.index({ eventType: 1, scheduleStatus: 1, scheduledAt: 1 });

export type EventDoc = InferSchemaType<typeof eventSchema>;
export const EventModel = model("Event", eventSchema);
