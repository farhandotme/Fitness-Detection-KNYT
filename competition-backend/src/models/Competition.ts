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
    // a second one - see services/roomService.ts.
    deviceIdHash: { type: String, required: false },
    joinedAt: { type: Date, default: () => new Date() },
    connected: { type: Boolean, default: true },
    // True only for the participant who created this room (services/roomService.ts
    // createRoom -> seatNewParticipant). The host "owns" the room: if they
    // leave or disconnect for good, the whole room is destroyed rather than
    // just freeing their seat - see destroyRoomAsHostLeft in
    // services/competitionService.ts.
    isHost: { type: Boolean, default: false },
    // Optional profile photo for this session only - uploaded straight to
    // Cloudinary by the frontend (see services/avatarService.ts), we only
    // ever store the resulting URL/publicId here. avatarPublicId is what
    // lets the server delete the actual image once the seat is freed
    // (competitionService.ts) - never exposed to other participants,
    // avatarUrl is the only one broadcast in room:state.
    avatarUrl: { type: String, required: false, maxlength: 500 },
    avatarPublicId: { type: String, required: false, maxlength: 300 },
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
    // Rooms are created by participants themselves (not auto-matchmade) -
    // see services/roomService.ts. roomName is what they called it, e.g.
    // "Me & Rahul"; visibility/passwordHash control who can join it.
    roomName: { type: String, required: true, trim: true, maxlength: 60 },
    visibility: {
      type: String,
      enum: ["public", "private"],
      default: "public",
    },
    // Only set for private rooms - bcrypt hash, never the raw password.
    passwordHash: { type: String, required: false },
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
    // Snapshot of the event's minParticipants at room-creation time (see
    // models/Event.ts) - how many seats this specific room needs filled
    // before its host can start it early via room:start. Copied rather
    // than looked up live so a later admin edit to the event doesn't
    // retroactively change the rules for a room that's already mid-fill.
    minParticipants: { type: Number, required: true, default: 2 },
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
// Used to look up "does this device already have an active seat in this event"
// so the same person can't grab multiple of a room's 5 slots (services/roomService.ts).
competitionSchema.index({
  eventId: 1,
  status: 1,
  "participants.deviceIdHash": 1,
});

export type CompetitionDoc = InferSchemaType<typeof competitionSchema> & {
  _id: Types.ObjectId;
};
export const CompetitionModel = model("Competition", competitionSchema);
