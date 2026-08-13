import { useEffect, useRef, useState } from "react";
import { getCompetitionSocket } from "@/lib/competitionSocket";
import type { EventPhasePayload, EventScheduling } from "@/types/competition";

interface UseEventPhaseResult {
  scheduling: EventScheduling | undefined;
  /** Server-clock-corrected "now", updates every second while a scheduling block is present. */
  now: number;
}

/**
 * Keeps a scheduled event's `scheduling` block live: joins the event's
 * Socket.IO room so services/eventScheduler.ts's phase broadcasts land
 * immediately, and ticks a local clock (corrected for drift against the
 * `serverNow` the API/socket handed us) so countdown labels update every
 * second without re-fetching.
 */
export function useEventPhase(eventId: string | undefined, initial: EventScheduling | undefined, initialServerNow: number | undefined): UseEventPhaseResult {
  const [scheduling, setScheduling] = useState<EventScheduling | undefined>(initial);
  const clockOffsetRef = useRef(initialServerNow ? initialServerNow - Date.now() : 0);
  const [now, setNow] = useState(() => Date.now() + clockOffsetRef.current);

  useEffect(() => {
    setScheduling(initial);
  }, [initial]);

  useEffect(() => {
    if (initialServerNow) clockOffsetRef.current = initialServerNow - Date.now();
  }, [initialServerNow]);

  useEffect(() => {
    if (!eventId || !scheduling) return;
    const socket = getCompetitionSocket();
    socket.emit("event:watch", { eventId });

    const onPhase = (payload: EventPhasePayload) => {
      if (payload.eventId !== eventId) return;
      clockOffsetRef.current = payload.serverNow - Date.now();
      setScheduling((prev) =>
        prev
          ? {
              ...prev,
              phase: payload.phase,
              scheduledAt: payload.scheduledAt ?? prev.scheduledAt,
              registrationOpensAt: payload.registrationOpensAt ?? prev.registrationOpensAt,
              registrationClosesAt: payload.registrationClosesAt ?? prev.registrationClosesAt,
            }
          : prev,
      );
    };

    socket.on("event:phase", onPhase);
    return () => {
      socket.off("event:phase", onPhase);
      socket.emit("event:unwatch", { eventId });
    };
    // Only needs to (re)subscribe when the event id changes or a scheduling
    // block first appears - not on every scheduling update itself.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eventId, Boolean(scheduling)]);

  useEffect(() => {
    if (!scheduling) return;
    const interval = window.setInterval(() => {
      setNow(Date.now() + clockOffsetRef.current);
    }, 1000);
    return () => window.clearInterval(interval);
  }, [scheduling]);

  return { scheduling, now };
}
