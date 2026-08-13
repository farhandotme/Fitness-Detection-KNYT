import type { Server } from "socket.io";
import { EventModel, type EventDoc } from "../models/Event.js";
import { CompetitionModel } from "../models/Competition.js";
import { redis } from "../config/redis.js";
import { env } from "../config/env.js";
import { logger } from "../config/logger.js";
import { competitionEngine } from "./competitionEngine.js";
import { getParticipantCount, clearRoomState } from "./redisState.js";
import type { SchedulingPhase } from "../types/index.js";

type SchedulingDoc = NonNullable<EventDoc["scheduling"]>;

const TERMINAL_PHASES: SchedulingPhase[] = [
  "COMPLETED",
  "CANCELLED",
  "POSTPONED",
];

/**
 * Drives every *scheduled* event's lifecycle forward. This is the piece the
 * scheduling add-on spec calls "the scheduler" - the important property is
 * that it is entirely stateless between ticks: every tick re-derives "what
 * phase should this event be in right now?" purely from the timestamps
 * stored in MongoDB and the current server clock, so a restart at any point
 * (mid-registration-window, seconds before a start time, whatever) picks up
 * exactly where it should with no separate recovery path to write.
 *
 * Timers (competition rounds, breaks, countdowns) still live in
 * competitionEngine's in-memory setTimeouts once a room is actually
 * running, same as before - this worker only owns the *pre-live* part of a
 * scheduled event's lifecycle (draft -> published -> registration ->
 * live/cancelled).
 */
class EventSchedulerService {
  private io: Server | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;
  private ticking = false;

  attach(io: Server) {
    this.io = io;
  }

  start(): void {
    if (this.timer) return;
    this.timer = setInterval(() => void this.tick(), env.SCHEDULER_TICK_MS);
    // Run once immediately on boot rather than waiting a full interval -
    // this is exactly the "server restarted at 6:59, what should be
    // happening right now?" case the spec calls out.
    void this.tick();
    logger.info(
      { intervalMs: env.SCHEDULER_TICK_MS },
      "event scheduler started",
    );
  }

  stop(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }

  private async tick(): Promise<void> {
    // A slow previous tick (e.g. a temporary Mongo hiccup) should never
    // stack a second one on top of it.
    if (this.ticking) return;
    this.ticking = true;
    try {
      const now = Date.now();
      const events = await EventModel.find({
        status: { $ne: "closed" },
        "scheduling.scheduledAt": { $exists: true },
        "scheduling.phase": { $nin: TERMINAL_PHASES },
      }).lean();

      for (const event of events) {
        await this.processEvent(event, now).catch((err) => {
          logger.error(
            { err, eventId: event._id },
            "scheduler: failed to process event",
          );
        });
      }
    } catch (err) {
      logger.error({ err }, "scheduler tick failed");
    } finally {
      this.ticking = false;
    }
  }

  /** Pure function of (schedule, now) -> phase, ignoring participant counts. */
  private derivePrelivePhase(
    scheduling: SchedulingDoc,
    now: number,
  ): SchedulingPhase {
    if (now < scheduling.registrationOpensAt.getTime()) return "PUBLISHED";
    if (now < scheduling.registrationClosesAt.getTime())
      return "REGISTRATION_OPEN";
    if (now < scheduling.scheduledAt.getTime()) return "REGISTRATION_CLOSED";
    return "LIVE";
  }

  private async processEvent(
    event: EventDoc & { _id: unknown },
    now: number,
  ): Promise<void> {
    const scheduling = event.scheduling;
    if (!scheduling) return;
    const eventId = String(event._id);

    const currentPhase = (scheduling.phase ?? "DRAFT") as SchedulingPhase;

    if (currentPhase === "LIVE") {
      // Nothing left for this worker to *decide* - just notice once every
      // room has finished, so the event can be marked COMPLETED too.
      await this.checkForCompletion(eventId, currentPhase);
      return;
    }

    const desiredPhase = this.derivePrelivePhase(scheduling, now);
    if (desiredPhase === currentPhase) return;

    // Idempotency guard: if two ticks (or, in a future multi-instance
    // deployment, two processes) both decide "this event should move to
    // REGISTRATION_OPEN" at once, only one should actually perform the
    // transition/side-effects. A short NX lock is enough since a tick that
    // loses the race simply does nothing and the next tick re-evaluates
    // from scratch anyway.
    const lockKey = `sched:lock:${eventId}:${desiredPhase}`;
    const acquired = await redis.set(
      lockKey,
      "1",
      "PX",
      env.SCHEDULER_TICK_MS * 4,
      "NX",
    );
    if (acquired !== "OK") return;

    if (desiredPhase === "LIVE") {
      await this.goLive(eventId, event, scheduling);
    } else {
      await EventModel.updateOne(
        { _id: eventId },
        { "scheduling.phase": desiredPhase },
      );
      this.broadcastPhase(eventId, desiredPhase, scheduling);
      logger.info(
        { eventId, from: currentPhase, to: desiredPhase },
        "event scheduling phase changed",
      );
    }
  }

  /**
   * The scheduled start time has arrived. Count who actually joined across
   * every room this event created during its registration window, then
   * either start all of them together or cancel/postpone the whole event -
   * never hardcoded, driven by `scheduling.minParticipants` /
   * `onInsufficientParticipants` (see models/Event.ts).
   */
  private async goLive(
    eventId: string,
    event: EventDoc,
    scheduling: SchedulingDoc,
  ): Promise<void> {
    const rooms = await CompetitionModel.find({
      eventId,
      status: { $in: ["WAITING", "FULL"] },
    });

    let totalParticipants = 0;
    for (const room of rooms) {
      totalParticipants += await getParticipantCount(String(room._id));
    }

    if (rooms.length === 0 || totalParticipants < scheduling.minParticipants) {
      const failPhase: SchedulingPhase =
        scheduling.onInsufficientParticipants === "postpone"
          ? "POSTPONED"
          : "CANCELLED";
      await EventModel.updateOne(
        { _id: eventId },
        { "scheduling.phase": failPhase },
      );

      for (const room of rooms) {
        const competitionId = String(room._id);
        await CompetitionModel.updateOne(
          { _id: competitionId },
          { status: "ABANDONED" },
        );
        await clearRoomState(competitionId);
        this.io?.to(competitionId).emit("competition:cancelled", {
          competitionId,
          reason: `Not enough participants joined before the start time (minimum ${scheduling.minParticipants}).`,
        });
      }

      this.broadcastPhase(eventId, failPhase, scheduling);
      logger.info(
        {
          eventId,
          totalParticipants,
          minParticipants: scheduling.minParticipants,
          failPhase,
        },
        "scheduled event did not reach minimum participants",
      );
      return;
    }

    await EventModel.updateOne(
      { _id: eventId },
      { "scheduling.phase": "LIVE" },
    );
    this.broadcastPhase(eventId, "LIVE", scheduling);

    // Every room this event spun up during registration (see "Multiple
    // Rooms" in the spec - a full room during registration silently starts
    // a fresh WAITING room for the next joiners) starts together, at the
    // same server timestamp.
    for (const room of rooms) {
      await competitionEngine.triggerScheduledStart(String(room._id));
    }

    logger.info(
      { eventId, rooms: rooms.length, totalParticipants },
      "scheduled event went live",
    );
  }

  private async checkForCompletion(
    eventId: string,
    currentPhase: SchedulingPhase,
  ): Promise<void> {
    const [openRooms, everCreated] = await Promise.all([
      CompetitionModel.countDocuments({
        eventId,
        status: { $nin: ["COMPLETED", "ABANDONED"] },
      }),
      CompetitionModel.countDocuments({ eventId }),
    ]);
    if (everCreated === 0 || openRooms > 0) return;

    const result = await EventModel.findOneAndUpdate(
      { _id: eventId, "scheduling.phase": currentPhase },
      { "scheduling.phase": "COMPLETED" },
      { new: true },
    );
    if (result) {
      this.broadcastPhase(eventId, "COMPLETED");
      logger.info({ eventId }, "scheduled event completed");
    }
  }

  private broadcastPhase(
    eventId: string,
    phase: SchedulingPhase,
    scheduling?: SchedulingDoc,
  ): void {
    this.io?.to(`event:${eventId}`).emit("event:phase", {
      eventId,
      phase,
      serverNow: Date.now(),
      scheduledAt: scheduling?.scheduledAt.toISOString() ?? null,
      registrationOpensAt:
        scheduling?.registrationOpensAt.toISOString() ?? null,
      registrationClosesAt:
        scheduling?.registrationClosesAt.toISOString() ?? null,
    });
  }
}

export const eventScheduler = new EventSchedulerService();
