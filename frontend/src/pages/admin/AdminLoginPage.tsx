import React, { useState } from "react";
import { Link, useLocation } from "wouter";
import {
  getAdminToken,
  loginAdmin,
  registerAdmin,
  saveAdminSession,
} from "@/lib/adminApi";
import {
  ArrowLeft,
  AlertOctagon,
  Radio,
  LogIn,
  UserPlus,
  Lock,
  User,
  KeyRound,
  Eye,
  EyeOff,
  Loader2,
  ShieldCheck,
  X,
  Sparkles,
} from "lucide-react";

type Tab = "login" | "register";

export function AdminLoginPage() {
  const [, setLocation] = useLocation();
  const [tab, setTab] = useState<Tab>("login");

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [signupCode, setSignupCode] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [shake, setShake] = useState(false);

  // Already logged in? Skip straight to the dashboard.
  React.useEffect(() => {
    if (getAdminToken()) setLocation("/admin");
  }, [setLocation]);

  const triggerError = (msg: string) => {
    setError(msg);
    setShake(true);
    setTimeout(() => setShake(false), 400); // Sharp 0.4s duration
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!username.trim() || !password) {
      triggerError("Username and password are required");
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
      triggerError(err.message || "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="relative min-h-dvh bg-background text-foreground flex flex-col justify-between overflow-hidden selection:bg-primary/20 selection:text-primary font-sans">
      {/* 
        Inline Shake Animation 
        Jerks LEFT (-10px), then RIGHT (10px), then smaller left/right, ending in MIDDLE (0)
      */}
      <style>{`
        @keyframes inlineShake {
          0%, 100% { transform: translateX(0); }
          20% { transform: translateX(-10px); }
          40% { transform: translateX(10px); }
          60% { transform: translateX(-5px); }
          80% { transform: translateX(5px); }
        }
        .animate-inline-shake {
          animation: inlineShake 0.4s cubic-bezier(0.36, 0.07, 0.19, 0.97) both;
        }
      `}</style>

      {/* Minimalist Ambient Glows */}
      <div className="pointer-events-none absolute -top-32 left-1/2 -translate-x-1/2 w-150 h-150 bg-primary/5 blur-[100px] rounded-full opacity-50" />

      {/* Background Subtle Dot Pattern */}
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(var(--border)_1px,transparent_1px)] bg-size-[24px_24px] opacity-[0.15]" />

      {/* Header */}
      <header className="relative z-10 px-6 py-6 max-w-7xl w-full mx-auto flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="relative flex items-center justify-center w-10 h-10 rounded-xl bg-primary/10 border border-primary/20 text-primary shadow-sm">
            <Radio className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-display font-extrabold tracking-tight text-base leading-none">
                KNYT Ops
              </span>
              <span className="text-[9px] font-mono uppercase px-1.5 py-0.5 rounded-md bg-primary/10 text-primary font-bold border border-primary/20">
                PRO CONSOLE
              </span>
            </div>
            <p className="text-[10px] font-medium text-muted-foreground mt-1">
              Operational Control Station
            </p>
          </div>
        </div>

        <Link
          href="/events"
          className="inline-flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-semibold text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-all border border-transparent hover:border-border"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">Back to events</span>
        </Link>
      </header>

      {/* Main Container - Sharper, Professional Apple-like Card */}
      <main className="relative z-10 max-w-115 w-full mx-auto p-4 md:p-6 my-auto flex flex-col justify-center">
        <div className="relative bg-card border border-border/60 rounded-2xl p-7 md:p-8 shadow-xl shadow-black/5 overflow-hidden transition-all duration-300">
          {/* Subtle Top Badges */}
          <div className="flex items-center justify-between mb-8">
            <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-primary/10 text-primary text-[10px] font-bold uppercase tracking-wider border border-primary/20">
              <ShieldCheck className="w-3.5 h-3.5" /> Secure Access
            </div>
            <div className="flex items-center gap-1.5 text-[10px] font-mono text-muted-foreground uppercase tracking-wider bg-secondary/50 px-2.5 py-1 rounded-lg border border-border/50">
              <Sparkles className="w-3 h-3 text-primary" />
              <span>{tab === "login" ? "AUTH_SESSION" : "NEW_REGISTER"}</span>
            </div>
          </div>

          <h1 className="font-display text-2xl md:text-3xl font-bold tracking-tight mb-2">
            {tab === "login" ? "Welcome back" : "Create account"}
          </h1>
          <p className="text-sm text-muted-foreground mb-8 leading-relaxed">
            Admins create and manage events. Everyone else joins from{" "}
            <Link
              href="/events"
              className="text-primary font-medium hover:underline inline-flex items-center"
            >
              /events
            </Link>
            .
          </p>

          {/* iOS-Style Segmented Control */}
          <div className="flex p-1 bg-secondary/60 rounded-xl mb-8 border border-border/40">
            <button
              type="button"
              onClick={() => {
                setTab("login");
                setError(null);
              }}
              data-testid="tab-admin-login"
              className={`flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-sm font-semibold transition-all duration-200 ${
                tab === "login"
                  ? "bg-background text-foreground shadow-sm border border-border/50"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Login
            </button>
            <button
              type="button"
              onClick={() => {
                setTab("register");
                setError(null);
              }}
              data-testid="tab-admin-register"
              className={`flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-sm font-semibold transition-all duration-200 ${
                tab === "register"
                  ? "bg-background text-foreground shadow-sm border border-border/50"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Register
            </button>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Username */}
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-muted-foreground ml-1">
                Username
              </label>
              <div className="relative flex items-center group">
                <User className="absolute left-3.5 w-4 h-4 text-muted-foreground group-focus-within:text-primary transition-colors pointer-events-none" />
                <input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  data-testid="input-admin-username"
                  placeholder="admin_username"
                  className="w-full h-12 pl-10 pr-4 rounded-xl border border-input bg-background/50 font-medium text-foreground text-sm placeholder:text-muted-foreground/40 outline-none transition-all duration-200 focus:border-primary focus:ring-2 focus:ring-primary/10 focus:bg-background"
                  autoFocus
                />
              </div>
            </div>

            {/* Password */}
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-muted-foreground ml-1">
                Password
              </label>
              <div className="relative flex items-center group">
                <Lock className="absolute left-3.5 w-4 h-4 text-muted-foreground group-focus-within:text-primary transition-colors pointer-events-none" />
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  data-testid="input-admin-password"
                  placeholder="••••••••"
                  className="w-full h-12 pl-10 pr-11 rounded-xl border border-input bg-background/50 font-medium text-foreground text-sm placeholder:text-muted-foreground/40 outline-none transition-all duration-200 focus:border-primary focus:ring-2 focus:ring-primary/10 focus:bg-background"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 text-muted-foreground hover:text-foreground transition-colors p-1.5 rounded-lg focus:outline-none"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? (
                    <EyeOff className="w-4 h-4" />
                  ) : (
                    <Eye className="w-4 h-4" />
                  )}
                </button>
              </div>
              {tab === "register" && (
                <p className="text-[11px] text-muted-foreground pl-1 font-medium">
                  At least 8 characters required.
                </p>
              )}
            </div>

            {/* Signup Code */}
            {tab === "register" && (
              <div className="space-y-1.5 transition-all">
                <label className="block text-xs font-semibold text-muted-foreground ml-1">
                  Signup code
                </label>
                <div className="relative flex items-center group">
                  <KeyRound className="absolute left-3.5 w-4 h-4 text-muted-foreground group-focus-within:text-primary transition-colors pointer-events-none" />
                  <input
                    value={signupCode}
                    onChange={(e) => setSignupCode(e.target.value)}
                    data-testid="input-admin-signup-code"
                    className="w-full h-12 pl-10 pr-4 rounded-xl border border-input bg-background/50 font-medium text-foreground text-sm placeholder:text-muted-foreground/40 outline-none transition-all duration-200 focus:border-primary focus:ring-2 focus:ring-primary/10 focus:bg-background"
                    placeholder="Enter admin code"
                  />
                </div>
                <p className="text-[11px] text-muted-foreground/80 pl-1 font-medium">
                  Found in backend environment variables.
                </p>
              </div>
            )}

            {/* Inline Error Toast - Positioned directly above the submit button */}
            {error && (
              <div
                className={`w-full mt-3 px-3 py-2 bg-red-50/90 backdrop-blur-xl border border-red-200 rounded-xl shadow-sm flex items-center gap-2.5 transition-all duration-200 ${
                  shake ? "animate-inline-shake" : ""
                }`}
              >
                <div className="w-7 h-7 rounded-full bg-red-100 flex items-center justify-center shrink-0">
                  <AlertOctagon className="w-3.5 h-3.5 text-red-500" />
                </div>

                <p className="flex-1 min-w-0 text-[10px] font-semibold text-red-700 truncate">
                  {error}
                </p>

                <button
                  type="button"
                  onClick={() => setError(null)}
                  className="w-6 h-6 rounded-full bg-red-100 hover:bg-red-200 flex items-center justify-center shrink-0 transition-colors"
                >
                  <X className="w-3 h-3 text-red-500" />
                </button>
              </div>
            )}

            {/* Submit Button */}
            <div className={error ? "mt-2" : "mt-6"}>
              <button
                type="submit"
                disabled={submitting}
                data-testid="button-admin-submit"
                className="w-full bg-primary text-primary-foreground h-12 rounded-xl font-semibold text-sm flex items-center justify-center gap-2 hover:opacity-90 active:scale-[0.98] transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
              >
                {submitting ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Processing...</span>
                  </>
                ) : tab === "login" ? (
                  <>
                    <LogIn className="w-4 h-4" />
                    <span>Log in</span>
                  </>
                ) : (
                  <>
                    <UserPlus className="w-4 h-4" />
                    <span>Create account</span>
                  </>
                )}
              </button>
            </div>
          </form>
        </div>
      </main>

      {/* Footer */}
      <footer className="relative z-10 px-6 py-6 text-center">
        <p className="text-[10px] font-medium text-muted-foreground/60 uppercase tracking-widest">
          KNYT Ops &bull; Authorized Access
        </p>
      </footer>
    </div>
  );
}
