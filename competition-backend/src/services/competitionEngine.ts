import type { Server } from "socket.io";
import { CompetitionModel } from "../models/Competition.js";
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

// A room whose persisted phase-end timestamp is further in the past than
// this when we recover it at boot is treated as unrecoverable (the gap is
// long enough that resuming a "fair" timed round no longer means anything)
// and is abandoned instead of silently fast-forwarded through.
const MAX_RECOVERABLE_STALENESS_MS = 5 * 60 * 1000;

interface RoomTimings {
  countdownEndAt: number | null;
  roundStartAt: number | null;
  roundEndAt: number | null;
  breakEndAt: number | null;
}

const EMPTY_TIMINGS: RoomTimings = {
  countdownEndAt: null,
  roundStartAt: null,
  roundEndAt: null,
  breakEndAt: null,
};

/**
 * Owns every room's lifecycle timers and is the single place that decides
 * "what time is it in this competition". Clients only ever render countdowns
 * against the timestamps this engine hands out - they never invent their own
 * start time - which is what keeps every participant's screen in sync
 * regardless of individual network latency.
 *
 * Timers themselves live in this process's memory (fine for a single Node
 * instance, as specified for v1), but every timing decision is persisted to
 * MongoDB in the same write as the status change. That serves two purposes:
 * admin views can show "this round ends at X" without reaching into engine
 * internals, and `recoverInFlight()` can rebuild every in-flight room's
 * timer from that persisted timestamp after a restart, instead of it being
 * silently stranded until an admin notices and abandons it by hand.
 */
class CompetitionEngine {
  private io: Server | null = null;
  private timers = new Map<string, ReturnType<typeof setTimeout>>();
  private timings = new Map<string, RoomTimings>();

  attach(io: Server) {
    this.io = io;
  }

  getTimings(competitionId: string): RoomTimings {
    return this.timings.get(competitionId) ?? EMPTY_TIMINGS;
  }

  private setTimings(competitionId: string, patch: Partial<RoomTimings>) {
    this.timings.set(competitionId, { ...this.getTimings(competitionId), ...patch });
  }

  private clearTimer(competitionId: string) {
    const existing = this.timers.get(competitionId);
    if (existing) clearTimeout(existing);
    this.timers.delete(competitionId);
  }

  private schedule(competitionId: string, delayMs: number, fn: () => void) {
    this.clearTimer(competitionId);
    const timer = setTimeout(fn, Math.max(0, delayMs));
    this.timers.set(competitionId, timer);
  }

  /** Call whenever a participant joins/leaves - starts the countdown once the room is full. */
  async onParticipantCountChanged(competitionId: string): Promise<void> {
    const room = await CompetitionModel.findById(competitionId);
    if (!room) return;
    if (room.status !== "WAITING") return;

    const count = await getParticipantCount(competitionId);
    if (count >= room.maxParticipants) {
      room.status = "FULL";
      await room.save();
      await this.emitRoomState(competitionId);
      this.startCountdown(competitionId);
    } else {
      await this.emitRoomState(competitionId);
    }
  }

  private startCountdown(competitionId: string) {
    const countdownEndAt = Date.now() + COUNTDOWN_MS;
    this.setTimings(competitionId, { ...EMPTY_TIMINGS, countdownEndAt });

    void (async () => {
      await CompetitionModel.updateOne(
        { _id: competitionId },
        {
          status: "COUNTDOWN",
          countdownEndAt: new Date(countdownEndAt),
          roundStartAt: null,
          roundEndAt: null,
          breakEndAt: null,
        },
      );
      await this.emitRoomState(competitionId);
    })();

    this.schedule(competitionId, countdownEndAt - Date.now(), () => {
      void this.startRound(competitionId, 1);
    });
  }

  private async startRound(competitionId: string, roundNumber: number): Promise<void> {
    const room = await CompetitionModel.findById(competitionId);
    if (!room) return;
    // Guard against a stray/duplicate timer firing on a room that's already
    // moved on (e.g. an admin abandoned it, or recovery already advanced it).
    if (room.status !== "COUNTDOWN" && room.status !== "BREAK") return;

    const roundStartAt = Date.now();
    const roundEndAt = roundStartAt + room.roundDurationSeconds * 1000;

    room.status = "ROUND_RUNNING";
    room.currentRound = roundNumber;
    room.rounds.push({ roundNumber, startedAt: new Date(roundStartAt), scores: [] });
    room.countdownEndAt = undefined;
    room.roundStartAt = new Date(roundStartAt);
    room.roundEndAt = new Date(roundEndAt);
    room.breakEndAt = undefined;
    await room.save();

    this.setTimings(competitionId, { ...EMPTY_TIMINGS, roundStartAt, roundEndAt });
    await this.emitRoomState(competitionId);
    logger.info({ competitionId, roundNumber }, "round started");

    this.schedule(competitionId, roundEndAt - Date.now(), () => {
      void this.finishRound(competitionId, roundNumber);
    });
  }

  private async finishRound(competitionId: string, roundNumber: number): Promise<void> {
    const room = await CompetitionModel.findById(competitionId);
    if (!room) return;
    if (room.status !== "ROUND_RUNNING") return;

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
    room.roundEndAt = new Date();
    await room.save();
    await this.emitRoomState(competitionId);
    logger.info({ competitionId, roundNumber }, "round finished");

    if (roundNumber >= room.totalRounds) {
      await this.completeCompetition(competitionId);
      return;
    }

    const breakEndAt = Date.now() + room.breakDurationSeconds * 1000;
    this.setTimings(competitionId, { ...EMPTY_TIMINGS, breakEndAt });
    await CompetitionModel.updateOne(
      { _id: competitionId },
      { status: "BREAK", roundStartAt: null, roundEndAt: null, breakEndAt: new Date(breakEndAt) },
    );
    await this.emitRoomState(competitionId);

    this.schedule(competitionId, breakEndAt - Date.now(), () => {
      void this.startRound(competitionId, roundNumber + 1);
    });
  }

  private async completeCompetition(competitionId: string): Promise<void> {
    const room = await CompetitionModel.findById(competitionId);
    if (!room) return;

    const participants = await getParticipants(competitionId);
    const cumulative = await getCumulativeScores(competitionId, room.totalRounds);
    const leaderboard = buildLeaderboard(
      room.participants.map((p) => ({ participantId: p.participantId, displayName: p.displayName })),
      cumulative,
    );

    const finalResults: FinalResultEntry[] = await Promise.all(
      leaderboard.map(async (entry) => ({
        participantId: entry.participantId,
        displayName: entry.displayName,
        totalScore: entry.score,
        rank: entry.rank,
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
    room.countdownEndAt = undefined;
    room.roundStartAt = undefined;
    room.roundEndAt = undefined;
    room.breakEndAt = undefined;
    await room.save();

    this.setTimings(competitionId, EMPTY_TIMINGS);
    this.clearTimer(competitionId);

    await this.emitRoomState(competitionId);
    this.io?.to(competitionId).emit("competition:completed", { competitionId, finalResults });
    logger.info({ competitionId, winner: finalResults[0]?.displayName }, "competition completed");

    // Free the redis participant/score keys, we no longer need live state.
    void clearRoomState(competitionId);
    void participants; // participants list already folded into finalResults above
  }

  /**
   * Admin-initiated force-end for a stuck or problem room (e.g. everyone
   * disconnected, or it needs to be pulled for any other reason). Distinct
   * from `completeCompetition` - no final results are computed or ranked,
   * since an abandoned room never legitimately finished.
   */
  async abandonCompetition(competitionId: string, reason: string): Promise<boolean> {
    const room = await CompetitionModel.findById(competitionId);
    if (!room) return false;
    if (room.status === "COMPLETED" || room.status === "ABANDONED") return false;

    this.clearTimer(competitionId);
    room.status = "ABANDONED";
    room.abandonedAt = new Date();
    room.abandonReason = reason;
    room.countdownEndAt = undefined;
    room.roundStartAt = undefined;
    room.roundEndAt = undefined;
    room.breakEndAt = undefined;
    await room.save();

    this.setTimings(competitionId, EMPTY_TIMINGS);
    await this.emitRoomState(competitionId);
    this.io?.to(competitionId).emit("competition:abandoned", { competitionId, reason });
    logger.info({ competitionId, reason }, "competition abandoned by admin");

    void clearRoomState(competitionId);
    return true;
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

  /**
   * Called once at boot, after `attach(io)`. Rooms in a timed phase
   * (COUNTDOWN / ROUND_RUNNING / BREAK) have a timer living only in this
   * class's memory, so a restart would otherwise strand them there forever
   * - the room would sit on screen with a countdown that never reaches
   * zero. This rebuilds an equivalent timer from the timestamp that was
   * persisted alongside the status, or fires the transition immediately if
   * it already elapsed while the process was down. A gap too large to
   * recover fairly (see MAX_RECOVERABLE_STALENESS_MS) is abandoned instead.
   */
  async recoverInFlight(): Promise<void> {
    const inFlight = await CompetitionModel.find({
      status: { $in: ["COUNTDOWN", "ROUND_RUNNING", "ROUND_FINISHED", "BREAK"] },
    });
    if (inFlight.length === 0) return;

    logger.info({ count: inFlight.length }, "recovering in-flight competitions after restart");

    for (const room of inFlight) {
      const competitionId = String(room._id);
      try {
        if (room.status === "ROUND_FINISHED") {
          // Crashed in the narrow synchronous window between "round
          // finished" being saved and the next phase being scheduled.
          // There's no persisted timestamp to resume from - just push it
          // forward from here exactly as finishRound's tail end would have.
          if (room.currentRound >= room.totalRounds) {
            await this.completeCompetition(competitionId);
          } else {
            const breakEndAt = Date.now() + room.breakDurationSeconds * 1000;
            this.setTimings(competitionId, { ...EMPTY_TIMINGS, breakEndAt });
            await CompetitionModel.updateOne(
              { _id: competitionId },
              { status: "BREAK", breakEndAt: new Date(breakEndAt) },
            );
            await this.emitRoomState(competitionId);
            this.schedule(competitionId, breakEndAt - Date.now(), () => {
              void this.startRound(competitionId, room.currentRound + 1);
            });
          }
          continue;
        }

        const endAt =
          room.status === "COUNTDOWN"
            ? room.countdownEndAt
            : room.status === "ROUND_RUNNING"
              ? room.roundEndAt
              : room.breakEndAt; // BREAK

        if (!endAt) {
          // No timestamp to recover from at all - shouldn't happen given
          // every transition above persists one, but abandon rather than
          // guess if it ever does.
          await this.abandonCompetition(competitionId, "Recovered after restart with no phase timestamp");
          continue;
        }

        const remainingMs = endAt.getTime() - Date.now();
        if (remainingMs < -MAX_RECOVERABLE_STALENESS_MS) {
          await this.abandonCompetition(
            competitionId,
            "Server was offline too long to safely resume this competition",
          );
          continue;
        }

        this.setTimings(competitionId, {
          ...EMPTY_TIMINGS,
          countdownEndAt: room.status === "COUNTDOWN" ? endAt.getTime() : null,
          roundEndAt: room.status === "ROUND_RUNNING" ? endAt.getTime() : null,
          breakEndAt: room.status === "BREAK" ? endAt.getTime() : null,
        });

        if (room.status === "COUNTDOWN") {
          this.schedule(competitionId, remainingMs, () => void this.startRound(competitionId, 1));
        } else if (room.status === "ROUND_RUNNING") {
          this.schedule(competitionId, remainingMs, () =>
            void this.finishRound(competitionId, room.currentRound),
          );
        } else {
          this.schedule(competitionId, remainingMs, () =>
            void this.startRound(competitionId, room.currentRound + 1),
          );
        }

        logger.info(
          { competitionId, status: room.status, remainingMs: Math.max(0, remainingMs) },
          "re-armed timer for recovered competition",
        );
      } catch (err) {
        logger.error({ err, competitionId }, "failed to recover in-flight competition");
      }
    }
  }
}

export const competitionEngine = new CompetitionEngine();
