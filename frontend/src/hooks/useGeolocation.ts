import { useCallback, useEffect, useRef, useState } from "react";

export type GeolocationStatus =
  | "idle"
  | "requesting"
  | "granted"
  | "denied"
  | "unsupported"
  | "error";

export interface GeolocationCoords {
  lat: number;
  lng: number;
}

/**
 * Thin wrapper around the browser Geolocation API, used for the "Live near
 * you" section embedded in the Events page (see
 * components/NearbyRoomsPanel.tsx). Exposes a simple status machine instead
 * of raw Permission/PositionError objects so the UI can render a clear
 * "enable location" prompt, a denied state with a fallback to the
 * country/city picker, etc.
 *
 * A couple of things this guards against that a naive wrapper wouldn't:
 * - Never calls setState after the component using it has unmounted (e.g.
 *   the user navigates away while the browser's permission prompt is still
 *   open) - avoids the classic "Can't perform a React state update on an
 *   unmounted component" leak/warning.
 * - Pre-checks the Permissions API where available so a user who already
 *   granted access on a previous visit doesn't need to click "enable
 *   location" again just to get results.
 */
export function useGeolocation() {
  const [status, setStatus] = useState<GeolocationStatus>("idle");
  const [coords, setCoords] = useState<GeolocationCoords | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const requestPosition = useCallback(() => {
    if (!("geolocation" in navigator)) {
      setStatus("unsupported");
      return;
    }
    setStatus("requesting");
    setErrorMessage(null);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        if (!mountedRef.current) return;
        setCoords({
          lat: position.coords.latitude,
          lng: position.coords.longitude,
        });
        setStatus("granted");
      },
      (err) => {
        if (!mountedRef.current) return;
        if (err.code === err.PERMISSION_DENIED) {
          setStatus("denied");
          setErrorMessage("Location access was denied.");
        } else if (err.code === err.TIMEOUT) {
          setStatus("error");
          setErrorMessage("Location request timed out. Please try again.");
        } else {
          setStatus("error");
          setErrorMessage("Couldn't get your location. Please try again.");
        }
      },
      { enableHighAccuracy: false, timeout: 10_000, maximumAge: 5 * 60_000 },
    );
  }, []);

  // Best-effort: if the browser already knows this origin has permission
  // (from a previous visit), reflect that immediately instead of making the
  // user click "enable location" again just to trigger the same silent
  // grant. Support for the Permissions API is inconsistent, so this is
  // purely an enhancement - it never blocks the explicit `request()` path
  // below, and any failure here is swallowed silently.
  useEffect(() => {
    if (!("geolocation" in navigator)) {
      setStatus("unsupported");
      return;
    }
    if (!("permissions" in navigator) || !navigator.permissions?.query) {
      return;
    }
    let cancelled = false;
    navigator.permissions
      .query({ name: "geolocation" as PermissionName })
      .then((result) => {
        if (cancelled || !mountedRef.current) return;
        if (result.state === "granted") {
          requestPosition();
        }
      })
      .catch(() => {
        // Some browsers (older Safari) don't support querying this
        // permission name - fall back silently to the explicit button.
      });
    return () => {
      cancelled = true;
    };
  }, [requestPosition]);

  // Explicit, user-initiated request (e.g. a button press) - always shows
  // the "requesting..." state so there's clear feedback even if the
  // permission prompt itself is answered instantly.
  const request = useCallback(() => {
    requestPosition();
  }, [requestPosition]);

  const reset = useCallback(() => {
    setStatus("idle");
    setCoords(null);
    setErrorMessage(null);
  }, []);

  return { status, coords, errorMessage, request, reset };
}
