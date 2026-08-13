/**
 * Minimal IANA timezone <-> UTC conversion, built on Node's built-in Intl
 * support (Node ships with full ICU, so this needs no extra dependency).
 *
 * The scheduling feature lets an admin type a *wall-clock* time ("20 August
 * 2026, 7:00 PM") plus an IANA zone ("Asia/Kolkata") and needs that turned
 * into the single UTC instant it actually refers to, so it can be compared
 * against `Date.now()` by the scheduler regardless of what timezone the
 * server process itself happens to run in.
 */

/**
 * Returns how far `timeZone`'s wall clock is ahead of UTC at the instant
 * `utcInstantMs`, in milliseconds. E.g. for Asia/Kolkata (UTC+5:30) this is
 * `5.5 * 60 * 60 * 1000`.
 */
function getTimeZoneOffsetMs(utcInstantMs: number, timeZone: string): number {
  const dtf = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  const parts: Record<string, string> = {};
  for (const part of dtf.formatToParts(new Date(utcInstantMs))) {
    if (part.type !== "literal") parts[part.type] = part.value;
  }

  // Re-interpret those same wall-clock digits as if they were UTC - the gap
  // between that and the real UTC instant we started from *is* the zone's
  // offset at this moment (handles DST correctly since we look up the
  // offset for the actual instant in question).
  const asIfUtc = Date.UTC(
    Number(parts.year),
    Number(parts.month) - 1,
    Number(parts.day),
    Number(parts.hour),
    Number(parts.minute),
    Number(parts.second),
  );

  return asIfUtc - utcInstantMs;
}

/**
 * Converts a naive local datetime string (no offset, e.g.
 * "2026-08-20T19:00:00" or "2026-08-20T19:00") that represents a wall-clock
 * time *in* `timeZone` into the UTC `Date` it corresponds to.
 */
export function zonedTimeToUtc(
  localDateTimeString: string,
  timeZone: string,
): Date {
  const normalized = /Z|[+-]\d\d:?\d\d$/.test(localDateTimeString)
    ? localDateTimeString
    : `${localDateTimeString}Z`;
  const guessUtcMs = Date.parse(normalized);
  if (Number.isNaN(guessUtcMs)) {
    throw new Error(`Invalid local date/time: ${localDateTimeString}`);
  }

  // One pass is enough for practically every real case; a second pass keeps
  // us correct even a few minutes either side of a DST transition, where
  // the offset computed from the first guess could itself be slightly off.
  const offset1 = getTimeZoneOffsetMs(guessUtcMs, timeZone);
  const refined = guessUtcMs - offset1;
  const offset2 = getTimeZoneOffsetMs(refined, timeZone);
  return new Date(guessUtcMs - offset2);
}

/** Human-readable rendering of a UTC instant in a given IANA zone, for logs. */
export function formatInTimeZone(date: Date, timeZone: string): string {
  return new Intl.DateTimeFormat("en-US", {
    timeZone,
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}
