import type { EventScheduling, RoomStateSnapshot } from "@/types/competition";

const ADMIN_TOKEN_KEY = "admin_token";
const ADMIN_USERNAME_KEY = "admin_username";

function getApiBase(): string {
  return (
    import.meta.env.VITE_COMPETITION_API_URL ||
    localStorage.getItem("COMPETITION_API_BASE_OVERRIDE") ||
    "http://localhost:4000"
  ).replace(/\/+$/, "");
}

export function getAdminToken(): string | null {
  return localStorage.getItem(ADMIN_TOKEN_KEY);
}

export function getAdminUsername(): string | null {
  return localStorage.getItem(ADMIN_USERNAME_KEY);
}

export function saveAdminSession(token: string, username: string): void {
  localStorage.setItem(ADMIN_TOKEN_KEY, token);
  localStorage.setItem(ADMIN_USERNAME_KEY, username);
}

export function clearAdminSession(): void {
  localStorage.removeItem(ADMIN_TOKEN_KEY);
  localStorage.removeItem(ADMIN_USERNAME_KEY);
}

async function adminFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAdminToken();
  const res = await fetch(`${getApiBase()}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });

  if (res.status === 401) {
    clearAdminSession();
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({ message: res.statusText }));
    throw new Error(body.message || `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export interface AdminEvent {
  _id: string;
  name: string;
  exerciseId: string;
  exerciseName: string;
  exerciseMode: "reps" | "hold";
  rounds: number;
  roundDurationSeconds: number;
  breakDurationSeconds: number;
  maxParticipants: number;
  status: "draft" | "live" | "closed";
  description?: string;
  imageUrl?: string;
  scheduling?: EventScheduling;
  createdAt: string;
}

export interface AdminStats {
  totalEvents: number;
  liveEvents: number;
  activeRooms: number;
  completedCompetitions: number;
  playersOnlineNow: number;
}

export interface LiveRoomSummary {
  competitionId: string;
  eventId: string;
  eventName: string;
  exerciseId: string;
  status: string;
  currentRound: number;
  totalRounds: number;
  participantCount: number;
  maxParticipants: number;
  participantNames: string[];
  hostName: string | null;
  createdAt: string;
}

export interface AdminEventRoomSummary {
  competitionId: string;
  roomName: string;
  visibility: "public" | "private";
  status: string;
  phase: "running" | "waiting" | "ended";
  currentRound: number;
  totalRounds: number;
  participantCount: number;
  maxParticipants: number;
  participantNames: string[];
  hostName: string | null;
  createdAt: string;
  completedAt: string | null;
}

export interface AdminEventRoomsResponse {
  event: {
    id: string;
    name: string;
    exerciseName: string;
    status: "draft" | "live" | "closed";
    maxParticipants: number;
  };
  rooms: AdminEventRoomSummary[];
}

export interface CreateEventSchedulingInput {
  scheduledAtLocal: string;
  registrationOpensAtLocal: string;
  registrationClosesAtLocal: string;
  timezone: string;
  minParticipants: number;
  onInsufficientParticipants: "cancel" | "postpone";
}

export interface CreateEventInput {
  name: string;
  exerciseId: string;
  exerciseName: string;
  exerciseMode: "reps" | "hold";
  rounds: number;
  roundDurationSeconds: number;
  breakDurationSeconds: number;
  maxParticipants: number;
  description?: string;
  imageUrl?: string;
  status: "draft" | "live" | "closed";
  scheduling?: CreateEventSchedulingInput;
}

export async function registerAdmin(
  username: string,
  password: string,
  signupCode: string,
): Promise<{ token: string; username: string }> {
  const res = await fetch(`${getApiBase()}/api/admin/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, signupCode }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ message: res.statusText }));
    throw new Error(body.message || "Registration failed");
  }
  return res.json();
}

export async function loginAdmin(
  username: string,
  password: string,
): Promise<{ token: string; username: string }> {
  const res = await fetch(`${getApiBase()}/api/admin/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ message: res.statusText }));
    throw new Error(body.message || "Login failed");
  }
  return res.json();
}

export async function fetchAdminEvents(): Promise<AdminEvent[]> {
  const data = await adminFetch<{ events: AdminEvent[] }>("/api/admin/events");
  return data.events;
}

export async function createAdminEvent(input: CreateEventInput): Promise<AdminEvent> {
  const data = await adminFetch<{ event: AdminEvent }>("/api/admin/events", {
    method: "POST",
    body: JSON.stringify(input),
  });
  return data.event;
}

/** Partial edit of an existing event - only the fields you pass are changed. */
export async function updateAdminEvent(id: string, input: Partial<CreateEventInput>): Promise<AdminEvent> {
  const data = await adminFetch<{ event: AdminEvent }>(`/api/admin/events/${id}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
  return data.event;
}

/** Permanently removes an event. The API refuses (409) if a room under it is still in progress. */
export async function deleteAdminEvent(id: string): Promise<void> {
  const token = getAdminToken();
  const res = await fetch(`${getApiBase()}/api/admin/events/${id}`, {
    method: "DELETE",
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  if (res.status === 401) clearAdminSession();
  if (!res.ok) {
    // DELETE returns 204 with no body on success, so only parse JSON on failure.
    const body = await res.json().catch(() => ({ message: res.statusText }));
    throw new Error(body.message || `Request failed (${res.status})`);
  }
}

export async function setAdminEventStatus(
  id: string,
  status: "draft" | "live" | "closed",
): Promise<AdminEvent> {
  const data = await adminFetch<{ event: AdminEvent }>(`/api/admin/events/${id}/status`, {
    method: "POST",
    body: JSON.stringify({ status }),
  });
  return data.event;
}

/** Manual override for a scheduled event ahead of its start time. */
export async function setAdminEventSchedulingPhase(
  id: string,
  phase: "CANCELLED" | "POSTPONED",
): Promise<AdminEvent> {
  const data = await adminFetch<{ event: AdminEvent }>(`/api/admin/events/${id}/scheduling/phase`, {
    method: "POST",
    body: JSON.stringify({ phase }),
  });
  return data.event;
}

export async function fetchAdminStats(): Promise<AdminStats> {
  const data = await adminFetch<{ stats: AdminStats }>("/api/admin/stats");
  return data.stats;
}

export async function fetchLiveRooms(): Promise<LiveRoomSummary[]> {
  const data = await adminFetch<{ rooms: LiveRoomSummary[] }>("/api/admin/competitions/live");
  return data.rooms;
}

/** Every room ever created under one event (any status), for the admin's per-event drill-down. */
export async function fetchEventRooms(eventId: string): Promise<AdminEventRoomsResponse> {
  return adminFetch<AdminEventRoomsResponse>(`/api/admin/events/${eventId}/rooms`);
}

export async function fetchRoomSnapshot(competitionId: string): Promise<RoomStateSnapshot> {
  const data = await adminFetch<{ room: RoomStateSnapshot }>(`/api/admin/competitions/${competitionId}`);
  return data.room;
}
