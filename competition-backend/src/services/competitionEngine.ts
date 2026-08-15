import type { Server } from "socket.io";
import { CompetitionModel } from "../models/Competition.js";
import { EventModel } from "../models/Event.js";
import { logger } from "../config/logger.js";
import {
  buildLeaderboard,
  clearRoomState,
  getCumulativeScores,
  getParticipantCount,
  getParticipants,
  getRoundScores,
} from "./redisState.js";
import type { FinalResultEntry, RoomStateSnapshot } from "../types/index.js";

const COUNTDOWN_MS = 5000;

interface RoomTimings {
  countdownEndAt: number | null;
  roundStartAt: number | null;
  roundEndAt: number | null;
  breakEndAt: number | null;
}

/**
 * Owns every room's lifecycle timers and is the single place that decides
 * "what time is it in this competition". Clients only ever render countdowns
 * against the timestamps this engine hands out - they never invent their own
 * start time - which is what keeps every participant's screen in sync
 * regardless of individual network latency.
 *
 * v1 scope: timers live in this process's memory. That's fine for a single
 * Node instance (as specified for the first version). Scaling to multiple
 * competition-backend instances later would move this to a shared scheduler
 * (e.g. Redis-backed job queue) keyed by competitionId so any instance can
 * pick up the next transition.
 */
class CompetitionEngine {
  private io: Server | null = null;
  private timers = new Map<string, ReturnType<typeof setTimeout>>();
  private timings = new Map<string, RoomTimings>();

  attach(io: Server) {
    this.io = io;
  }

  getTimings(competitionId: string): RoomTimings {
    return (
      this.timings.get(competitionId) ?? {
        countdownEndAt: null,
        roundStartAt: null,
        roundEndAt: null,
        breakEndAt: null,
      }
    );
  }

  private setTimings(competitionId: string, patch: Partial<RoomTimings>) {
    this.timings.set(competitionId, { ...this.getTimings(competitionId), ...patch });
  }

  private clearTimer(competitionId: string) {
    const existing = this.timers.get(competitionId);
    if (existing) clearTimeout(existing);
    this.timers.delete(competitionId);
  }

  /**
   * Public teardown for a room that's being destroyed outright (host left
   * for good - see destroyRoomAsHostLeft in competitionService.ts). Stops
   * whatever lifecycle timer was pending (countdown/round/break) so it
   * can't fire against a room that's now ABANDONED, and drops the cached
   * timings so a stale countdown/round clock never gets served again.
   */
  cancelRoom(competitionId: string): void {
    this.clearTimer(competitionId);
    this.timings.delete(competitionId);
  }

  private schedule(competitionId: string, delayMs: number, fn: () => void) {
    this.clearTimer(competitionId);
    const timer = setTimeout(fn, Math.max(0, delayMs));
    this.timers.set(competitionId, timer);
  }

  /**
   * Call whenever a participant joins/leaves - starts the countdown once
   * the room is full.
   *
   * Exception: a room that belongs to a *scheduled* event (see
   * services/eventScheduler.ts) which hasn't reached its start time yet is
   * only marked FULL here, never auto-started - the scheduler is what
   * triggers the countdown for every room under that event at once,
   * precisely at `scheduledAt`, regardless of which rooms filled early.
   */
  async onParticipantCountChanged(competitionId: string): Promise<void> {
    const room = await CompetitionModel.findById(competitionId);
    if (!room) return;
    if (room.status !== "WAITING") return;

    const count = await getParticipantCount(competitionId);
    if (count >= room.maxParticipants) {
      room.status = "FULL";
      await room.save();
      await this.emitRoomState(competitionId);

      const event = await EventModel.findById(room.eventId).lean();
      const isPendingScheduledEvent = Boolean(
        event?.scheduling && event.scheduling.phase !== "LIVE" && event.scheduling.phase !== "COMPLETED",
      );
      if (!isPendingScheduledEvent) {
        this.startCountdown(competitionId);
      }
    } else {
      await this.emitRoomState(competitionId);
    }
  }

  /**
   * Public entry point for services/eventScheduler.ts: force a WAITING/FULL
   * room into its countdown regardless of whether it ever filled, once its
   * event's scheduled start time has arrived and the minimum-participants
   * check has passed.
   */
  async triggerScheduledStart(competitionId: string): Promise<void> {
    const room = await CompetitionModel.findById(competitionId);
    if (!room) return;
    if (room.status !== "WAITING" && room.status !== "FULL") return; // already progressed past this point

    room.status = "FULL";
    await room.save();
    await this.emitRoomState(competitionId);
    this.startCountdown(competitionId);
  }

  private startCountdown(competitionId: string) {
    const countdownEndAt = Date.now() + COUNTDOWN_MS;
    this.setTimings(competitionId, { countdownEndAt, roundStartAt: null, roundEndAt: null, breakEndAt: null });

    void (async () => {
      await CompetitionModel.updateOne({ _id: competitionId }, { status: "COUNTDOWN" });
      await this.emitRoomState(competitionId);
    })();

    this.schedule(competitionId, COUNTDOWN_MS, () => {
      void this.startRound(competitionId, 1);
    });
  }

  private async startRound(competitionId: string, roundNumber: number): Promise<void> {
    const room = await CompetitionModel.findById(competitionId);
    if (!room) return;

    const roundStartAt = Date.now();
    const roundEndAt = roundStartAt + room.roundDurationSeconds * 1000;

    room.status = "ROUND_RUNNING";
    room.currentRound = roundNumber;
    room.rounds.push({ roundNumber, startedAt: new Date(roundStartAt), scores: [] });
    await room.save();

    this.setTimings(competitionId, { countdownEndAt: null, roundStartAt, roundEndAt, breakEndAt: null });
    await this.emitRoomState(competitionId);
    logger.info({ competitionId, roundNumber }, "round started");

    this.schedule(competitionId, room.roundDurationSeconds * 1000, () => {
      void this.finishRound(competitionId, roundNumber);
    });
  }

  private async finishRound(competitionId: string, roundNumber: number): Promise<void> {
    const room = await CompetitionModel.findById(competitionId);
    if (!room) return;

    const roundScores = await getRoundScores(competitionId, roundNumber);
    const roundEntry = room.rounds.find((r) => r.roundNumber === roundNumber);
    if (roundEntry) {
      roundEntry.endedAt = new Date();
      // Mongoose subdocument arrays aren't assignable from a plain array
      // (that's a real type error, not just tsconfig strictness) - clear
      // and push instead, which is how Mongoose expects this to be done.
      roundEntry.scores.splice(0, roundEntry.scores.length);
      for (const [participantId, score] of Object.entries(roundScores)) {
        roundEntry.scores.push({ participantId, score });
      }
    }
    room.status = "ROUND_FINISHED";
    await room.save();
    await this.emitRoomState(competitionId);
    logger.info({ competitionId, roundNumber }, "round finished");

    if (roundNumber >= room.totalRounds) {
      await this.completeCompetition(competitionId);
      return;
    }

    const breakEndAt = Date.now() + room.breakDurationSeconds * 1000;
    this.setTimings(competitionId, { roundStartAt: null, roundEndAt: null, breakEndAt });
    await CompetitionModel.updateOne({ _id: competitionId }, { status: "BREAK" });
    await this.emitRoomState(competitionId);

    this.schedule(competitionId, room.breakDurationSeconds * 1000, () => {
      void this.startRound(competitionId, roundNumber + 1);
    });
  }

  private async completeCompetition(competitionId: string): Promise<void> {
    const room = await CompetitionModel.findById(competitionId);
    if (!room) return;

    const participants = await getParticipants(competitionId);
    const cumulative = await getCumulativeScores(competitionId, room.totalRounds);
    const leaderboard = buildLeaderboard(
      room.participants.map((p) => ({
        participantId: p.participantId,
        displayName: p.displayName,
        avatarUrl: p.avatarUrl ?? null,
      })),
      cumulative,
    );

    const finalResults: FinalResultEntry[] = await Promise.all(
      leaderboard.map(async (entry) => ({
        participantId: entry.participantId,
        displayName: entry.displayName,
        totalScore: entry.score,
        rank: entry.rank,
        avatarUrl: entry.avatarUrl,
        perRound: await this.perRoundScores(competitionId, entry.participantId, room.totalRounds),
      })),
    );

    room.status = "COMPLETED";
    room.finalResults.splice(0, room.finalResults.length);
    for (const f of finalResults) {
      room.finalResults.push({
        participantId: f.participantId,
        displayName: f.displayName,
        totalScore: f.totalScore,
        rank: f.rank,
      });
    }
    room.completedAt = new Date();
    await room.save();

    this.setTimings(competitionId, { countdownEndAt: null, roundStartAt: null, roundEndAt: null, breakEndAt: null });
    this.clearTimer(competitionId);

    await this.emitRoomState(competitionId);
    this.io?.to(competitionId).emit("competition:completed", { competitionId, finalResults });
    logger.info({ competitionId, winner: finalResults[0]?.displayName }, "competition completed");

    // Free the redis participant/score keys, we no longer need live state.
    void clearRoomState(competitionId);
    void participants; // participants list already folded into finalResults above
  }

  private async perRoundScores(
    competitionId: string,
    participantId: string,
    totalRounds: number,
  ): Promise<{ round: number; score: number }[]> {
    const out: { round: number; score: number }[] = [];
    for (let round = 1; round <= totalRounds; round += 1) {
      const scores = await getRoundScores(competitionId, round);
      out.push({ round, score: scores[participantId] ?? 0 });
    }
    return out;
  }

  async broadcastLeaderboard(competitionId: string): Promise<void> {
    await this.emitRoomState(competitionId);
  }

  private async emitRoomState(competitionId: string): Promise<void> {
    if (!this.io) return;
    const { getRoomSnapshot } = await import("./competitionService.js");
    const snapshot: RoomStateSnapshot | null = await getRoomSnapshot(competitionId);
    if (!snapshot) return;
    this.io.to(competitionId).emit("room:state", snapshot);
  }
}

export const competitionEngine = new CompetitionEngine();
