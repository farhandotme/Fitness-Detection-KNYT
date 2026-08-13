import React from "react";
import { cn } from "@/lib/utils";

interface StatCardProps {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  accent?: "default" | "primary" | "destructive";
  hint?: string;
}

export function StatCard({
  label,
  value,
  icon,
  accent = "default",
  hint,
}: StatCardProps) {
  return (
    <div className="bg-card border border-card-border rounded-3xl p-5 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-black uppercase tracking-[.16em] text-muted-foreground">
          {label}
        </span>
        <div
          className={cn(
            "w-8 h-8 rounded-xl flex items-center justify-center shrink-0",
            accent === "primary" && "bg-primary/15 text-primary",
            accent === "destructive" && "bg-destructive/10 text-destructive",
            accent === "default" && "bg-secondary text-muted-foreground",
          )}
        >
          {icon}
        </div>
      </div>
      <span className="text-3xl font-black tracking-tight tabular-nums">
        {value}
      </span>
      {hint && (
        <span className="text-xs text-muted-foreground font-medium">
          {hint}
        </span>
      )}
    </div>
  );
}
