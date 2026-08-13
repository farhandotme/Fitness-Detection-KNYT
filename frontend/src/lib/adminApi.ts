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
  if (res.status === 204) {
    return undefined as T;
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
  createdAt: string;
  stats?: EventRoomStats;
}

export interface EventRoomStats {
  active: number;
  completed: number;
  abandoned: number;
  totalParticipants: number;
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
  status: "draft" | "live" | "closed";
}

export type UpdateEventInput = Partial<CreateEventInput>;

export type AdminCompetitionStatus =
  | "WAITING"
  | "FULL"
  | "COUNTDOWN"
  | "ROUND_RUNNING"
  | "ROUND_FINISHED"
  | "BREAK"
  | "COMPLETED"
  | "ABANDONED";

export interface AdminCompetitionParticipant {
  participantId: string;
  displayName: string;
  joinedAt: string;
}

export interface AdminCompetitionRoundScore {
  participantId: string;
  score: number;
}

export interface AdminCompetitionRound {
  roundNumber: number;
  startedAt: string;
  endedAt?: string;
  scores: AdminCompetitionRoundScore[];
}

export interface AdminCompetitionFinalResult {
  participantId: string;
  displayName: string;
  totalScore: number;
  rank: number;
}

export interface AdminCompetitionRoom {
  _id: string;
  eventId: string;
  eventName: string;
  exerciseId: string;
  exerciseMode: "reps" | "hold";
  roomCode: string;
  status: AdminCompetitionStatus;
  maxParticipants: number;
  totalRounds: number;
  roundDurationSeconds: number;
  breakDurationSeconds: number;
  currentRound: number;
  participants: AdminCompetitionParticipant[];
  rounds: AdminCompetitionRound[];
  finalResults: AdminCompetitionFinalResult[];
  completedAt?: string;
  abandonedAt?: string;
  abandonReason?: string;
  createdAt: string;
  updatedAt: string;
}

export interface PagedResult<T> {
  rooms: T[];
  total: number;
  page: number;
  limit: number;
}

export interface AdminCompetitionDetail {
  room: AdminCompetitionRoom;
  // Live snapshot (connection state, current-phase end timestamps,
  // leaderboard) - present for anything not yet completed/abandoned; the
  // Mongo `room` above already carries everything needed once it's over.
  snapshot: RoomStateSnapshot | null;
}

// Minimal local copy - avoids importing the participant-app's competition
// types (which pull in socket-client code this admin surface doesn't need)
// just for one shape.
export interface RoomStateSnapshot {
  competitionId: string;
  status: AdminCompetitionStatus;
  currentRound: number;
  participants: { participantId: string; displayName: string; connected: boolean }[];
  leaderboard: { participantId: string; displayName: string; score: number; rank: number }[];
  countdownEndAt: number | null;
  roundStartAt: number | null;
  roundEndAt: number | null;
  breakEndAt: number | null;
  serverNow: number;
}

export interface DashboardStats {
  events: { total: number; draft: number; live: number; closed: number };
  competitions: {
    total: number;
    active: number;
    completed: number;
    abandoned: number;
    liveParticipantsNow: number;
  };
  completedLast24h: number;
  mostPopularExercise: { exerciseId: string; exerciseName: string; count: number } | null;
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

export async function changeAdminPassword(
  currentPassword: string,
  newPassword: string,
): Promise<{ token: string; username: string }> {
  const data = await adminFetch<{ token: string; username: string }>("/api/admin/auth/change-password", {
    method: "POST",
    body: JSON.stringify({ currentPassword, newPassword }),
  });
  // The server issues a fresh token alongside the password change - keep
  // the stored session in sync so the admin isn't unexpectedly logged out.
  saveAdminSession(data.token, data.username);
  return data;
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

export async function fetchAdminEventDetail(id: string): Promise<AdminEvent> {
  const data = await adminFetch<{ event: AdminEvent }>(`/api/admin/events/${id}`);
  return data.event;
}

export async function updateAdminEvent(id: string, input: UpdateEventInput): Promise<AdminEvent> {
  const data = await adminFetch<{ event: AdminEvent }>(`/api/admin/events/${id}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
  return data.event;
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

/** Only succeeds for a draft event with zero competition rooms ever created - see backend for why. */
export async function deleteAdminEvent(id: string): Promise<void> {
  await adminFetch<void>(`/api/admin/events/${id}`, { method: "DELETE" });
}

export async function fetchEventCompetitions(
  eventId: string,
  opts: { status?: AdminCompetitionStatus; page?: number; limit?: number } = {},
): Promise<PagedResult<AdminCompetitionRoom>> {
  const qs = buildQuery(opts);
  return adminFetch<PagedResult<AdminCompetitionRoom>>(`/api/admin/events/${eventId}/competitions${qs}`);
}

export async function fetchAllCompetitions(
  opts: { status?: AdminCompetitionStatus; eventId?: string; page?: number; limit?: number } = {},
): Promise<PagedResult<AdminCompetitionRoom>> {
  const qs = buildQuery(opts);
  return adminFetch<PagedResult<AdminCompetitionRoom>>(`/api/admin/competitions${qs}`);
}

export async function fetchAdminCompetitionDetail(id: string): Promise<AdminCompetitionDetail> {
  return adminFetch<AdminCompetitionDetail>(`/api/admin/competitions/${id}`);
}

export async function abandonAdminCompetition(id: string, reason?: string): Promise<void> {
  await adminFetch<{ ok: true }>(`/api/admin/competitions/${id}/abandon`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

/** Pre-start only (WAITING/FULL) - see backend removeParticipantAdmin for why. */
export async function removeAdminParticipant(competitionId: string, participantId: string): Promise<void> {
  await adminFetch<void>(`/api/admin/competitions/${competitionId}/participants/${participantId}`, {
    method: "DELETE",
  });
}

export async function fetchDashboardStats(): Promise<DashboardStats> {
  const data = await adminFetch<{ stats: DashboardStats }>("/api/admin/dashboard/stats");
  return data.stats;
}

/**
 * CSV download needs the admin's bearer token, so it can't be a plain
 * `<a href>` - fetched as a blob and handed to the browser via a
 * throwaway object URL instead.
 */
export async function downloadEventResultsCsv(eventId: string, suggestedName: string): Promise<void> {
  const token = getAdminToken();
  const res = await fetch(`${getApiBase()}/api/admin/events/${eventId}/results.csv`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ message: res.statusText }));
    throw new Error(body.message || "Could not export results");
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = suggestedName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function buildQuery(params: Record<string, string | number | undefined>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== "");
  if (entries.length === 0) return "";
  const search = new URLSearchParams(entries.map(([k, v]) => [k, String(v)]));
  return `?${search.toString()}`;
}
