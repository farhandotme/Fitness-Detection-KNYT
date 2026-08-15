export type ExerciseMode = "reps" | "hold";

export type SchedulingPhase =
  | "DRAFT"
  | "PUBLISHED"
  | "REGISTRATION_OPEN"
  | "REGISTRATION_CLOSED"
  | "LIVE"
  | "COMPLETED"
  | "CANCELLED"
  | "POSTPONED";

export interface EventScheduling {
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

export type RoomVisibility = "public" | "private";

// A room in the browse/lobby list for an event - before anyone has joined
// it. participantNames is only present for public rooms; private rooms
// only reveal occupants after the correct password is supplied (see
// revealRoom in lib/competitionApi.ts).
export interface RoomListEntry {
  competitionId: string;
  roomName: string;
  visibility: RoomVisibility;
  status: CompetitionStatus;
  participantCount: number;
  maxParticipants: number;
  participantNames?: string[];
  // Parallel to participantNames - null where that participant hasn't
  // uploaded a photo (see PlayerAvatar, which generates a cartoon face
  // for those).
  participantAvatars?: (string | null)[];
  createdAt: string;
}

export interface RoomPreview {
  roomName: string;
  visibility: RoomVisibility;
  participantNames: string[];
  participantAvatars: (string | null)[];
  maxParticipants: number;
}

export interface LiveEventSummary {
  id: string;
  name: string;
  exerciseId: string;
  exerciseName: string;
  exerciseMode: ExerciseMode;
  rounds: number;
  roundDurationSeconds: number;
  breakDurationSeconds: number;
  maxParticipants: number;
  description?: string;
  activeRooms: number;
  scheduling?: EventScheduling;
  serverNow?: number;
}

export interface EventDetail {
  id: string;
  name: string;
  exerciseId: string;
  exerciseName: string;
  exerciseMode: ExerciseMode;
  rounds: number;
  roundDurationSeconds: number;
  breakDurationSeconds: number;
  maxParticipants: number;
  description?: string;
  imageUrl?: string;
  scheduling?: EventScheduling;
  serverNow?: number;
}

export interface ParticipantPublic {
  participantId: string;
  displayName: string;
  connected: boolean;
  // True for whoever created this room. See useCompetitionRoom.ts.
  isHost: boolean;
  // Cloudinary photo URL if this player uploaded one this session -
  // broadcast to every participant in the room, not just themselves. Null
  // means PlayerAvatar renders a generated cartoon face instead.
  avatarUrl: string | null;
}

export interface LeaderboardEntry {
  participantId: string;
  displayName: string;
  score: number;
  rank: number;
  avatarUrl: string | null;
}

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
  totalRounds: number;
  currentRound: number;
  roundDurationSeconds: number;
  breakDurationSeconds: number;
  participants: ParticipantPublic[];
  leaderboard: LeaderboardEntry[];
  countdownEndAt: number | null;
  roundStartAt: number | null;
  roundEndAt: number | null;
  breakEndAt: number | null;
  serverNow: number;
}

export interface FinalResultEntry {
  participantId: string;
  displayName: string;
  totalScore: number;
  rank: number;
  perRound: { round: number; score: number }[];
  avatarUrl: string | null;
}

export interface JoinedAckPayload {
  competitionId: string;
  participantId: string;
  participantToken: string;
  room: RoomStateSnapshot;
}

export interface ParticipantIdentity {
  competitionId: string;
  participantId: string;
  participantToken: string;
}

export interface SocketErrorPayload {
  code: string;
  message: string;
}
