import React, { useEffect, useRef, useState } from "react";
import { useLocation } from "wouter";
import { useGeolocation } from "@/hooks/useGeolocation";
import { discoverRooms } from "@/lib/competitionApi";
import { COUNTRIES } from "@/config/countries";
import type { DiscoveredRoomEntry } from "@/types/competition";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import {
  MapPin,
  Navigation,
  Users,
  Lock,
  RefreshCw,
  AlertTriangle,
  ArrowRight,
  Locate,
  ChevronDown,
  Globe2,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";

const RADIUS_OPTIONS_KM = [10, 25, 40, 100];

export interface NearbyRoomsPanelProps {
  /** Lets the Events page badge each event card with "N near you" once results land. */
  onResults?: (rooms: DiscoveredRoomEntry[]) => void;
}

/**
 * "Live near you" - the location-based room finder, embedded directly
 * inside the Events page instead of living behind a separate /nearby
 * route. Nudges the visitor to enable location with a slim, low-friction
 * prompt; once granted it streams live open rooms (grouped by the event
 * they belong to) as a horizontally-scrollable strip sitting right above
 * the main event grid, so "nearby" always reads as part of Events rather
 * than a competing destination.
 */
export function NearbyRoomsPanel({ onResults }: NearbyRoomsPanelProps) {
  const [, setLocation] = useLocation();
  const geo = useGeolocation();

  const [radiusKm, setRadiusKm] = useState(25);
  const [rooms, setRooms] = useState<DiscoveredRoomEntry[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [regionFallbackOpen, setRegionFallbackOpen] = useState(false);
  const [countryCode, setCountryCode] = useState(COUNTRIES[0].code);
  const [city, setCity] = useState("");
  const [dismissedPrompt, setDismissedPrompt] = useState(false);

  // Cancels a still-in-flight search when a newer one supersedes it (radius
  // change, mode switch, etc.) - otherwise a slow earlier response can land
  // after a faster later one and flash stale results ("flow is confusing").
  const abortRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);
  useEffect(
    () => () => {
      mountedRef.current = false;
      abortRef.current?.abort();
    },
    [],
  );

  const selectedCountry = COUNTRIES.find((c) => c.code === countryCode)!;

  const runSearch = async (params: {
    lat?: number;
    lng?: number;
    radiusKm?: number;
    country?: string;
    city?: string;
  }) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setSearching(true);
    setSearchError(null);
    try {
      const result = await discoverRooms({
        ...params,
        signal: controller.signal,
      });
      if (!mountedRef.current || controller.signal.aborted) return;
      setRooms(result);
      onResults?.(result);
    } catch (err: any) {
      if (err?.name === "AbortError") return;
      if (!mountedRef.current) return;
      setSearchError(err.message || "Could not search for rooms right now");
      setRooms(null);
    } finally {
      if (mountedRef.current && !controller.signal.aborted) setSearching(false);
    }
  };

  // As soon as we have a coordinate fix, search automatically - no extra
  // click needed once permission is granted.
  useEffect(() => {
    if (geo.status === "granted" && geo.coords) {
      void runSearch({ lat: geo.coords.lat, lng: geo.coords.lng, radiusKm });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geo.status, geo.coords?.lat, geo.coords?.lng]);

  const handleRadiusChange = (km: number) => {
    setRadiusKm(km);
    if (geo.coords) {
      void runSearch({
        lat: geo.coords.lat,
        lng: geo.coords.lng,
        radiusKm: km,
      });
    }
  };

  const handleRegionSearch = () => {
    void runSearch({
      country: selectedCountry.name,
      city: city.trim() || undefined,
    });
  };

  const handleJoinRoom = (room: DiscoveredRoomEntry) => {
    setLocation(`/events/${room.eventId}/rooms`);
  };

  const showEnablePrompt =
    !dismissedPrompt &&
    !regionFallbackOpen &&
    geo.status !== "granted" &&
    geo.status !== "requesting";

  return (
    <section className="flex flex-col gap-4" data-testid="section-nearby">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2.5">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-primary" />
          </span>
          <h2 className="font-display text-lg font-extrabold tracking-tight">
            Live near you
          </h2>
        </div>

        {geo.status === "granted" && geo.coords && (
          <div className="flex items-center gap-1.5">
            {RADIUS_OPTIONS_KM.map((km) => (
              <button
                key={km}
                onClick={() => handleRadiusChange(km)}
                data-testid={`button-radius-${km}`}
                className={cn(
                  "px-3 py-1.5 rounded-full text-[11px] font-bold uppercase tracking-wider transition-colors border",
                  radiusKm === km
                    ? "bg-primary text-primary-foreground border-primary"
                    : "bg-secondary/60 text-muted-foreground border-border hover:bg-secondary",
                )}
              >
                {km} km
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Slim, low-friction enable-location prompt - never blocks browsing events below it */}
      {showEnablePrompt && (
        <div className="flex items-center justify-between gap-4 bg-card border border-border border-dashed rounded-2xl px-5 py-4 flex-wrap">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-10 h-10 shrink-0 rounded-xl bg-primary/15 text-primary flex items-center justify-center">
              <Locate className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <p className="font-bold text-sm">
                Find live rooms happening near you
              </p>
              <p className="text-xs text-muted-foreground mt-0.5">
                We only use this to match distance - never stored, never shown
                to anyone.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={geo.request}
              data-testid="button-enable-location"
              className="flex items-center gap-2 px-4 py-2.5 rounded-full text-xs font-black uppercase tracking-wider bg-primary text-primary-foreground hover:brightness-110 transition-all shadow-md shadow-primary/20"
            >
              <MapPin className="w-3.5 h-3.5" />
              Enable location
            </button>
            <button
              onClick={() => setRegionFallbackOpen(true)}
              data-testid="button-pick-region-instead"
              className="px-4 py-2.5 rounded-full text-xs font-bold uppercase tracking-wider text-muted-foreground hover:text-foreground border border-border hover:border-primary/40 transition-all"
            >
              Pick a region
            </button>
            <button
              onClick={() => setDismissedPrompt(true)}
              aria-label="Dismiss"
              data-testid="button-dismiss-nearby-prompt"
              className="p-2 rounded-full text-muted-foreground hover:text-foreground hover:bg-secondary/60 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {geo.status === "requesting" && (
        <div className="flex items-center gap-3 bg-card border border-border rounded-2xl px-5 py-4">
          <RefreshCw className="w-4 h-4 animate-spin text-primary" />
          <p className="text-sm font-semibold text-muted-foreground">
            Requesting location access...
          </p>
        </div>
      )}

      {(geo.status === "denied" ||
        geo.status === "error" ||
        geo.status === "unsupported") &&
        !regionFallbackOpen && (
          <div className="flex items-center justify-between gap-3 bg-destructive/10 border border-destructive/30 rounded-2xl px-5 py-3.5 flex-wrap">
            <p className="text-xs font-semibold text-destructive flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0" />
              {geo.status === "unsupported"
                ? "Your browser doesn't support location access."
                : geo.errorMessage}
            </p>
            <button
              onClick={() => setRegionFallbackOpen(true)}
              className="text-xs font-black uppercase tracking-wider text-destructive underline underline-offset-2 shrink-0"
            >
              Choose a region instead
            </button>
          </div>
        )}

      {/* Compact region fallback - inline, not a separate screen */}
      {regionFallbackOpen && (
        <div className="bg-card border border-border rounded-2xl p-5 flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <p className="text-xs font-extrabold uppercase tracking-[.12em] text-muted-foreground flex items-center gap-2">
              <Globe2 className="w-3.5 h-3.5" /> Browse by region
            </p>
            <button
              onClick={() => setRegionFallbackOpen(false)}
              aria-label="Close"
              className="p-1.5 rounded-full text-muted-foreground hover:text-foreground hover:bg-secondary/60 transition-colors"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-[1fr_1fr_auto] gap-3">
            <div className="relative">
              <select
                value={countryCode}
                onChange={(e) => {
                  setCountryCode(e.target.value);
                  setCity("");
                }}
                className="w-full h-11 rounded-xl border border-input bg-background px-3.5 pr-9 font-semibold text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 transition-all cursor-pointer appearance-none"
              >
                {COUNTRIES.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.name}
                  </option>
                ))}
              </select>
              <ChevronDown className="w-4 h-4 text-muted-foreground absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            </div>
            <input
              value={city}
              onChange={(e) => setCity(e.target.value)}
              placeholder="Any city (optional)"
              className="w-full h-11 rounded-xl border border-input bg-background px-3.5 font-semibold text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 transition-all"
            />
            <button
              onClick={handleRegionSearch}
              disabled={searching}
              className="flex items-center justify-center gap-2 px-5 h-11 rounded-xl text-xs font-black uppercase tracking-wider bg-primary text-primary-foreground hover:brightness-110 transition-all disabled:opacity-60"
            >
              {searching ? (
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Navigation className="w-3.5 h-3.5" />
              )}
              Search
            </button>
          </div>
        </div>
      )}

      {/* Results strip */}
      {searchError && (
        <div className="bg-destructive/10 border border-destructive/30 rounded-2xl px-5 py-3.5 flex gap-3 items-center">
          <AlertTriangle className="w-4 h-4 text-destructive shrink-0" />
          <p className="text-xs text-destructive font-bold">{searchError}</p>
        </div>
      )}

      {searching && !rooms && (
        <div className="flex gap-4 overflow-x-auto pb-1">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="shrink-0 w-64 h-36 rounded-3xl bg-card/50 border border-border/50 animate-pulse"
            />
          ))}
        </div>
      )}

      {!searching && !searchError && rooms && rooms.length === 0 && (
        <div className="bg-card border border-border border-dashed rounded-2xl px-5 py-6 text-center">
          <MapPin className="w-6 h-6 text-muted-foreground mx-auto mb-2 opacity-50" />
          <p className="font-bold text-sm">No open rooms found here yet</p>
          <p className="text-xs text-muted-foreground mt-1">
            Try a wider radius, another region, or join any event below - live
            rooms show up here the moment someone nearby creates one.
          </p>
        </div>
      )}

      {rooms && rooms.length > 0 && (
        <div
          className="flex gap-4 overflow-x-auto pb-1 snap-x snap-mandatory scroll-px-1"
          data-testid="list-nearby-rooms"
        >
          {rooms.map((room) => (
            <button
              key={room.competitionId}
              onClick={() => handleJoinRoom(room)}
              data-testid={`card-nearby-room-${room.competitionId}`}
              className="snap-start text-left shrink-0 w-64 bg-card border border-border rounded-3xl p-4 flex flex-col gap-3 hover:border-primary/40 hover:shadow-md transition-all group"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-[10px] font-mono uppercase tracking-widest text-primary font-black truncate">
                    {room.eventName}
                  </p>
                  <h3 className="font-bold text-sm truncate mt-0.5">
                    {room.roomName}
                  </h3>
                </div>
                {room.visibility === "private" && (
                  <Lock className="w-3.5 h-3.5 text-muted-foreground shrink-0 mt-0.5" />
                )}
              </div>

              <div className="flex items-center gap-2 flex-wrap">
                <span className="flex items-center gap-1.5 text-[11px] font-mono text-muted-foreground bg-secondary/60 px-2 py-1 rounded-full">
                  <Users className="w-3 h-3" />
                  {room.participantCount}/{room.maxParticipants}
                </span>
                {room.distanceKm !== undefined ? (
                  <span className="flex items-center gap-1.5 text-[11px] font-bold text-primary bg-primary/10 px-2 py-1 rounded-full">
                    <Navigation className="w-3 h-3" />
                    {room.distanceKm < 1
                      ? "< 1 km"
                      : `${Math.round(room.distanceKm)} km`}
                  </span>
                ) : (
                  (room.city || room.country) && (
                    <span className="flex items-center gap-1.5 text-[11px] font-bold text-primary bg-primary/10 px-2 py-1 rounded-full truncate">
                      <Globe2 className="w-3 h-3" />
                      {[room.city, room.country].filter(Boolean).join(", ")}
                    </span>
                  )
                )}
              </div>

              <div className="flex items-center justify-between mt-auto pt-1">
                <div className="flex -space-x-2">
                  {(room.participantNames ?? []).slice(0, 4).map((name, i) => (
                    <PlayerAvatar
                      key={i}
                      name={name}
                      src={room.participantAvatars?.[i]}
                      seed={name}
                      size="sm"
                      className="ring-2 ring-card"
                    />
                  ))}
                </div>
                <span className="flex items-center gap-1 text-[10px] font-black uppercase tracking-wider text-primary group-hover:gap-1.5 transition-all">
                  Join
                  <ArrowRight className="w-3 h-3" />
                </span>
              </div>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
