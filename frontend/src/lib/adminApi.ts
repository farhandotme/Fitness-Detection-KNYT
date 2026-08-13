import type { RoomStateSnapshot } from "@/types/competition";

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
  createdAt: string;
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

export async function createAdminEvent(
  input: CreateEventInput,
): Promise<AdminEvent> {
  const data = await adminFetch<{ event: AdminEvent }>("/api/admin/events", {
    method: "POST",
    body: JSON.stringify(input),
  });
  return data.event;
}

export async function setAdminEventStatus(
  id: string,
  status: "draft" | "live" | "closed",
): Promise<AdminEvent> {
  const data = await adminFetch<{ event: AdminEvent }>(
    `/api/admin/events/${id}/status`,
    {
      method: "POST",
      body: JSON.stringify({ status }),
    },
  );
  return data.event;
}

export async function fetchAdminStats(): Promise<AdminStats> {
  const data = await adminFetch<{ stats: AdminStats }>("/api/admin/stats");
  return data.stats;
}

export async function fetchLiveRooms(): Promise<LiveRoomSummary[]> {
  const data = await adminFetch<{ rooms: LiveRoomSummary[] }>(
    "/api/admin/competitions/live",
  );
  return data.rooms;
}

export async function fetchRoomSnapshot(
  competitionId: string,
): Promise<RoomStateSnapshot> {
  const data = await adminFetch<{ room: RoomStateSnapshot }>(
    `/api/admin/competitions/${competitionId}`,
  );
  return data.room;
}
