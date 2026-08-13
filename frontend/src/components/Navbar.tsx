import { Link, useLocation } from "wouter";
import { Activity, Settings, Trophy } from "lucide-react";
import { cn } from "@/lib/utils";

interface NavbarProps {
  onSettingsClick?: () => void;
}

export function Navbar({ onSettingsClick }: NavbarProps) {
  const [location] = useLocation();
  const isEvents = location.startsWith("/events") || location.startsWith("/competitions");

  return (
    <header className="sticky top-0 z-50 bg-background/80 backdrop-blur-xl border-b border-border p-4">
      <div className="max-w-6xl mx-auto flex items-center justify-between gap-4">
        <Link href="/" className="flex items-center gap-3 shrink-0">
          <div className="w-10 h-10 bg-primary rounded-2xl flex items-center justify-center text-primary-foreground font-black text-xl shadow-lg shadow-primary/20">
            <Activity className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-xl font-bold uppercase tracking-tight leading-none">
              Fitness Coach
            </h1>
            <p className="text-xs text-muted-foreground uppercase tracking-widest">
              Real-time Form Tracking
            </p>
          </div>
        </Link>

        <nav className="flex items-center gap-2">
          <Link
            href="/events"
            data-testid="link-nav-events"
            className={cn(
              "flex items-center gap-2 px-4 py-2.5 rounded-full text-sm font-bold uppercase tracking-wider transition-colors",
              isEvents
                ? "bg-foreground text-background shadow-lg"
                : "bg-secondary/70 text-muted-foreground hover:bg-secondary",
            )}
          >
            <Trophy className="w-4 h-4" />
            Events
          </Link>
          {onSettingsClick && (
            <button
              onClick={onSettingsClick}
              data-testid="button-settings"
              className="p-2.5 bg-secondary/70 hover:bg-secondary rounded-full transition-colors"
              aria-label="Connection settings"
            >
              <Settings className="w-5 h-5 text-muted-foreground" />
            </button>
          )}
        </nav>
      </div>
    </header>
  );
}
