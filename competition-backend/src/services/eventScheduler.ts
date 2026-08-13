import type { Server } from "socket.io";
import { EventModel } from "../models/Event.js";
import { CompetitionModel } from "../models/Competition.js";
import { logger } from "../config/logger.js";
import { competitionEngine } from "./competitionEngine.js";

const TICK_INTERVAL_MS = 5000;

/**
 * Drives every "scheduled" event's lifecycle forward:
 *
 *   PUBLISHED -> REGISTRATION_OPEN -> REGISTRATION_CLOSED -> LIVE -> COMPLETED
 *                                                          \-> CANCELLED / POSTPONED
 *
 * Deliberately a polling worker inside this same Node process (per spec:
 * no separate microservice at this stage) rather than setTimeout per event -
 * every transition is computed from stored timestamps + current server
 * time on every tick, so a process restart just picks up wherever it left
 * off instead of losing scheduled work. Each transition is a Mongo
 * compare-and-swap (findOneAndUpdate matching the expected current state),
 * which is what makes overlapping ticks - or, later, multiple instances -
 * safe: only one caller's CAS can ever succeed for a given transition.
 */
class EventScheduler {
  private timer: ReturnType<typeof setInterval> | null = null;
  private ticking = false;
  private io: Server | null = null;

  start(io: Server): void {
    if (this.timer) return;
    this.io = io;
    this.timer = setInterval(() => void this.tick(), TICK_INTERVAL_MS);
    void this.tick(); // run immediately so a restart catches up right away, not after the first interval
    logger.info({ intervalMs: TICK_INTERVAL_MS }, "event scheduler started");
  }

  stop(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }

  async tick(): Promise<void> {
    if (this.ticking) return; // don't let a slow tick overlap with the next one
    this.ticking = true;
    try {
      await this.openRegistrations();
      await this.closeRegistrations();
      await this.startScheduledCompetitions();
      await this.completeFinishedEvents();
    } catch (err) {
      logger.error({ err }, "event scheduler tick failed");
    } finally {
      this.ticking = false;
    }
  }

  private notify(eventId: string, scheduleStatus: string): void {
    // Lightweight broadcast so a join screen watching this event can refresh
    // without polling - not a per-room channel, just enough for the join
    // page's "registration opens/closes soon" state to react immediately.
    this.io?.emit("event:schedule", { eventId, scheduleStatus });
  }

  private async openRegistrations(): Promise<void> {
    const due = await EventModel.find({
      eventType: "scheduled",
      scheduleStatus: "PUBLISHED",
      registrationOpensAt: { $lte: new Date() },
    }).lean();

    for (const event of due) {
      const eventId = String(event._id);
      const updated = await EventModel.findOneAndUpdate(
        { _id: eventId, scheduleStatus: "PUBLISHED" },
        { scheduleStatus: "REGISTRATION_OPEN" },
      );
      if (updated) {
        logger.info({ eventId }, "registration opened");
        this.notify(eventId, "REGISTRATION_OPEN");
      }
    }
  }

  private async closeRegistrations(): Promise<void> {
    const due = await EventModel.find({
      eventType: "scheduled",
      scheduleStatus: "REGISTRATION_OPEN",
      registrationClosesAt: { $lte: new Date() },
    }).lean();

    for (const event of due) {
      const eventId = String(event._id);
      const updated = await EventModel.findOneAndUpdate(
        { _id: eventId, scheduleStatus: "REGISTRATION_OPEN" },
        { scheduleStatus: "REGISTRATION_CLOSED" },
      );
      if (updated) {
        logger.info({ eventId }, "registration closed");
        this.notify(eventId, "REGISTRATION_CLOSED");
      }
    }
  }

  private async startScheduledCompetitions(): Promise<void> {
    const due = await EventModel.find({
      eventType: "scheduled",
      scheduleStatus: "REGISTRATION_CLOSED",
      scheduledAt: { $lte: new Date() },
    }).lean();

    for (const event of due) {
      const eventId = String(event._id);
      // Flip to LIVE first (CAS) so a second overlapping tick can't also
      // try to start/abandon these same rooms.
      const claimed = await EventModel.findOneAndUpdate(
        { _id: eventId, scheduleStatus: "REGISTRATION_CLOSED" },
        { scheduleStatus: "LIVE" },
      );
      if (!claimed) continue;

      const rooms = await CompetitionModel.find({ eventId, status: { $in: ["WAITING", "FULL"] } });
      let startedAny = false;

      for (const room of rooms) {
        if (room.participants.length >= event.minParticipants) {
          await competitionEngine.forceStart(String(room._id));
          startedAny = true;
        } else {
          room.status = "ABANDONED";
          await room.save();
          logger.info(
            {
              eventId,
              competitionId: String(room._id),
              participants: room.participants.length,
              minParticipants: event.minParticipants,
            },
            "room had too few participants at scheduled start time, abandoning",
          );
        }
      }

      const finalStatus = startedAny ? "LIVE" : event.onInsufficientParticipants === "postpone" ? "POSTPONED" : "CANCELLED";
      await EventModel.updateOne({ _id: eventId }, { scheduleStatus: finalStatus, status: "closed" });
      logger.info({ eventId, finalStatus, roomsStarted: startedAny }, "scheduled competition start processed");
      this.notify(eventId, finalStatus);
    }
  }

  private async completeFinishedEvents(): Promise<void> {
    const inProgress = await EventModel.find({ eventType: "scheduled", scheduleStatus: "LIVE" }).lean();

    for (const event of inProgress) {
      const eventId = String(event._id);
      const openRooms = await CompetitionModel.countDocuments({
        eventId,
        status: { $nin: ["COMPLETED", "ABANDONED"] },
      });
      if (openRooms === 0) {
        const updated = await EventModel.findOneAndUpdate(
          { _id: eventId, scheduleStatus: "LIVE" },
          { scheduleStatus: "COMPLETED" },
        );
        if (updated) {
          logger.info({ eventId }, "scheduled event completed");
          this.notify(eventId, "COMPLETED");
        }
      }
    }
  }
}

export const eventScheduler = new EventScheduler();
