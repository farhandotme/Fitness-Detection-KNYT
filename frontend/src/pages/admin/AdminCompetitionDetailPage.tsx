import React, { useEffect, useState } from "react";
import { Link, useLocation, useRoute } from "wouter";
import { Navbar } from "@/components/Navbar";
import {
  type AdminCompetitionDetail,
  type AdminCompetitionStatus,
  abandonAdminCompetition,
  clearAdminSession,
  fetchAdminCompetitionDetail,
  getAdminToken,
  removeAdminParticipant,
} from "@/lib/adminApi";
import {
  AlertTriangle,
  ArrowLeft,
  Ban,
  Medal,
  UserMinus,
  Wifi,
  WifiOff,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";

const STATUS_STYLES: Record<AdminCompetitionStatus, string> = {
  WAITING: "bg-secondary text-muted-foreground",
  FULL: "bg-amber-500/15 text-amber-500",
  COUNTDOWN: "bg-amber-500/15 text-amber-500",
  ROUND_RUNNING: "bg-primary/15 text-primary",
  ROUND_FINISHED: "bg-primary/15 text-primary",
  BREAK: "bg-amber-500/15 text-amber-500",
  COMPLETED: "bg-emerald-500/15 text-emerald-500",
  ABANDONED: "bg-destructive/10 text-destructive",
};

const STATUS_LABELS: Record<AdminCompetitionStatus, string> = {
  WAITING: "Waiting for players",
  FULL: "Full - starting soon",
  COUNTDOWN: "Countdown",
  ROUND_RUNNING: "Round running",
  ROUND_FINISHED: "Round finished",
  BREAK: "Break",
  COMPLETED: "Completed",
  ABANDONED: "Abandoned",
};

const LIVE_STATUSES: AdminCompetitionStatus[] = [
  "WAITING",
  "FULL",
  "COUNTDOWN",
  "ROUND_RUNNING",
  "ROUND_FINISHED",
  "BREAK",
];
const POLL_MS = 5000;

export function AdminCompetitionDetailPage() {
  const [, params] = useRoute("/admin/competitions/:competitionId");
  const competitionId = params?.competitionId ?? "";
  const [, setLocation] = useLocation();

  const [detail, setDetail] = useState<AdminCompetitionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAbandon, setShowAbandon] = useState(false);
  const [removingParticipantId, setRemovingParticipantId] = useState<
    string | null
  >(null);

  useEffect(() => {
    if (!getAdminToken()) {
      setLocation("/admin/login");
      return;
    }
    if (competitionId) void load(true);
  }, [competitionId]);

  useEffect(() => {
    if (!detail || !LIVE_STATUSES.includes(detail.room.status)) return;
    const interval = setInterval(() => void load(false), POLL_MS);
    return () => clearInterval(interval);
  }, [detail?.room.status]);

  const load = async (showSpinner: boolean) => {
    if (showSpinner) setLoading(true);
    setError(null);
    try {
      setDetail(await fetchAdminCompetitionDetail(competitionId));
    } catch (err: any) {
      const message = err.message || "Could not load this competition";
      setError(message);
      if (
        message.toLowerCase().includes("session") ||
        message.toLowerCase().includes("token")
      ) {
        clearAdminSession();
        setLocation("/admin/login");
      }
    } finally {
      if (showSpinner) setLoading(false);
    }
  };

  const handleAbandon = async (reason: string) => {
    await abandonAdminCompetition(competitionId, reason);
    await load(false);
  };

  const handleRemoveParticipant = async (participantId: string) => {
    setRemovingParticipantId(participantId);
    try {
      await removeAdminParticipant(competitionId, participantId);
      await load(false);
    } catch (err: any) {
      setError(err.message || "Could not remove participant");
    } finally {
      setRemovingParticipantId(null);
    }
  };

  const room = detail?.room;
  const snapshot = detail?.snapshot;
  const canAbandon =
    room && room.status !== "COMPLETED" && room.status !== "ABANDONED";
  const canRemoveParticipants =
    room && (room.status === "WAITING" || room.status === "FULL");

  return (
    <div className="min-h-dvh bg-background text-foreground pb-20">
      <Navbar />

      <main className="max-w-4xl mx-auto p-4 mt-6 flex flex-col gap-6">
        {room && (
          <Link
            href={`/admin/events/${room.eventId}`}
            data-testid="link-back-to-event"
            className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors w-fit"
          >
            <ArrowLeft className="w-3.5 h-3.5" /> {room.eventName}
          </Link>
        )}

        {error && (
          <div className="bg-destructive/10 border border-destructive/30 rounded-2xl p-4 flex gap-3 items-start">
            <AlertTriangle className="w-5 h-5 text-destructive shrink-0 mt-0.5" />
            <p className="text-sm text-destructive font-semibold">{error}</p>
          </div>
        )}

        {loading && (
          <div className="bg-card border border-card-border rounded-3xl p-8 h-56 animate-pulse" />
        )}

        {!loading && room && (
          <>
            <div className="bg-card border border-card-border rounded-3xl p-6 flex flex-col gap-4">
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div>
                  <div className="flex items-center gap-2">
                    <h1 className="font-display text-2xl font-extrabold tracking-tight tracking-wide">
                      Room {room.roomCode}
                    </h1>
                    <span
                      className={cn(
                        "text-[10px] font-black uppercase tracking-widest px-2.5 py-1 rounded-md",
                        STATUS_STYLES[room.status],
                      )}
                    >
                      {STATUS_LABELS[room.status]}
                    </span>
                  </div>
                  <p className="text-sm text-muted-foreground mt-1">
                    {room.exerciseId} · Round {room.currentRound}/
                    {room.totalRounds} · {room.participants.length}/
                    {room.maxParticipants} players
                  </p>
                  {room.abandonReason && (
                    <p className="text-xs text-destructive font-semibold mt-1">
                      Abandoned: {room.abandonReason}
                    </p>
                  )}
                </div>
                {canAbandon && (
                  <button
                    onClick={() => setShowAbandon(true)}
                    data-testid="button-open-abandon"
                    className="flex items-center gap-1.5 px-3.5 py-2 rounded-full text-xs font-bold uppercase tracking-wider bg-destructive/10 text-destructive hover:bg-destructive/20 transition-colors"
                  >
                    <Ban className="w-3.5 h-3.5" /> End competition
                  </button>
                )}
              </div>
            </div>

            {/* Participants */}
            <div className="bg-card border border-card-border rounded-3xl p-5 md:p-6">
              <h2 className="text-lg font-black tracking-tight mb-4">
                Participants
              </h2>
              <div className="flex flex-col gap-2">
                {room.participants.map((p) => {
                  const live = snapshot?.participants.find(
                    (sp) => sp.participantId === p.participantId,
                  );
                  const leaderboardEntry = snapshot?.leaderboard.find(
                    (l) => l.participantId === p.participantId,
                  );
                  return (
                    <div
                      key={p.participantId}
                      data-testid={`row-participant-${p.participantId}`}
                      className="flex items-center justify-between gap-3 py-2.5 px-3 rounded-2xl bg-secondary/40"
                    >
                      <div className="flex items-center gap-2.5 min-w-0">
                        {live?.connected ? (
                          <Wifi className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
                        ) : (
                          <WifiOff className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                        )}
                        <span className="font-bold truncate">
                          {p.displayName}
                        </span>
                        {leaderboardEntry && (
                          <span className="text-xs text-muted-foreground font-semibold shrink-0">
                            #{leaderboardEntry.rank} · {leaderboardEntry.score}{" "}
                            pts
                          </span>
                        )}
                      </div>
                      {canRemoveParticipants && (
                        <button
                          onClick={() =>
                            handleRemoveParticipant(p.participantId)
                          }
                          disabled={removingParticipantId === p.participantId}
                          data-testid={`button-remove-participant-${p.participantId}`}
                          className="flex items-center gap-1 px-2.5 py-1.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-destructive/10 text-destructive hover:bg-destructive/20 transition-colors disabled:opacity-50 shrink-0"
                        >
                          <UserMinus className="w-3 h-3" />
                          {removingParticipantId === p.participantId
                            ? "..."
                            : "Remove"}
                        </button>
                      )}
                    </div>
                  );
                })}
                {room.participants.length === 0 && (
                  <p className="text-sm text-muted-foreground text-center py-6">
                    No one has joined yet.
                  </p>
                )}
              </div>
            </div>

            {/* Rounds & scores */}
            {room.rounds.length > 0 && (
              <div className="bg-card border border-card-border rounded-3xl p-5 md:p-6">
                <h2 className="text-lg font-black tracking-tight mb-4">
                  Round scores
                </h2>
                <div className="overflow-x-auto -mx-2">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-[10px] font-black uppercase tracking-wider text-muted-foreground border-b border-card-border">
                        <th className="px-2 py-2">Player</th>
                        {room.rounds.map((r) => (
                          <th
                            key={r.roundNumber}
                            className="px-2 py-2 text-right"
                          >
                            Round {r.roundNumber}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {room.participants.map((p) => (
                        <tr
                          key={p.participantId}
                          className="border-b border-card-border/50 last:border-0"
                        >
                          <td className="px-2 py-2.5 font-bold">
                            {p.displayName}
                          </td>
                          {room.rounds.map((r) => {
                            const score =
                              r.scores.find(
                                (s) => s.participantId === p.participantId,
                              )?.score ?? 0;
                            return (
                              <td
                                key={r.roundNumber}
                                className="px-2 py-2.5 text-right font-semibold tabular-nums"
                              >
                                {score}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Final results */}
            {room.status === "COMPLETED" && room.finalResults.length > 0 && (
              <div className="bg-card border border-card-border rounded-3xl p-5 md:p-6">
                <h2 className="text-lg font-black tracking-tight mb-4">
                  Final results
                </h2>
                <div className="flex flex-col gap-2">
                  {[...room.finalResults]
                    .sort((a, b) => a.rank - b.rank)
                    .map((r) => (
                      <div
                        key={r.participantId}
                        data-testid={`row-final-result-${r.participantId}`}
                        className={cn(
                          "flex items-center justify-between gap-3 py-3 px-4 rounded-2xl",
                          r.rank === 1
                            ? "bg-primary/10 border border-primary/30"
                            : "bg-secondary/40",
                        )}
                      >
                        <div className="flex items-center gap-3">
                          <span
                            className={cn(
                              "w-7 h-7 rounded-full flex items-center justify-center text-xs font-black shrink-0",
                              r.rank === 1
                                ? "bg-primary text-primary-foreground"
                                : "bg-secondary text-muted-foreground",
                            )}
                          >
                            {r.rank}
                          </span>
                          <span className="font-bold">{r.displayName}</span>
                          {r.rank === 1 && (
                            <Medal className="w-4 h-4 text-primary" />
                          )}
                        </div>
                        <span className="font-black tabular-nums">
                          {r.totalScore} pts
                        </span>
                      </div>
                    ))}
                </div>
              </div>
            )}
          </>
        )}
      </main>

      {showAbandon && (
        <AbandonRoomDialog
          onClose={() => setShowAbandon(false)}
          onConfirm={handleAbandon}
        />
      )}
    </div>
  );
}

function AbandonRoomDialog({
  onClose,
  onConfirm,
}: {
  onClose: () => void;
  onConfirm: (reason: string) => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleConfirm = async () => {
    setBusy(true);
    setError(null);
    try {
      await onConfirm(reason.trim() || "Ended by admin");
      onClose();
    } catch (err: any) {
      setError(err.message || "Could not end this competition");
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm p-0 sm:p-4">
      <div className="bg-card border border-card-border rounded-t-4xl sm:rounded-4xl w-full sm:max-w-md max-h-[90dvh] overflow-y-auto p-6 md:p-8 shadow-2xl">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-black tracking-tight">
            End this competition?
          </h2>
          <button
            onClick={onClose}
            disabled={busy}
            data-testid="button-close-abandon-dialog"
            className="p-2 rounded-full bg-secondary hover:bg-secondary/80 transition-colors disabled:opacity-50"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <p className="text-sm text-muted-foreground font-medium mb-4">
          This force-ends the room for every connected participant right now. No
          final ranking is produced - use this for stuck or abandoned rooms, not
          for a competition that's legitimately finishing.
        </p>

        <label className="block text-xs font-bold uppercase tracking-[.16em] text-muted-foreground mb-2">
          Reason (shown in the room's history)
        </label>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="e.g. Everyone disconnected and never came back"
          rows={3}
          maxLength={300}
          data-testid="input-abandon-reason"
          className="w-full rounded-2xl border border-input bg-background px-4 py-3 font-medium outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 resize-none mb-4"
        />

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
            data-testid="button-cancel-abandon"
            className="flex-1 py-3 rounded-2xl text-xs font-bold uppercase tracking-wider bg-secondary text-muted-foreground hover:bg-secondary/80 transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={busy}
            data-testid="button-confirm-abandon"
            className="flex-1 py-3 rounded-2xl text-xs font-black uppercase tracking-wider bg-destructive text-destructive-foreground hover:brightness-110 shadow-lg shadow-destructive/20 transition-all disabled:opacity-50"
          >
            {busy ? "Ending..." : "End competition"}
          </button>
        </div>
      </div>
    </div>
  );
}
