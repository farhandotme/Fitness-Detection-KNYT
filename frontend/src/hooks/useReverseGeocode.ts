import { useEffect, useRef, useState } from "react";

export interface ResolvedPlace {
  /** Locality-level label, e.g. "Dispur, Guwahati" - matches how apps like OLX show it. */
  label: string;
  /** Neighbourhood/suburb, when Nominatim has one - the most specific part. */
  locality?: string;
  city?: string;
  country?: string;
}

type Status = "idle" | "loading" | "resolved" | "error";

// Round to ~100m so GPS jitter within the same block re-uses the last
// lookup instead of re-fetching on every render.
function roundCoord(n: number) {
  return Math.round(n * 1000) / 1000;
}

const cache = new Map<string, ResolvedPlace>();

/**
 * Turns a lat/lng into a "You're in <locality>, <city>" style label via
 * OpenStreetMap's free Nominatim reverse-geocoding endpoint, at
 * neighbourhood-level zoom rather than city-level. Best-effort and silent
 * on failure - the caller should treat `place` as optional decoration,
 * never something the rest of the UI depends on.
 */
export function useReverseGeocode(lat?: number, lng?: number) {
  const [status, setStatus] = useState<Status>("idle");
  const [place, setPlace] = useState<ResolvedPlace | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (lat === undefined || lng === undefined) {
      setStatus("idle");
      setPlace(null);
      return;
    }

    const key = `${roundCoord(lat)},${roundCoord(lng)}`;
    const cached = cache.get(key);
    if (cached) {
      setPlace(cached);
      setStatus("resolved");
      return;
    }

    const controller = new AbortController();
    setStatus("loading");

    // zoom=18 pulls neighbourhood/suburb-level detail instead of stopping
    // at the city, e.g. "Dispur" rather than just "Guwahati".
    const url = `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${lat}&lon=${lng}&zoom=18&addressdetails=1`;

    fetch(url, {
      signal: controller.signal,
      headers: { Accept: "application/json" },
    })
      .then((res) => (res.ok ? res.json() : Promise.reject(res.status)))
      .then((data) => {
        if (!mountedRef.current) return;
        const address = data?.address ?? {};
        const locality: string | undefined =
          address.suburb ||
          address.neighbourhood ||
          address.quarter ||
          address.locality ||
          address.city_district;
        const city: string | undefined =
          address.city ||
          address.town ||
          address.village ||
          address.municipality ||
          address.county;
        const country: string | undefined = address.country;

        if (!locality && !city && !country) {
          setStatus("error");
          setPlace(null);
          return;
        }

        // Prefer "locality, city" (e.g. "Dispur, Guwahati"); fall back
        // gracefully as detail is available.
        const label =
          [locality, city].filter(Boolean).join(", ") ||
          city ||
          locality ||
          country!;

        const resolved: ResolvedPlace = { label, locality, city, country };
        cache.set(key, resolved);
        setPlace(resolved);
        setStatus("resolved");
      })
      .catch((err) => {
        if (err?.name === "AbortError") return;
        if (!mountedRef.current) return;
        setStatus("error");
        setPlace(null);
      });

    return () => controller.abort();
  }, [
    lat !== undefined ? roundCoord(lat) : lat,
    lng !== undefined ? roundCoord(lng) : lng,
  ]);

  return { place, status };
}
