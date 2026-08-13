import { Schema, model, Types, type InferSchemaType } from "mongoose";

const participantSchema = new Schema(
  {
    participantId: { type: String, required: true },
    displayName: { type: String, required: true, trim: true, maxlength: 40 },
    tokenHash: { type: String, required: true },
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
  },
  { timestamps: true },
);

competitionSchema.index({ eventId: 1, status: 1 });
competitionSchema.index({
  eventId: 1,
  status: 1,
  "participants.deviceIdHash": 1,
});

export type CompetitionDoc = InferSchemaType<typeof competitionSchema> & {
  _id: Types.ObjectId;
};
export const CompetitionModel = model("Competition", competitionSchema);
