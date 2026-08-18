export interface GeoSearchResult {
  label: string;
  lat: number;
  lng: number;
}

/**
 * Forward geocoding: turns a free-text query ("Dispur", "Six Mile Guwahati")
 * into a short list of real places with coordinates, via OpenStreetMap's
 * free Nominatim search endpoint. Used by LocationPicker so a user can pick
 * their own location instead of relying purely on GPS.
 */
export async function searchPlaces(
  query: string,
  signal?: AbortSignal,
): Promise<GeoSearchResult[]> {
  const q = query.trim();
  if (!q) return [];

  const url = `https://nominatim.openstreetmap.org/search?format=jsonv2&q=${encodeURIComponent(
    q,
  )}&addressdetails=1&limit=6`;

  const res = await fetch(url, {
    signal,
    headers: { Accept: "application/json" },
  });
  if (!res.ok) throw new Error(`Search failed (${res.status})`);

  const data = await res.json();
  if (!Array.isArray(data)) return [];

  return data.map((item: any) => ({
    label: item.display_name as string,
    lat: parseFloat(item.lat),
    lng: parseFloat(item.lon),
  }));
}
