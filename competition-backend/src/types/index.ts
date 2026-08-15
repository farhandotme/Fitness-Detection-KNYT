export type SchedulingPhase =
  | "DRAFT"
  | "PUBLISHED"
  | "REGISTRATION_OPEN"
  | "REGISTRATION_CLOSED"
  | "LIVE"
  | "COMPLETED"
  | "CANCELLED"
  | "POSTPONED";

export interface EventSchedulingPublic {
  scheduledAt: string; // ISO UTC
  scheduledEndAt?: string; // ISO UTC - optional, display-only
  registrationOpensAt: string;
  registrationClosesAt: string;
  timezone: string;
  minParticipants: number;
  onInsufficientParticipants: "cancel" | "postpone";
  phase: SchedulingPhase;
}

export interface EventPhasePayload {
  eventId: string;
  phase: SchedulingPhase;
  serverNow: number;
  scheduledAt: string | null;
  registrationOpensAt: string | null;
  registrationClosesAt: string | null;
}

export type CompetitionStatus =
  | "WAITING"
  | "FULL"
  | "COUNTDOWN"
  | "ROUND_RUNNING"
  | "ROUND_FINISHED"
  | "BREAK"
  | "COMPLETED"
  | "ABANDONED";

export type ExerciseMode = "reps" | "hold";

export interface ParticipantPublic {
  participantId: string;
  displayName: string;
  connected: boolean;
  // Whether this participant created the room. See models/Competition.ts.
  isHost: boolean;
  // Cloudinary URL if this player uploaded a photo this session, otherwise
  // null - every other participant sees this same URL (see
  // services/avatarService.ts). Never the Cloudinary publicId, only the
  // owning client keeps that (needed to delete it later).
  avatarUrl: string | null;
}

export interface LeaderboardEntry {
  participantId: string;
  displayName: string;
  score: number;
  rank: number;
  avatarUrl: string | null;
}

export type RoomVisibility = "public" | "private";

export interface RoomStateSnapshot {
  competitionId: string;
  eventId: string;
  eventName: string;
  roomName: string;
  visibility: RoomVisibility;
  exerciseId: string;
  exerciseMode: ExerciseMode;
  status: CompetitionStatus;
  maxParticipants: number;
  // Snapshot of the event's minParticipants at room-creation time - the
  // room's host can call room:start once this many seats are filled,
  // instead of waiting for maxParticipants. See models/Competition.ts.
  minParticipants: number;
  totalRounds: number;
  currentRound: number;
  roundDurationSeconds: number;
  breakDurationSeconds: number;
  participants: ParticipantPublic[];
  leaderboard: LeaderboardEntry[];
  countdownEndAt: number | null; // epoch ms - server is source of truth for time
  roundStartAt: number | null;
  roundEndAt: number | null;
  breakEndAt: number | null;
  serverNow: number; // epoch ms, lets the client correct for clock drift
}

export interface FinalResultEntry {
  participantId: string;
  displayName: string;
  totalScore: number;
  rank: number;
  perRound: { round: number; score: number }[];
  avatarUrl: string | null;
}

// A room in the browse/lobby list for an event - before anyone has joined
// it. Participant names are only included for public rooms; private rooms
// only reveal who's inside after the correct password is supplied (see
// POST /api/events/:eventId/rooms/:competitionId/reveal).
export interface RoomListEntry {
  competitionId: string;
  roomName: string;
  visibility: RoomVisibility;
  status: CompetitionStatus;
  participantCount: number;
  maxParticipants: number;
  participantNames?: string[];
  // Parallel to participantNames (same index = same person) - null entries
  // mean that participant hasn't uploaded a photo, so the frontend shows a
  // generated avatar for them instead. Public rooms only, same as names.
  participantAvatars?: (string | null)[];
  createdAt: string;
}

// ---- Client -> Server socket payloads ----

export interface CreateRoomPayload {
  eventId: string;
  roomName: string;
  visibility: RoomVisibility;
  password?: string;
  displayName: string;
  // Stable per-browser id (see frontend src/lib/deviceId.ts) used to stop
  // the same person from occupying multiple of a room's seats.
  deviceId: string;
  // Cloudinary URL/publicId from a completed signed upload (see
  // POST /api/avatars/signature) - both optional, a player can always skip
  // uploading and get a generated avatar instead.
  avatarUrl?: string;
  avatarPublicId?: string;
}

export interface JoinRoomPayload {
  competitionId: string;
  displayName: string;
  password?: string;
  deviceId: string;
  avatarUrl?: string;
  avatarPublicId?: string;
}

export interface ReconnectPayload {
  competitionId: string;
  participantId: string;
  participantToken: string;
}

export interface ScoreUpdatePayload {
  competitionId: string;
  participantId: string;
  participantToken: string;
  round: number;
  score: number; // cumulative score for the current round (e.g. rep_count or hold_seconds)
  status?: "RUNNING" | "PAUSED" | "DONE";
}

export interface LeaveCompetitionPayload {
  competitionId: string;
  participantId: string;
  participantToken: string;
}

// ---- Server -> Client socket payloads ----

export interface JoinedAckPayload {
  competitionId: string;
  participantId: string;
  participantToken: string;
  room: RoomStateSnapshot;
}

export interface ErrorPayload {
  code: string;
  message: string;
}

export interface CompetitionCompletedPayload {
  competitionId: string;
  finalResults: FinalResultEntry[];
}
