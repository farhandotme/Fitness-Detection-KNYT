/**
 * Converts a "wall clock" date/time in a given IANA timezone into the
 * correct UTC instant, using only built-in Intl APIs (no extra dependency
 * like luxon/date-fns-tz needed just for this).
 *
 * Two passes handle DST correctly: the first pass estimates the offset,
 * the second re-checks the offset at the corrected instant so the result
 * lands on the right side of a DST transition.
 */
function getOffsetMs(instant: Date, timeZone: string): number {
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
  const parts = dtf.formatToParts(instant);
  const map: Record<string, string> = {};
  for (const part of parts) map[part.type] = part.value;
  const asUtc = Date.UTC(
    Number(map.year),
    Number(map.month) - 1,
    Number(map.day),
    Number(map.hour),
    Number(map.minute),
    Number(map.second),
  );
  return asUtc - instant.getTime();
}

/**
 * @param localDateTime wall-clock time with no offset, "YYYY-MM-DDTHH:mm"
 * @param timeZone IANA zone, e.g. "Asia/Kolkata"
 */
export function zonedTimeToUtc(localDateTime: string, timeZone: string): Date {
  const naiveUtc = new Date(`${localDateTime}:00Z`);
  if (Number.isNaN(naiveUtc.getTime())) {
    throw new Error(
      `Invalid local date/time: "${localDateTime}", expected "YYYY-MM-DDTHH:mm"`,
    );
  }
  let offset = getOffsetMs(naiveUtc, timeZone);
  let result = new Date(naiveUtc.getTime() - offset);
  offset = getOffsetMs(result, timeZone);
  result = new Date(naiveUtc.getTime() - offset);
  return result;
}
