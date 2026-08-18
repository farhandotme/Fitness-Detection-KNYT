import React, { useEffect, useRef, useState } from "react";
import { ChevronDown, Locate, MapPin, RefreshCw } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { searchPlaces, type GeoSearchResult } from "@/lib/geocoding";
import {
  addRecentLocation,
  getRecentLocations,
  type RecentLocation,
} from "@/lib/recentLocations";
import { cn } from "@/lib/utils";

export interface PickedLocation {
  label: string;
  lat: number;
  lng: number;
}

interface LocationPickerProps {
  /** Label to show while a picked/GPS location is active, e.g. "Dispur, Guwahati". */
  label: string | null;
  /** True while GPS or reverse-geocoding is still resolving the current fix. */
  loading?: boolean;
  /** True when the label shown is coming from GPS rather than a manual pick. */
  isCurrentLocation?: boolean;
  /** Re-requests the browser's GPS location and clears any manual override. */
  onUseCurrentLocation: () => void;
  /** User picked a specific place from search or recents. */
  onSelectLocation: (location: PickedLocation) => void;
  className?: string;
}

/**
 * OLX-style location chip: shows the active location and opens a popover
 * to either re-use GPS ("Use current location") or search for and pick a
 * specific place, with recently-picked locations offered for quick re-use.
 */
export function LocationPicker({
  label,
  loading = false,
  isCurrentLocation = false,
  onUseCurrentLocation,
  onSelectLocation,
  className,
}: LocationPickerProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<GeoSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [recent, setRecent] = useState<RecentLocation[]>([]);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (open) setRecent(getRecentLocations());
  }, [open]);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    abortRef.current?.abort();

    const q = query.trim();
    if (!q) {
      setResults([]);
      setSearching(false);
      return;
    }

    setSearching(true);
    debounceRef.current = setTimeout(() => {
      const controller = new AbortController();
      abortRef.current = controller;
      searchPlaces(q, controller.signal)
        .then((found) => {
          setResults(found);
          setSearching(false);
        })
        .catch((err) => {
          if (err?.name === "AbortError") return;
          setResults([]);
          setSearching(false);
        });
    }, 350);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query]);

  const handleSelect = (location: PickedLocation) => {
    addRecentLocation(location);
    onSelectLocation(location);
    setOpen(false);
    setQuery("");
  };

  const handleUseCurrent = () => {
    onUseCurrentLocation();
    setOpen(false);
    setQuery("");
  };

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setQuery("");
      }}
    >
      <PopoverTrigger asChild>
        <button
          type="button"
          data-testid="button-location-picker"
          className={cn(
            "flex items-center gap-2 pl-3.5 pr-3 h-10 rounded-full border border-input bg-background font-bold text-sm max-w-[280px] hover:border-primary/50 transition-colors",
            className,
          )}
        >
          <MapPin className="w-3.5 h-3.5 text-primary shrink-0" />
          {loading ? (
            <span className="flex items-center gap-1.5 text-muted-foreground font-semibold">
              <RefreshCw className="w-3 h-3 animate-spin" />
              Locating...
            </span>
          ) : (
            <span className="truncate">{label ?? "Set your location"}</span>
          )}
          <ChevronDown className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-0" align="start">
        <Command shouldFilter={false}>
          <CommandInput
            value={query}
            onValueChange={setQuery}
            placeholder="Search area, street, city..."
          />
          <CommandList className="max-h-72">
            <CommandGroup className="pb-2">
              <CommandItem
                onSelect={handleUseCurrent}
                data-testid="option-use-current-location"
                // Deliberately styled rather than left to rely on the
                // generic hover/selected tint, so it always reads clearly
                // as the primary action at the top of the list.
                className="bg-primary/10 border border-primary/20 data-[selected=true]:bg-primary/20 mb-1"
              >
                <span className="w-8 h-8 rounded-full bg-primary/15 flex items-center justify-center shrink-0">
                  <Locate className="text-primary" />
                </span>
                <div className="flex flex-col min-w-0">
                  <span className="font-bold text-foreground">
                    Use current location
                  </span>
                  {isCurrentLocation && label && (
                    <span className="text-xs text-muted-foreground truncate">
                      {label}
                    </span>
                  )}
                </div>
              </CommandItem>
            </CommandGroup>

            {!query && recent.length > 0 && (
              <CommandGroup heading="Recent locations">
                {recent.map((loc) => (
                  <CommandItem
                    key={`${loc.lat},${loc.lng}`}
                    onSelect={() => handleSelect(loc)}
                  >
                    <MapPin className="text-muted-foreground shrink-0" />
                    <span className="truncate">{loc.label}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}

            {query && (
              <CommandGroup heading={searching ? "Searching..." : "Results"}>
                {results.map((result) => (
                  <CommandItem
                    key={`${result.lat},${result.lng}`}
                    onSelect={() => handleSelect(result)}
                  >
                    <MapPin className="text-muted-foreground shrink-0" />
                    <span className="truncate">{result.label}</span>
                  </CommandItem>
                ))}
                {!searching && results.length === 0 && (
                  <CommandEmpty>No matches found.</CommandEmpty>
                )}
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
