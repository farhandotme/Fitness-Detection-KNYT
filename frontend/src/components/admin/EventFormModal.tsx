import React, { useMemo, useState } from "react";
import { AlertTriangle, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { exercises } from "@/config/exercises";
import { type AdminEvent, type CreateEventInput } from "@/lib/adminApi";

interface EventFormModalProps {
  /** Present -> edit mode (fields pre-filled, submit calls onSubmit with a partial diff-friendly payload). Absent -> create mode. */
  initialEvent?: AdminEvent;
  onClose: () => void;
  onSubmit: (input: CreateEventInput) => Promise<void>;
}

/**
 * One form backs both "New event" (AdminDashboardPage) and "Edit event"
 * (AdminEventDetailPage) - they're the same fields, and keeping them in
 * sync by hand in two places is exactly how forms drift apart over time.
 */
export function EventFormModal({
  initialEvent,
  onClose,
  onSubmit,
}: EventFormModalProps) {
  const isEdit = Boolean(initialEvent);
  const [name, setName] = useState(initialEvent?.name ?? "");
  const [exerciseId, setExerciseId] = useState(
    initialEvent?.exerciseId ?? exercises[0]?.id ?? "",
  );
  const [rounds, setRounds] = useState(initialEvent?.rounds ?? 2);
  const [roundDurationSeconds, setRoundDurationSeconds] = useState(
    initialEvent?.roundDurationSeconds ?? 60,
  );
  const [breakDurationSeconds, setBreakDurationSeconds] = useState(
    initialEvent?.breakDurationSeconds ?? 15,
  );
  const [maxParticipants, setMaxParticipants] = useState(
    initialEvent?.maxParticipants ?? 5,
  );
  const [description, setDescription] = useState(
    initialEvent?.description ?? "",
  );
  const [status, setStatus] = useState<"draft" | "live">(
    (initialEvent?.status === "closed" ? "draft" : initialEvent?.status) ??
      "live",
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedExercise = useMemo(
    () => exercises.find((e) => e.id === exerciseId),
    [exerciseId],
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedExercise) {
      setError("Pick an exercise");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit({
        name: name.trim(),
        exerciseId: selectedExercise.id,
        exerciseName: selectedExercise.name,
        exerciseMode: selectedExercise.mode,
        rounds,
        roundDurationSeconds,
        breakDurationSeconds,
        maxParticipants,
        description: description.trim() || undefined,
        status,
      });
    } catch (err: any) {
      setError(
        err.message ||
          (isEdit ? "Could not save changes" : "Could not create event"),
      );
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm p-0 sm:p-4">
      <div className="bg-card border border-card-border rounded-t-4xl sm:rounded-4xl w-full sm:max-w-lg max-h-[90dvh] overflow-y-auto p-6 md:p-8 shadow-2xl">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-black tracking-tight">
            {isEdit ? "Edit event" : "New event"}
          </h2>
          <button
            onClick={onClose}
            data-testid="button-close-event-form"
            className="p-2 rounded-full bg-secondary hover:bg-secondary/80 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {isEdit && (
          <p className="text-xs text-muted-foreground font-medium mb-4 -mt-2">
            Changes only apply to rooms created after you save - competitions
            already in progress keep the settings they started with.
          </p>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <Field label="Event name">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              data-testid="input-event-name"
              placeholder="e.g. Push-Up Championship"
              className="w-full h-12 rounded-2xl border border-input bg-background px-4 font-semibold outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
              required
              minLength={3}
            />
          </Field>

          <Field label="Exercise">
            <select
              value={exerciseId}
              onChange={(e) => setExerciseId(e.target.value)}
              data-testid="select-exercise"
              className="w-full h-12 rounded-2xl border border-input bg-background px-4 font-semibold outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
            >
              {exercises.map((ex) => (
                <option key={ex.id} value={ex.id}>
                  {ex.name} ({ex.mode})
                </option>
              ))}
            </select>
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Rounds">
              <input
                type="number"
                min={1}
                max={10}
                value={rounds}
                onChange={(e) => setRounds(Number(e.target.value))}
                data-testid="input-rounds"
                className="w-full h-12 rounded-2xl border border-input bg-background px-4 font-semibold outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
              />
            </Field>
            <Field label="Max players">
              <input
                type="number"
                min={2}
                max={5}
                value={maxParticipants}
                onChange={(e) => setMaxParticipants(Number(e.target.value))}
                data-testid="input-max-participants"
                className="w-full h-12 rounded-2xl border border-input bg-background px-4 font-semibold outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
              />
            </Field>
            <Field label="Round duration (s)">
              <input
                type="number"
                min={10}
                max={600}
                value={roundDurationSeconds}
                onChange={(e) =>
                  setRoundDurationSeconds(Number(e.target.value))
                }
                data-testid="input-round-duration"
                className="w-full h-12 rounded-2xl border border-input bg-background px-4 font-semibold outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
              />
            </Field>
            <Field label="Break duration (s)">
              <input
                type="number"
                min={5}
                max={300}
                value={breakDurationSeconds}
                onChange={(e) =>
                  setBreakDurationSeconds(Number(e.target.value))
                }
                data-testid="input-break-duration"
                className="w-full h-12 rounded-2xl border border-input bg-background px-4 font-semibold outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
              />
            </Field>
          </div>

          <Field label="Description (optional)">
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              data-testid="input-description"
              rows={2}
              maxLength={500}
              className="w-full rounded-2xl border border-input bg-background px-4 py-3 font-medium outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 resize-none"
            />
          </Field>

          <Field label="Publish as">
            <div className="flex gap-2">
              {(["live", "draft"] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setStatus(s)}
                  data-testid={`button-publish-${s}`}
                  className={cn(
                    "flex-1 py-2.5 rounded-xl text-xs font-bold uppercase tracking-wider transition-colors",
                    status === s
                      ? "bg-foreground text-background"
                      : "bg-secondary text-muted-foreground",
                  )}
                >
                  {s === "live" ? "Live now" : "Draft"}
                </button>
              ))}
            </div>
          </Field>

          {error && (
            <div className="bg-destructive/10 border border-destructive/30 rounded-2xl p-4 flex gap-2.5 items-start">
              <AlertTriangle className="w-4 h-4 text-destructive shrink-0 mt-0.5" />
              <p className="text-sm text-destructive font-semibold">{error}</p>
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            data-testid="button-submit-event-form"
            className="w-full bg-primary text-primary-foreground py-4 rounded-2xl font-black uppercase tracking-wider hover:brightness-110 active:scale-[0.98] transition-all shadow-xl shadow-primary/20 disabled:opacity-50"
          >
            {submitting
              ? "Saving..."
              : isEdit
                ? "Save changes"
                : "Create event"}
          </button>
        </form>
      </div>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-xs font-bold uppercase tracking-[.16em] text-muted-foreground mb-2">
        {label}
      </label>
      {children}
    </div>
  );
}
