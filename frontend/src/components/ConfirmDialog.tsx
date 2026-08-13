import React, { useState } from "react";
import { AlertTriangle, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface ConfirmDialogProps {
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  onConfirm: () => Promise<void> | void;
  onClose: () => void;
}

/**
 * Matches CreateEventModal's modal chrome exactly (same overlay, same
 * rounded-4xl card) rather than pulling in the shadcn alert-dialog
 * primitive, which renders with a visibly different style - mixing the two
 * would look like an inconsistency, not a feature.
 */
export function ConfirmDialog({
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  danger = false,
  onConfirm,
  onClose,
}: ConfirmDialogProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleConfirm = async () => {
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
      onClose();
    } catch (err: any) {
      setError(err.message || "That didn't work");
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm p-0 sm:p-4">
      <div className="bg-card border border-card-border rounded-t-4xl sm:rounded-4xl w-full sm:max-w-md max-h-[90dvh] overflow-y-auto p-6 md:p-8 shadow-2xl">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-black tracking-tight">{title}</h2>
          <button
            onClick={onClose}
            disabled={busy}
            data-testid="button-close-confirm-dialog"
            className="p-2 rounded-full bg-secondary hover:bg-secondary/80 transition-colors disabled:opacity-50"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <p className="text-sm text-muted-foreground font-medium mb-6">
          {description}
        </p>

        {error && (
          <div className="bg-destructive/10 border border-destructive/30 rounded-2xl p-4 flex gap-2.5 items-start mb-4">
            <AlertTriangle className="w-4 h-4 text-destructive shrink-0 mt-0.5" />
            <p className="text-sm text-destructive font-semibold">{error}</p>
          </div>
        )}

        <div className="flex gap-3">
          <button
            onClick={onClose}
            disabled={busy}
            data-testid="button-cancel-confirm"
            className="flex-1 py-3 rounded-2xl text-xs font-bold uppercase tracking-wider bg-secondary text-muted-foreground hover:bg-secondary/80 transition-colors disabled:opacity-50"
          >
            {cancelLabel}
          </button>
          <button
            onClick={handleConfirm}
            disabled={busy}
            data-testid="button-confirm-action"
            className={cn(
              "flex-1 py-3 rounded-2xl text-xs font-black uppercase tracking-wider transition-all disabled:opacity-50",
              danger
                ? "bg-destructive text-destructive-foreground hover:brightness-110 shadow-lg shadow-destructive/20"
                : "bg-primary text-primary-foreground hover:brightness-110 shadow-lg shadow-primary/20",
            )}
          >
            {busy ? "Working..." : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
