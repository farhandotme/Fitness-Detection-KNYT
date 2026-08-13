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
    roundDurationSeconds: { type: Number, required: true, min: 10, max: 600, default: 60 },
    breakDurationSeconds: { type: Number, required: true, min: 5, max: 300, default: 15 },
    maxParticipants: { type: Number, required: true, min: 2, max: 5, default: 5 },
    status: { type: String, enum: ["draft", "live", "closed"], default: "live" },
    description: { type: String, default: "" },
  },
  { timestamps: true },
);

eventSchema.index({ status: 1, createdAt: -1 });

export type EventDoc = InferSchemaType<typeof eventSchema>;
export const EventModel = model("Event", eventSchema);
