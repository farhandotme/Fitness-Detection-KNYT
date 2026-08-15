import React from "react";
import { Link, useLocation } from "wouter";
import { clearAdminSession, getAdminUsername } from "@/lib/adminApi";
import { LayoutDashboard, LogOut, Radio, ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";

export function AdminShell({ children }: { children: React.ReactNode }) {
  const [, setLocation] = useLocation();
  const [location] = useLocation();
  const username = getAdminUsername();

  const handleLogout = () => {
    clearAdminSession();
    setLocation("/admin/login");
  };

  const navItems = [
    {
      href: "/admin",
      label: "Dashboard",
      icon: LayoutDashboard,
      active: location === "/admin",
    },
  ];

  return (
    <div className="min-h-dvh bg-background text-foreground md:flex">
      {/* Sidebar - desktop */}
      <aside className="hidden md:flex md:w-64 md:flex-col md:fixed md:inset-y-0 border-r border-card-border bg-card/40">
        <div className="px-6 pt-7 pb-6">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center shrink-0">
              <Radio className="w-4 h-4 text-primary-foreground" />
            </div>
            <div>
              <p className="font-display font-extrabold tracking-tight text-sm leading-none">
                KNYT Ops
              </p>
              <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted-foreground mt-1">
                Control Console
              </p>
            </div>
          </div>
        </div>

        <nav className="flex-1 px-3 space-y-1">
          {navItems.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-bold transition-colors",
                item.active
                  ? "bg-primary text-primary-foreground shadow-lg shadow-primary/20"
                  : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
              )}
            >
              <item.icon className="w-4 h-4" />
              {item.label}
            </Link>
          ))}

          <a
            href="/events"
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-bold text-muted-foreground hover:bg-secondary/60 hover:text-foreground transition-colors"
          >
            <ArrowUpRight className="w-4 h-4" />
            View participant site
          </a>
        </nav>

        <div className="px-3 pb-5 pt-3 border-t border-card-border/60">
          <div className="px-3 py-2.5 mb-1">
            <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted-foreground">
              Signed in
            </p>
            <p className="text-sm font-bold truncate">{username ?? "Admin"}</p>
          </div>
          <button
            onClick={handleLogout}
            data-testid="button-admin-logout"
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-bold text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-colors"
          >
            <LogOut className="w-4 h-4" />
            Log out
          </button>
        </div>
      </aside>

      {/* Top bar - mobile */}
      <header className="md:hidden sticky top-0 z-30 flex items-center justify-between px-4 h-14 border-b border-card-border bg-background/95 backdrop-blur">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-primary flex items-center justify-center">
            <Radio className="w-3.5 h-3.5 text-primary-foreground" />
          </div>
          <span className="font-display font-extrabold text-sm tracking-tight">
            KNYT Ops
          </span>
        </div>
        <button
          onClick={handleLogout}
          data-testid="button-admin-logout-mobile"
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-bold text-muted-foreground bg-secondary/60"
        >
          <LogOut className="w-3.5 h-3.5" />
          Log out
        </button>
      </header>

      <main className="flex-1 md:pl-64 min-w-0">
        <div className="max-w-6xl mx-auto p-4 md:p-8">{children}</div>
      </main>
    </div>
  );
}
