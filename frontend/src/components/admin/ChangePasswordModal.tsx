import React, { useState } from "react";
import { AlertTriangle, CheckCircle2, X } from "lucide-react";
import { changeAdminPassword } from "@/lib/adminApi";

interface ChangePasswordModalProps {
  onClose: () => void;
}

export function ChangePasswordModal({ onClose }: ChangePasswordModalProps) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (newPassword !== confirmPassword) {
      setError("New passwords don't match");
      return;
    }
    if (newPassword.length < 8) {
      setError("New password must be at least 8 characters");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await changeAdminPassword(currentPassword, newPassword);
      setDone(true);
    } catch (err: any) {
      setError(err.message || "Could not change password");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm p-0 sm:p-4">
      <div className="bg-card border border-card-border rounded-t-4xl sm:rounded-4xl w-full sm:max-w-sm max-h-[90dvh] overflow-y-auto p-6 md:p-8 shadow-2xl">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-black tracking-tight">Change password</h2>
          <button
            onClick={onClose}
            data-testid="button-close-change-password"
            className="p-2 rounded-full bg-secondary hover:bg-secondary/80 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {done ? (
          <div className="flex flex-col items-center text-center gap-3 py-4">
            <CheckCircle2 className="w-10 h-10 text-primary" />
            <p className="font-bold">Password updated</p>
            <button
              onClick={onClose}
              data-testid="button-done-change-password"
              className="w-full bg-primary text-primary-foreground py-3.5 rounded-2xl font-black uppercase tracking-wider hover:brightness-110 transition-all mt-2"
            >
              Done
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <Field label="Current password">
              <input
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                data-testid="input-current-password"
                className="w-full h-12 rounded-2xl border border-input bg-background px-4 font-semibold outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
                required
                autoComplete="current-password"
              />
            </Field>
            <Field label="New password">
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                data-testid="input-new-password"
                className="w-full h-12 rounded-2xl border border-input bg-background px-4 font-semibold outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
                required
                minLength={8}
                autoComplete="new-password"
              />
            </Field>
            <Field label="Confirm new password">
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                data-testid="input-confirm-password"
                className="w-full h-12 rounded-2xl border border-input bg-background px-4 font-semibold outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
                required
                minLength={8}
                autoComplete="new-password"
              />
            </Field>

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
              data-testid="button-submit-change-password"
              className="w-full bg-primary text-primary-foreground py-4 rounded-2xl font-black uppercase tracking-wider hover:brightness-110 active:scale-[0.98] transition-all shadow-xl shadow-primary/20 disabled:opacity-50"
            >
              {submitting ? "Updating..." : "Update password"}
            </button>
          </form>
        )}
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
