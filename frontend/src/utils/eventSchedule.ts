import type { EventScheduling } from "@/types/competition";
import {
  formatCountdown,
  formatInTimeZone,
  formatTimeOnlyInTimeZone,
} from "./formatTime";

export interface ScheduleStatus {
  /** Short badge text, e.g. "Starts in 2h 10m" */
  badge: string;
  /** Longer status line shown on the join screen. */
  message: string;
  /** Whether the join button should be enabled right now. */
  canJoin: boolean;
  /** Whether this event is in a state worth showing at all (not e.g. long-completed). */
  tone: "upcoming" | "open" | "closed" | "live" | "ended" | "cancelled";
}

export function getScheduleStatus(scheduling: EventScheduling, now: number): ScheduleStatus {
  const startLabel = scheduling.scheduledEndAt
    ? `${formatInTimeZone(scheduling.scheduledAt, scheduling.timezone)} - ${formatTimeOnlyInTimeZone(scheduling.scheduledEndAt, scheduling.timezone)}`
    : formatInTimeZone(scheduling.scheduledAt, scheduling.timezone);
  const opensAt = new Date(scheduling.registrationOpensAt).getTime();
  const closesAt = new Date(scheduling.registrationClosesAt).getTime();
  const startsAt = new Date(scheduling.scheduledAt).getTime();

  switch (scheduling.phase) {
    case "DRAFT":
    case "PUBLISHED":
      return {
        badge: `Registration opens in ${formatCountdown(opensAt - now)}`,
        message: `Starts ${startLabel}. Registration opens in ${formatCountdown(opensAt - now)}.`,
        canJoin: false,
        tone: "upcoming",
      };
    case "REGISTRATION_OPEN":
      return {
        badge: `Registration closes in ${formatCountdown(closesAt - now)}`,
        message: `Starts ${startLabel}. Registration closes in ${formatCountdown(closesAt - now)} - join now to save your seat.`,
        canJoin: true,
        tone: "open",
      };
    case "REGISTRATION_CLOSED":
      return {
        badge: `Starts in ${formatCountdown(startsAt - now)}`,
        message: `Registration is closed. The competition starts in ${formatCountdown(startsAt - now)}.`,
        canJoin: false,
        tone: "closed",
      };
    case "LIVE":
      return {
        badge: "Live now",
        message: "This competition has already started.",
        canJoin: false,
        tone: "live",
      };
    case "COMPLETED":
      return {
        badge: "Completed",
        message: "This scheduled competition has already finished.",
        canJoin: false,
        tone: "ended",
      };
    case "CANCELLED":
      return {
        badge: "Cancelled",
        message: "This event was cancelled - not enough participants joined before the start time.",
        canJoin: false,
        tone: "cancelled",
      };
    case "POSTPONED":
      return {
        badge: "Postponed",
        message: "This event was postponed - not enough participants joined before the start time.",
        canJoin: false,
        tone: "cancelled",
      };
    default:
      return { badge: "", message: "", canJoin: false, tone: "upcoming" };
  }
}
