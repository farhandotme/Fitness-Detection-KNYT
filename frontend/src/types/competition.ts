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
  imageUrl: string | undefined;
  imageUrl: any;
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
  scheduling?: EventScheduling;
  serverNow?: number;
}

export interface ParticipantPublic {
  participantId: string;
  displayName: string;
  connected: boolean;
}

export interface LeaderboardEntry {
  participantId: string;
  displayName: string;
  score: number;
  rank: number;
}

export interface RoomStateSnapshot {
  competitionId: string;
  eventId: string;
  eventName: string;
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
