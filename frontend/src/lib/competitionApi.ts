import type { EventDetail, LiveEventSummary } from "@/types/competition";

function getApiBase(): string {
  return (
    import.meta.env.VITE_COMPETITION_API_URL ||
    localStorage.getItem("COMPETITION_API_BASE_OVERRIDE") ||
    "http://localhost:4000"
  ).replace(/\/+$/, "");
}

async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${getApiBase()}${path}`);
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
