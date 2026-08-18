export interface RecentLocation {
  label: string;
  lat: number;
  lng: number;
}

const STORAGE_KEY = "knyt.recentLocations";
const MAX_RECENT = 5;

export function getRecentLocations(): RecentLocation[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function addRecentLocation(loc: RecentLocation) {
  try {
    const deduped = getRecentLocations().filter((l) => l.label !== loc.label);
    const next = [loc, ...deduped].slice(0, MAX_RECENT);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Best-effort only - private browsing / storage quota failures are fine to ignore.
  }
}
