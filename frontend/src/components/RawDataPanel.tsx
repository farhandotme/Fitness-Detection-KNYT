import React, { useState } from "react";
import { ChevronDown, ChevronUp, Code2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface RawDataPanelProps {
  data: any;
}

export function RawDataPanel({ data }: RawDataPanelProps) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="bg-card border border-card-border rounded-xl overflow-hidden mt-4">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between p-3 bg-secondary/30 hover:bg-secondary/50 transition-colors"
      >
        <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          <Code2 className="w-4 h-4" /> Live WS Data
        </div>
        {isOpen ? (
          <ChevronUp className="w-4 h-4 text-muted-foreground" />
        ) : (
          <ChevronDown className="w-4 h-4 text-muted-foreground" />
        )}
      </button>

      <div
        className={cn(
          "grid transition-all duration-300 ease-in-out",
          isOpen ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0",
        )}
      >
        <div className="overflow-hidden">
          <pre className="p-4 text-xs font-mono text-muted-foreground overflow-auto max-h-75 whitespace-pre-wrap break-all custom-scrollbar">
            {JSON.stringify(data, null, 2)}
          </pre>
        </div>
      </div>
    </div>
  );
}
