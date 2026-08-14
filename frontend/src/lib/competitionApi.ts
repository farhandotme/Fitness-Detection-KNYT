import type { EventDetail, LiveEventSummary, RoomListEntry, RoomPreview } from "@/types/competition";

function getApiBase(): string {
  return (
    import.meta.env.VITE_COMPETITION_API_URL ||
    localStorage.getItem("COMPETITION_API_BASE_OVERRIDE") ||
    "http://localhost:4000"
  ).replace(/\/+$/, "");
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${getApiBase()}${path}`, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ message: res.statusText }));
    throw new Error(body.message || `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
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
