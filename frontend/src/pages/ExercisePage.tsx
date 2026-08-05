import React, { useState } from "react";
import { useRoute, useLocation } from "wouter";
import { getExerciseById } from "@/config/exercises";
import {
  ArrowLeft,
  Target,
  RefreshCw,
  Clock,
  Play,
  ShieldCheck,
  Sparkles,
  Minus,
  Plus,
} from "lucide-react";
import { Link } from "wouter";

export function ExercisePage() {
  const [match, params] = useRoute("/exercise/:id");
  const [, setLocation] = useLocation();

  const id = params?.id;
  const exercise = id ? getExerciseById(id) : undefined;

  const [target, setTarget] = useState(exercise?.defaultTarget || 10);
  const [sets, setSets] = useState(exercise?.defaultSets || 3);
  const [rest, setRest] = useState(exercise?.defaultRestSeconds || 45);

  if (!match || !exercise) {
    return (
      <div className="p-8 text-center text-destructive">
        Exercise not found.
      </div>
    );
  }

  const handleStart = () => {
    // Navigate to session passing params in URL state or query
    // Simple way with Wouter: use URL search params
    setLocation(
      `/exercise/${exercise.id}/session?target=${target}&sets=${sets}&rest=${rest}`,
    );
  };

  const clampNumber = (value: string, min: number, max: number) => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return min;
    return Math.min(Math.max(Math.round(parsed), min), max);
  };

  const NumberField = ({
    label,
    value,
    min,
    max,
    step = 1,
    onChange,
    suffix,
    icon,
  }: {
    label: string;
    value: number;
    min: number;
    max: number;
    step?: number;
    onChange: (value: number) => void;
    suffix: string;
    icon: React.ReactNode;
  }) => (
    <div className="rounded-2xl border border-border bg-background/60 p-4 transition-colors focus-within:border-primary/55">
      <div className="mb-3 flex items-center justify-between">
        <label className="flex items-center gap-2 text-xs font-bold uppercase tracking-[.16em] text-muted-foreground">
          {icon}
          {label}
        </label>
        <span className="font-mono text-[10px] uppercase tracking-widest text-primary/70">
          {min}–{max}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          aria-label={`Decrease ${label}`}
          onClick={() => onChange(clampNumber(String(value - step), min, max))}
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-border bg-secondary text-muted-foreground transition hover:border-primary/45 hover:text-primary"
        >
          <Minus className="h-4 w-4" />
        </button>
        <div className="relative flex-1">
          <input
            type="number"
            min={min}
            max={max}
            step={step}
            value={value}
            onChange={(event) =>
              onChange(clampNumber(event.target.value, min, max))
            }
            className="h-12 w-full rounded-xl border border-input bg-card px-4 pr-16 text-center font-mono text-xl font-bold text-foreground outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/15"
            aria-label={label}
          />
          <span className="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2 font-mono text-xs uppercase tracking-widest text-muted-foreground">
            {suffix}
          </span>
        </div>
        <button
          type="button"
          aria-label={`Increase ${label}`}
          onClick={() => onChange(clampNumber(String(value + step), min, max))}
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-border bg-secondary text-muted-foreground transition hover:border-primary/45 hover:text-primary"
        >
          <Plus className="h-4 w-4" />
        </button>
      </div>
    </div>
  );

  return (
    <div className="min-h-dvh bg-background text-foreground">
      {/* Header */}
      <header className="sticky top-0 z-50 bg-background/80 backdrop-blur-xl border-b border-border p-4">
        <div className="max-w-3xl mx-auto flex items-center gap-4">
          <Link
            href="/"
            data-testid="link-back-home"
            className="p-2.5 bg-secondary/70 hover:bg-secondary rounded-full transition-colors"
          >
            <ArrowLeft className="w-5 h-5 text-foreground" />
          </Link>
          <h1 className="text-sm font-bold uppercase tracking-[.2em] text-muted-foreground">
            Session setup
          </h1>
        </div>
      </header>

      <main className="max-w-4xl mx-auto p-4 mt-6">
        {/* Header Hero */}
        <div className="bg-card border border-card-border rounded-4xl p-6 md:p-10 mb-6 flex flex-col md:flex-row gap-8 items-center md:items-stretch overflow-hidden relative">
          <div className="w-full md:w-1/2 min-h-52.5 rounded-2xl overflow-hidden relative bg-[#173b42]">
            {exercise.imageUrl ? (
              <img
                src={exercise.imageUrl}
                alt=""
                className="absolute inset-0 w-full h-full object-cover opacity-85"
              />
            ) : (
              <div className="absolute inset-0 bg-[radial-gradient(circle_at_70%_20%,hsl(var(--accent)/.7),transparent_30%),linear-gradient(135deg,#173b42,#2d6e6b)]" />
            )}
            <div className="absolute inset-0 bg-linear-to-t from-[#173b42]/80 to-transparent" />
            <div className="absolute left-5 bottom-5 text-[#f2f5ed]">
              <div className="text-[10px] uppercase tracking-[.24em] text-[#f2b35b] font-bold">
                Today's focus
              </div>
              <div className="text-2xl font-display font-extrabold mt-1">
                {exercise.mode === "reps"
                  ? "Controlled strength"
                  : "Steady endurance"}
              </div>
            </div>
          </div>
          <div className="flex-1 self-center">
            <div className="flex items-center gap-2 text-primary text-xs uppercase tracking-[.2em] font-bold mb-4">
              <Sparkles className="w-4 h-4" /> Guided session
            </div>
            <h2 className="text-4xl md:text-5xl font-black tracking-tighter leading-none mb-3">
              {exercise.name}
            </h2>
            <p className="text-lg text-muted-foreground mb-6 max-w-md">
              {exercise.tagline}
            </p>

            <div className="flex flex-wrap justify-center gap-3">
              <span className="px-4 py-1.5 text-xs font-black uppercase tracking-widest rounded-lg bg-secondary text-secondary-foreground">
                {exercise.category.replace("_", " ")}
              </span>
              <span className="px-4 py-1.5 text-xs font-black uppercase tracking-widest rounded-lg bg-secondary text-secondary-foreground">
                {exercise.difficulty}
              </span>
              <span className="px-4 py-1.5 text-xs font-black uppercase tracking-widest rounded-lg bg-primary/20 text-primary">
                {exercise.mode} MODE
              </span>
            </div>
          </div>
        </div>

        {/* Setup Tip */}
        <div className="bg-accent/10 border border-accent/25 rounded-2xl p-5 mb-6 flex gap-4 items-start">
          <ShieldCheck className="w-5 h-5 text-accent shrink-0 mt-0.5" />
          <div>
            <h3 className="text-accent font-bold uppercase tracking-widest text-xs mb-2">
              Coach's cue
            </h3>
            <p className="text-foreground/80">{exercise.setupTip}</p>
          </div>
        </div>

        {/* Configuration Form */}
        <div className="space-y-6 bg-card border border-card-border rounded-3xl p-6 md:p-8 shadow-sm">
          <h3 className="text-xl font-bold tracking-tight border-b border-border pb-4">
            Session Parameters
          </h3>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Target */}
            <NumberField
              label={`Target ${exercise.mode === "reps" ? "Reps" : "Seconds"}`}
              value={target}
              min={exercise.mode === "reps" ? 1 : 10}
              max={exercise.mode === "reps" ? 100 : 300}
              step={exercise.mode === "reps" ? 1 : 5}
              onChange={setTarget}
              suffix={exercise.mode === "reps" ? "reps" : "sec"}
              icon={<Target className="h-4 w-4" />}
            />

            {/* Sets */}
            <NumberField
              label="Total Sets"
              value={sets}
              min={1}
              max={10}
              onChange={setSets}
              suffix="sets"
              icon={<RefreshCw className="h-4 w-4" />}
            />

            {/* Rest */}
            <div className="md:col-span-2">
              <NumberField
                label="Rest Between Sets"
                value={rest}
                min={10}
                max={120}
                step={5}
                onChange={setRest}
                suffix="sec"
                icon={<Clock className="h-4 w-4" />}
              />
            </div>
          </div>
        </div>

        {/* Action Bar */}
        <div className="mt-8 pb-12">
          <button
            data-testid="button-start-session"
            onClick={handleStart}
            className="w-full bg-primary text-primary-foreground py-5 rounded-2xl font-black text-xl uppercase tracking-wider flex items-center justify-center gap-3 hover:brightness-110 active:scale-[0.98] transition-all shadow-xl shadow-primary/20"
          >
            <Play className="fill-current w-6 h-6" />
            Start Session
          </button>
        </div>
      </main>
    </div>
  );
}
