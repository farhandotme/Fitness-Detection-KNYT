import React, { useState } from "react";
import { Link, useLocation } from "wouter";
import {
  getAdminToken,
  loginAdmin,
  registerAdmin,
  saveAdminSession,
} from "@/lib/adminApi";
import { ArrowLeft, AlertTriangle, Radio, LogIn, UserPlus } from "lucide-react";

type Tab = "login" | "register";

export function AdminLoginPage() {
  const [, setLocation] = useLocation();
  const [tab, setTab] = useState<Tab>("login");

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [signupCode, setSignupCode] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Already logged in? Skip straight to the dashboard.
  React.useEffect(() => {
    if (getAdminToken()) setLocation("/admin");
  }, [setLocation]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!username.trim() || !password) {
      setError("Username and password are required");
      return;
    }
    setSubmitting(true);
    try {
      const result =
        tab === "login"
          ? await loginAdmin(username.trim(), password)
          : await registerAdmin(username.trim(), password, signupCode.trim());
      saveAdminSession(result.token, result.username);
      setLocation("/admin");
    } catch (err: any) {
      setError(err.message || "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-dvh bg-background text-foreground flex flex-col">
      <header className="px-4 md:px-8 pt-6">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
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
      </header>

      <main className="max-w-md w-full mx-auto p-4 mt-10 flex-1">
        <Link
          href="/events"
          className="inline-flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors mb-6"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to events
        </Link>

        <div className="bg-card border border-card-border rounded-4xl p-6 md:p-8 shadow-sm">
          <div className="flex items-center gap-2 text-primary text-[10px] font-mono uppercase tracking-[0.25em] font-bold mb-4">
            <Radio className="w-3.5 h-3.5" /> Admin access
          </div>
          <h1 className="font-display text-2xl md:text-3xl font-extrabold tracking-tight mb-1">
            {tab === "login" ? "Log in" : "Create an admin account"}
          </h1>
          <p className="text-sm text-muted-foreground mb-6">
            Admins create and manage events. Everyone else just joins from{" "}
            <Link href="/events" className="text-primary hover:underline">
              /events
            </Link>
            .
          </p>

          <div className="flex gap-2 mb-6 p-1 bg-secondary/60 rounded-2xl">
            <button
              type="button"
              onClick={() => setTab("login")}
              data-testid="tab-admin-login"
              className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl text-xs font-black uppercase tracking-wider transition-colors ${
                tab === "login"
                  ? "bg-foreground text-background"
                  : "text-muted-foreground"
              }`}
            >
              <LogIn className="w-3.5 h-3.5" /> Login
            </button>
            <button
              type="button"
              onClick={() => setTab("register")}
              data-testid="tab-admin-register"
              className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl text-xs font-black uppercase tracking-wider transition-colors ${
                tab === "register"
                  ? "bg-foreground text-background"
                  : "text-muted-foreground"
              }`}
            >
              <UserPlus className="w-3.5 h-3.5" /> Register
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-bold uppercase tracking-[.16em] text-muted-foreground mb-2">
                Username
              </label>
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                data-testid="input-admin-username"
                className="w-full h-12 rounded-2xl border border-input bg-background px-4 font-semibold text-foreground outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/15"
                autoFocus
              />
            </div>

            <div>
              <label className="block text-xs font-bold uppercase tracking-[.16em] text-muted-foreground mb-2">
                Password
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                data-testid="input-admin-password"
                className="w-full h-12 rounded-2xl border border-input bg-background px-4 font-semibold text-foreground outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/15"
              />
              {tab === "register" && (
                <p className="text-xs text-muted-foreground mt-1.5">
                  At least 8 characters.
                </p>
              )}
            </div>

            {tab === "register" && (
              <div>
                <label className="block text-xs font-bold uppercase tracking-[.16em] text-muted-foreground mb-2">
                  Signup code
                </label>
                <input
                  value={signupCode}
                  onChange={(e) => setSignupCode(e.target.value)}
                  data-testid="input-admin-signup-code"
                  className="w-full h-12 rounded-2xl border border-input bg-background px-4 font-semibold text-foreground outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/15"
                  placeholder="ADMIN_SIGNUP_CODE from the backend .env"
                />
              </div>
            )}

            {error && (
              <div className="bg-destructive/10 border border-destructive/30 rounded-2xl p-4 flex gap-2.5 items-start">
                <AlertTriangle className="w-4 h-4 text-destructive shrink-0 mt-0.5" />
                <p className="text-sm text-destructive font-semibold">
                  {error}
                </p>
              </div>
            )}

            <button
              type="submit"
              disabled={submitting}
              data-testid="button-admin-submit"
              className="w-full bg-primary text-primary-foreground py-4 rounded-2xl font-black uppercase tracking-wider hover:brightness-110 active:scale-[0.98] transition-all shadow-xl shadow-primary/20 disabled:opacity-50"
            >
              {submitting
                ? "Please wait..."
                : tab === "login"
                  ? "Log in"
                  : "Create account"}
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}
