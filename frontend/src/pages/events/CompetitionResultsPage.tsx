import React, { useEffect, useState } from "react";
import { useRoute, Link } from "wouter";
import { Navbar } from "@/components/Navbar";
import { getCompetitionSocket } from "@/lib/competitionSocket";
import { useCompetitionRoom } from "@/hooks/useCompetitionRoom";
import type { FinalResultEntry } from "@/types/competition";
import { Trophy, Medal, ArrowRight, Home } from "lucide-react";
import { cn } from "@/lib/utils";
import { motion } from "framer-motion";

export function CompetitionResultsPage() {
  const [match, params] = useRoute("/competitions/:competitionId/results");
  const competitionId = params?.competitionId;

  const { room, identity } = useCompetitionRoom(competitionId);
  const [finalResults, setFinalResults] = useState<FinalResultEntry[] | null>(null);

  useEffect(() => {
    if (!competitionId) return;
    const socket = getCompetitionSocket();
    const onCompleted = (payload: { competitionId: string; finalResults: FinalResultEntry[] }) => {
      if (payload.competitionId === competitionId) setFinalResults(payload.finalResults);
    };
    socket.on("competition:completed", onCompleted);
    return () => {
      socket.off("competition:completed", onCompleted);
    };
  }, [competitionId]);

  // Fall back to the last live leaderboard snapshot if we arrived here after
  // the competition:completed event already fired (e.g. a page refresh).
  const results: FinalResultEntry[] | null =
    finalResults ??
    (room?.status === "COMPLETED"
      ? room.leaderboard.map((e) => ({
          participantId: e.participantId,
          displayName: e.displayName,
          totalScore: e.score,
          rank: e.rank,
          perRound: [],
        }))
      : null);

  if (!match || !competitionId) {
    return <div className="p-8 text-center text-destructive">Room not found.</div>;
  }

  const podium = results?.slice(0, 3) ?? [];
  const rest = results?.slice(3) ?? [];

  return (
    <div className="min-h-dvh bg-background text-foreground">
      <Navbar />

      <main className="max-w-2xl mx-auto p-4 mt-6">
        <div className="text-center mb-8">
          <Trophy className="w-10 h-10 text-accent mx-auto mb-3" />
          <p className="text-xs font-bold uppercase tracking-[.2em] text-primary mb-1">
            Competition complete
          </p>
          <h1 className="text-3xl md:text-4xl font-black tracking-tighter">
            {room?.eventName ?? "Final Results"}
          </h1>
        </div>

        {!results && (
          <div className="bg-card border border-card-border rounded-3xl p-8 text-center text-muted-foreground">
            Calculating final results...
          </div>
        )}

        {results && (
          <>
            <div className="grid grid-cols-3 items-end gap-3 mb-8">
              {[podium[1], podium[0], podium[2]].map((entry, i) => {
                if (!entry) return <div key={i} />;
                const isFirst = entry.rank === 1;
                const isMe = entry.participantId === identity?.participantId;
                return (
                  <motion.div
                    key={entry.participantId}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.1 }}
                    data-testid={`podium-rank-${entry.rank}`}
                    className={cn(
                      "flex flex-col items-center justify-end rounded-3xl border p-4 text-center",
                      isFirst
                        ? "bg-accent/15 border-accent/40 h-48"
                        : "bg-card border-card-border h-36",
                      isMe && "ring-2 ring-primary",
                    )}
                  >
                    <Medal
                      className={cn(
                        "w-6 h-6 mb-2",
                        isFirst ? "text-accent" : "text-muted-foreground",
                      )}
                    />
                    <p className="font-black text-lg leading-tight truncate w-full">
                      {entry.displayName}
                    </p>
                    <p className="text-2xl font-mono font-black text-foreground mt-1">
                      {entry.totalScore}
                    </p>
                    <p className="text-[10px] uppercase tracking-widest text-muted-foreground mt-1">
                      #{entry.rank}
                    </p>
                  </motion.div>
                );
              })}
            </div>

            {rest.length > 0 && (
              <div className="space-y-2 mb-8">
                {rest.map((entry) => {
                  const isMe = entry.participantId === identity?.participantId;
                  return (
                    <div
                      key={entry.participantId}
                      data-testid={`standing-rank-${entry.rank}`}
                      className={cn(
                        "flex items-center gap-3 rounded-2xl border px-4 py-3",
                        isMe
                          ? "border-primary/40 bg-primary/5"
                          : "border-card-border bg-card",
                      )}
                    >
                      <span className="w-7 h-7 rounded-full bg-secondary flex items-center justify-center text-xs font-black text-muted-foreground shrink-0">
                        {entry.rank}
                      </span>
                      <span className="flex-1 font-bold truncate">
                        {entry.displayName}
                        {isMe && <span className="text-primary"> (You)</span>}
                      </span>
                      <span className="font-mono font-black">{entry.totalScore}</span>
                    </div>
                  );
                })}
              </div>
            )}

            <div className="flex flex-col sm:flex-row gap-3">
              <Link
                href="/events"
                data-testid="link-back-to-events"
                className="flex-1 flex items-center justify-center gap-2 bg-primary text-primary-foreground py-4 rounded-2xl font-black uppercase tracking-wider hover:brightness-110 transition-all"
              >
                Find another event
                <ArrowRight className="w-4 h-4" />
              </Link>
              <Link
                href="/"
                data-testid="link-home"
                className="flex items-center justify-center gap-2 bg-secondary text-foreground py-4 px-6 rounded-2xl font-black uppercase tracking-wider hover:bg-secondary/80 transition-all"
              >
                <Home className="w-4 h-4" />
                Home
              </Link>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
