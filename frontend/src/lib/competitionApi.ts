import type {
  DiscoveredRoomEntry,
  EventDetail,
  LiveEventSummary,
  RoomListEntry,
  RoomPreview,
} from "@/types/competition";

function getApiBase(): string {
  return (
    import.meta.env.VITE_COMPETITION_API_URL ||
    localStorage.getItem("COMPETITION_API_BASE_OVERRIDE") ||
    "http://localhost:4000"
  ).replace(/\/+$/, "");
}

// Guards every request against a hung connection (bad network, backend
// stalled, etc.) so the UI never spins forever - it fails predictably
// instead. Kept generous since this also covers slower mobile connections.
const DEFAULT_TIMEOUT_MS = 12_000;

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  // Respect a caller-supplied AbortSignal (e.g. to cancel a stale "nearby"
  // search when the user changes radius again before the first one
  // resolves) while still enforcing our own timeout - whichever fires
  // first wins.
  const timeoutController = new AbortController();
  const timeoutId = setTimeout(
    () => timeoutController.abort(),
    DEFAULT_TIMEOUT_MS,
  );
  const externalSignal = init?.signal;
  if (externalSignal) {
    if (externalSignal.aborted) timeoutController.abort();
    else
      externalSignal.addEventListener("abort", () => timeoutController.abort());
  }

  try {
    const res = await fetch(`${getApiBase()}${path}`, {
      ...init,
      signal: timeoutController.signal,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({ message: res.statusText }));
      if (res.status === 429) {
        throw new Error(
          body.message || "Too many requests, please slow down.",
        );
      }
      throw new Error(body.message || `Request failed (${res.status})`);
    }
    return (await res.json()) as T;
  } catch (err: any) {
    if (err?.name === "AbortError") {
      // Distinguish "the caller cancelled this on purpose" (e.g. a newer
      // search superseded it) from a genuine timeout, so callers that care
      // can ignore the former without showing an error toast for it.
      if (externalSignal?.aborted) {
        throw Object.assign(new Error("Request cancelled"), {
          name: "AbortError",
        });
      }
      throw new Error("The request timed out. Please check your connection and try again.");
    }
    if (err instanceof TypeError) {
      // fetch() throws a bare TypeError for DNS/connection failures - give
      // people something more actionable than "Failed to fetch".
      throw new Error(
        "Could not reach the server. Check your connection and try again.",
      );
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function fetchLiveEvents(): Promise<LiveEventSummary[]> {
  const data = await apiFetch<{ events: LiveEventSummary[] }>("/api/events");
  return data.events;
}

export async function fetchEventDetail(eventId: string): Promise<EventDetail> {
  const data = await apiFetch<{ event: EventDetail }>(`/api/events/${eventId}`);
  return data.event;
}

/** Every open room under an event, for the lobby list shown before anyone types a name. */
export async function fetchEventRooms(eventId: string): Promise<RoomListEntry[]> {
  const data = await apiFetch<{ rooms: RoomListEntry[] }>(`/api/events/${eventId}/rooms`);
  return data.rooms;
}

/** Preview a room's occupants before joining - password required only for private rooms. */
export async function revealRoom(eventId: string, competitionId: string, password?: string): Promise<RoomPreview> {
  const data = await apiFetch<{ room: RoomPreview }>(`/api/events/${eventId}/rooms/${competitionId}/reveal`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  return data.room;
}

export interface DiscoverRoomsParams {
  lat?: number;
  lng?: number;
  radiusKm?: number;
  country?: string;
  city?: string;
  /** Scopes results to a single event's rooms - used by the per-event "Near you" filter. */
  eventId?: string;
  /** Cancels this request if a newer one supersedes it (e.g. radius changed again before this resolved). */
  signal?: AbortSignal;
}

/**
 * Open rooms anywhere, tagged with location and filtered either by a
 * lat/lng + radius ("near you") or a country (+ optional city) ("choose a
 * region"), optionally scoped to one event. Powers the "Live near you"
 * section embedded in the Events page and the "Near you" filter inside a
 * single event's rooms lobby - see components/NearbyRoomsPanel.tsx and
 * pages/events/RoomsLobbyPage.tsx.
 */
export async function discoverRooms({
  signal,
  ...params
}: DiscoverRoomsParams): Promise<DiscoveredRoomEntry[]> {
  const query = new URLSearchParams();
  if (params.lat !== undefined) query.set("lat", String(params.lat));
  if (params.lng !== undefined) query.set("lng", String(params.lng));
  if (params.radiusKm !== undefined) query.set("radiusKm", String(params.radiusKm));
  if (params.country) query.set("country", params.country);
  if (params.city) query.set("city", params.city);
  if (params.eventId) query.set("eventId", params.eventId);

  const data = await apiFetch<{ rooms: DiscoveredRoomEntry[] }>(
    `/api/discover/rooms?${query.toString()}`,
    { signal },
  );
  return data.rooms;
}
