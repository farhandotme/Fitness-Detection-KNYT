export function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/** "3d 4h", "12m 05s", "45s" style label for a duration, for countdown UI. */
export function formatCountdown(ms: number): string {
  if (ms <= 0) return "0s";
  const totalSeconds = Math.floor(ms / 1000);
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${seconds.toString().padStart(2, "0")}s`;
  return `${seconds}s`;
}

/** Renders a UTC ISO instant in the given IANA zone, e.g. "Aug 20, 7:00 PM". */
export function formatInTimeZone(isoUtc: string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-US", {
    timeZone,
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(isoUtc));
}

/** Time-only, no date, e.g. "7:00 PM" - for pairing start/end into a range. */
export function formatTimeOnlyInTimeZone(
  isoUtc: string,
  timeZone: string,
): string {
  return new Intl.DateTimeFormat("en-US", {
    timeZone,
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(isoUtc));
}

/** "7:00 PM - 11:00 PM" if an end is given, else just the start time. */
export function formatTimeRangeInTimeZone(
  startIsoUtc: string,
  endIsoUtc: string | undefined,
  timeZone: string,
): string {
  const start = formatTimeOnlyInTimeZone(startIsoUtc, timeZone);
  if (!endIsoUtc) return start;
  return `${start} - ${formatTimeOnlyInTimeZone(endIsoUtc, timeZone)}`;
}
