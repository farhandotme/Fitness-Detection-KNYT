import { redis } from "../config/redis.js";
import type { LeaderboardEntry } from "../types/index.js";

// Redis is used only for data that changes constantly during a live round
// (membership, live scores). Permanent history lives in MongoDB - see
// models/Competition.ts. Keys expire a few hours after the room is created
// so abandoned rooms don't accumulate forever.
const ROOM_TTL_SECONDS = 60 * 60 * 6;

const participantsKey = (competitionId: string) => `comp:${competitionId}:participants`;
const scoresKey = (competitionId: string, round: number) => `comp:${competitionId}:scores:${round}`;
const roundSetKey = (competitionId: string) => `comp:${competitionId}:rounds`; // tracks which round keys exist

interface StoredParticipant {
  displayName: string;
  connected: boolean;
}

export async function joinRoomAtomic(
  competitionId: string,
  maxParticipants: number,
  participantId: string,
  displayName: string,
): Promise<"joined" | "full" | "already_member"> {
  const key = participantsKey(competitionId);
  const payload: StoredParticipant = { displayName, connected: true };
  const result = await redis.joinRoom(key, maxParticipants, participantId, JSON.stringify(payload));
  await redis.expire(key, ROOM_TTL_SECONDS);
  if (result === 0) return "full";
  if (result === 2) return "already_member";
  return "joined";
}

export async function setParticipantConnected(
  competitionId: string,
  participantId: string,
  connected: boolean,
): Promise<void> {
  const key = participantsKey(competitionId);
  const raw = await redis.hget(key, participantId);
  if (!raw) return;
  const parsed: StoredParticipant = JSON.parse(raw);
  parsed.connected = connected;
  await redis.hset(key, participantId, JSON.stringify(parsed));
}

export async function isParticipantConnected(
  competitionId: string,
  participantId: string,
): Promise<boolean> {
  const raw = await redis.hget(participantsKey(competitionId), participantId);
  if (!raw) return false;
  const parsed: StoredParticipant = JSON.parse(raw);
  return parsed.connected;
}

export async function removeParticipant(competitionId: string, participantId: string): Promise<void> {
  await redis.hdel(participantsKey(competitionId), participantId);
}

export async function getParticipantCount(competitionId: string): Promise<number> {
  return redis.hlen(participantsKey(competitionId));
}

export async function getParticipants(
  competitionId: string,
): Promise<{ participantId: string; displayName: string; connected: boolean }[]> {
  const all = await redis.hgetall(participantsKey(competitionId));
  return Object.entries(all).map(([participantId, raw]) => {
    const parsed: StoredParticipant = JSON.parse(raw);
    return { participantId, displayName: parsed.displayName, connected: parsed.connected };
  });
}

export async function hasParticipant(competitionId: string, participantId: string): Promise<boolean> {
  return (await redis.hexists(participantsKey(competitionId), participantId)) === 1;
}

export async function setScore(competitionId: string, round: number, participantId: string, score: number): Promise<void> {
  const key = scoresKey(competitionId, round);
  await redis.hset(key, participantId, score);
  await redis.expire(key, ROOM_TTL_SECONDS);
  await redis.sadd(roundSetKey(competitionId), String(round));
  await redis.expire(roundSetKey(competitionId), ROOM_TTL_SECONDS);
}

export async function getRoundScores(competitionId: string, round: number): Promise<Record<string, number>> {
  const raw = await redis.hgetall(scoresKey(competitionId, round));
  const out: Record<string, number> = {};
  for (const [participantId, value] of Object.entries(raw)) {
    out[participantId] = Number(value) || 0;
  }
  return out;
}

/** Cumulative score across every round played so far, per participant. */
export async function getCumulativeScores(competitionId: string, uptoRound: number): Promise<Record<string, number>> {
  const totals: Record<string, number> = {};
  for (let round = 1; round <= uptoRound; round += 1) {
    const roundScores = await getRoundScores(competitionId, round);
    for (const [participantId, score] of Object.entries(roundScores)) {
      totals[participantId] = (totals[participantId] ?? 0) + score;
    }
  }
  return totals;
}

export function buildLeaderboard(
  participants: { participantId: string; displayName: string }[],
  scores: Record<string, number>,
): LeaderboardEntry[] {
  const entries = participants.map((p) => ({
    participantId: p.participantId,
    displayName: p.displayName,
    score: scores[p.participantId] ?? 0,
  }));
  entries.sort((a, b) => b.score - a.score);
  return entries.map((entry, index) => ({ ...entry, rank: index + 1 }));
}

export async function clearRoomState(competitionId: string): Promise<void> {
  const roundsRaw = await redis.smembers(roundSetKey(competitionId));
  const keysToDelete = [
    participantsKey(competitionId),
    roundSetKey(competitionId),
    ...roundsRaw.map((round) => scoresKey(competitionId, Number(round))),
  ];
  if (keysToDelete.length > 0) await redis.del(...keysToDelete);
}
