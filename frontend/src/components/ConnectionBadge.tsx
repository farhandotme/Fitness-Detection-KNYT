import React from "react";
import { Wifi, WifiOff } from "lucide-react";
import { cn } from "@/lib/utils";

interface ConnectionBadgeProps {
  connected: boolean;
  error?: string | null;
  className?: string;
}

export function ConnectionBadge({
  connected,
  error,
  className,
}: ConnectionBadgeProps) {
  return (
    <div
      className={cn(
        "inline-flex items-center gap-2 px-2.5 py-1 rounded-full text-xs font-medium tracking-wide",
        connected
          ? "bg-primary/10 text-primary border border-primary/20"
          : "bg-destructive/10 text-destructive border border-destructive/20",
        className,
      )}
    >
      {connected ? (
        <Wifi className="w-3 h-3" />
      ) : (
        <WifiOff className="w-3 h-3" />
      )}
      {connected ? "Live Data" : error ? "Error" : "Disconnected"}
    </div>
  );
}
