export type ExerciseMode = "reps" | "hold";

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
