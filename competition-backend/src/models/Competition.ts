import { Schema, model, Types, type InferSchemaType } from "mongoose";

const participantSchema = new Schema(
  {
    participantId: { type: String, required: true },
    displayName: { type: String, required: true, trim: true, maxlength: 40 },
    tokenHash: { type: String, required: true },
    // Hash of a per-browser device id the frontend generates and persists in
    // localStorage (see frontend src/lib/deviceId.ts). Lets the backend
    // recognize "this is the same person trying to join again" even without
    // login, and reattach them to their existing seat instead of handing out
    // a second one - see competitionService.joinEvent.
    deviceIdHash: { type: String, required: false },
    joinedAt: { type: Date, default: () => new Date() },
    connected: { type: Boolean, default: true },
  },
  { _id: false },
);

const roundScoreSchema = new Schema(
  {
    participantId: { type: String, required: true },
    score: { type: Number, required: true, default: 0 },
  },
  { _id: false },
);

const roundSchema = new Schema(
  {
    roundNumber: { type: Number, required: true },
    startedAt: { type: Date },
    endedAt: { type: Date },
    scores: { type: [roundScoreSchema], default: [] },
  },
  { _id: false },
);

const finalResultSchema = new Schema(
  {
    participantId: { type: String, required: true },
    displayName: { type: String, required: true },
    totalScore: { type: Number, required: true },
    rank: { type: Number, required: true },
  },
  { _id: false },
);

const competitionSchema = new Schema(
  {
    eventId: { type: Schema.Types.ObjectId, ref: "Event", required: true },
    eventName: { type: String, required: true },
    exerciseId: { type: String, required: true },
    exerciseMode: { type: String, enum: ["reps", "hold"], required: true },
    roomCode: { type: String, required: true, unique: true },
    status: {
      type: String,
      enum: [
        "WAITING",
        "FULL",
        "COUNTDOWN",
        "ROUND_RUNNING",
        "ROUND_FINISHED",
        "BREAK",
        "COMPLETED",
        "ABANDONED",
      ],
      default: "WAITING",
    },
    maxParticipants: { type: Number, required: true },
    totalRounds: { type: Number, required: true },
    roundDurationSeconds: { type: Number, required: true },
    breakDurationSeconds: { type: Number, required: true },
    currentRound: { type: Number, default: 0 },
    participants: { type: [participantSchema], default: [] },
    rounds: { type: [roundSchema], default: [] },
    finalResults: { type: [finalResultSchema], default: [] },
    completedAt: { type: Date },

    // Persisted mirror of competitionEngine's in-memory phase timings.
    // While the process is up, the engine's own Map is what's actually
    // driving timers - these fields exist so (a) admin views can show
    // "this room's break ends at X" without reaching into engine internals,
    // and (b) `competitionEngine.recoverInFlight()` can re-arm a timer for
    // the remaining time (or fire the overdue transition immediately) after
    // a restart, instead of every in-progress room being stranded forever.
    countdownEndAt: { type: Date },
    roundStartAt: { type: Date },
    roundEndAt: { type: Date },
    breakEndAt: { type: Date },

    // Set when an admin force-ends a stuck/problem room via
    // POST /api/admin/competitions/:id/abandon.
    abandonedAt: { type: Date },
    abandonReason: { type: String },
  },
  { timestamps: true },
);

competitionSchema.index({ eventId: 1, status: 1 });
// Used to look up "does this device already have an active seat in this event"
// so the same person can't grab multiple of a room's 5 slots (competitionService.joinEvent).
competitionSchema.index({
  eventId: 1,
  status: 1,
  "participants.deviceIdHash": 1,
});
// Admin room-monitor / event-detail listings: newest first, optionally by status.
competitionSchema.index({ status: 1, createdAt: -1 });

export type CompetitionDoc = InferSchemaType<typeof competitionSchema> & {
  _id: Types.ObjectId;
};
export const CompetitionModel = model("Competition", competitionSchema);
