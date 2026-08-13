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
}

// ---- Client -> Server socket payloads ----

export interface JoinCompetitionPayload {
  eventId: string;
  displayName: string;
  // Stable per-browser id (see frontend src/lib/deviceId.ts) used to stop
  // the same person from occupying multiple of a room's 5 seats.
  deviceId: string;
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
