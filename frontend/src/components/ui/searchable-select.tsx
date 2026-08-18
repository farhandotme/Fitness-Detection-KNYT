import React, { useMemo, useState } from "react";
import { Check, ChevronDown } from "lucide-react";
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
import { cn } from "@/lib/utils";

export interface SearchableSelectOption {
  value: string;
  label: string;
}

interface SearchableSelectProps {
  options: SearchableSelectOption[];
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  searchPlaceholder?: string;
  emptyText?: string;
  disabled?: boolean;
  className?: string;
  /** Caps how many filtered rows render at once - keeps large lists (e.g. thousands of cities) fast. */
  maxResults?: number;
}

/**
 * A closed-set, search-to-filter dropdown (Popover + cmdk Command).
 * Unlike a plain text input, the user can only ever pick one of the
 * provided `options` - typing just narrows the visible list.
 */
export function SearchableSelect({
  options,
  value,
  onChange,
  placeholder,
  searchPlaceholder = "Search...",
  emptyText = "No matches found.",
  disabled = false,
  className,
  maxResults = 100,
}: SearchableSelectProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const selected = useMemo(
    () => options.find((o) => o.value === value),
    [options, value],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const source = q
      ? options.filter((o) => o.label.toLowerCase().includes(q))
      : options;
    return source.slice(0, maxResults);
  }, [options, query, maxResults]);

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
          disabled={disabled}
          className={cn(
            "w-full h-11 rounded-xl border border-input bg-background px-3.5 pr-9 font-semibold text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 transition-all relative text-left disabled:opacity-50 disabled:cursor-not-allowed",
            !selected && "text-muted-foreground font-medium",
            className,
          )}
        >
          <span className="block truncate">
            {selected ? selected.label : placeholder}
          </span>
          <ChevronDown className="w-4 h-4 text-muted-foreground absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-[--radix-popover-trigger-width] p-0"
        align="start"
      >
        <Command shouldFilter={false}>
          <CommandInput
            value={query}
            onValueChange={setQuery}
            placeholder={searchPlaceholder}
          />
          <CommandList className="max-h-64">
            <CommandEmpty>{emptyText}</CommandEmpty>
            <CommandGroup>
              {filtered.map((option) => (
                <CommandItem
                  key={option.value}
                  value={option.value}
                  onSelect={() => {
                    onChange(option.value);
                    setOpen(false);
                    setQuery("");
                  }}
                >
                  <Check
                    className={cn(
                      "mr-2 h-4 w-4",
                      value === option.value ? "opacity-100" : "opacity-0",
                    )}
                  />
                  <span className="truncate">{option.label}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
