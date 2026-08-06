import React from "react";
import { cn } from "@/lib/utils";
import { CheckCircle2 } from "lucide-react";

interface SetTrackerProps {
  currentSet: number;
  targetSets: number;
  className?: string;
}

export function SetTracker({
  currentSet,
  targetSets,
  className,
}: SetTrackerProps) {
  const sets = Array.from({ length: targetSets }, (_, i) => i + 1);

  return (
    <div
      className={cn(
        "bg-card border border-card-border p-4 rounded-xl flex flex-col gap-3",
        className,
      )}
    >
      <div className="flex justify-between items-center text-sm font-semibold uppercase tracking-widest text-muted-foreground">
        <span>Session Progress</span>
        <span>
          Set {Math.min(currentSet, targetSets)} / {targetSets}
        </span>
      </div>

      <div className="flex gap-2">
        {sets.map((set) => {
          const isCompleted = set < currentSet;
          const isCurrent = set === currentSet;

          return (
            <div
              key={set}
              className={cn(
                "h-2 flex-1 rounded-full transition-all duration-300",
                isCompleted
                  ? "bg-primary shadow-[0_0_8px_hsl(var(--primary)/0.5)]"
                  : isCurrent
                    ? "bg-accent animate-pulse"
                    : "bg-secondary",
              )}
            />
          );
        })}
      </div>
    </div>
  );
}
