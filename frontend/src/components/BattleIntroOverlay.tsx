import React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Swords, Zap } from "lucide-react";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import type { ParticipantPublic } from "@/types/competition";

interface BattleIntroOverlayProps {
  participants: ParticipantPublic[];
  selfParticipantId?: string;
  roundNumber: number;
  /** Seconds remaining, already floored/ceiled by the caller (e.g. 5,4,3,2,1). */
  countdownSeconds: number;
}

/**
 * Shown during the COUNTDOWN phase, right before a round starts. Replaces
 * the old plain "Get into position / 3 / 2 / 1" screen with a proper arena
 * face-off: every participant's avatar and name animate in, a VS badge
 * flares up between the first two players (or a "battle royale" badge for
 * 3+), and the big countdown number ticks underneath. Purely presentational
 * - all timing still comes from the room's countdownEndAt on the caller
 * side, this just renders whatever second it's told.
 */
export function BattleIntroOverlay({
  participants,
  selfParticipantId,
  roundNumber,
  countdownSeconds,
}: BattleIntroOverlayProps) {
  const isDuel = participants.length === 2;
  // Cap how many avatars we choreograph individually so a large room
  // doesn't turn into a wall of avatars - anything past 6 just shows as a
  // "+N" chip instead of its own animated slot.
  const visible = participants.slice(0, 6);
  const overflowCount = participants.length - visible.length;

  return (
    <div className="absolute inset-0 overflow-hidden flex flex-col items-center justify-center bg-[#171714]">
      {/* Ambient arena glow */}
      <div className="pointer-events-none absolute -top-24 left-1/4 w-72 h-72 rounded-full bg-primary/20 blur-[90px] ambient-pulse" />
      <div
        className="pointer-events-none absolute -bottom-24 right-1/4 w-72 h-72 rounded-full bg-accent/20 blur-[90px] ambient-pulse"
        style={{ animationDelay: "1.2s" }}
      />
      {/* Dot-grid texture, matching the app's ambient background elsewhere */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.06]"
        style={{
          backgroundImage:
            "radial-gradient(circle at 1px 1px, white 1px, transparent 0)",
          backgroundSize: "26px 26px",
        }}
      />
      {/* Diagonal light sweep for a "spotlight" arena feel */}
      <div className="pointer-events-none absolute inset-y-0 left-0 w-1/3 bg-linear-to-r from-transparent via-white/5 to-transparent arena-sweep" />

      <motion.p
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35 }}
        className="relative z-10 text-xs font-black uppercase tracking-[.4em] text-accent mb-4"
      >
        Round {roundNumber}
      </motion.p>

      {/* Roster face-off */}
      <div className="relative z-10 flex items-center justify-center gap-3 md:gap-6 px-4 flex-wrap max-w-3xl">
        {visible.map((p, i) => {
          const isSelf = p.participantId === selfParticipantId;
          const fromLeft = i % 2 === 0;
          return (
            <React.Fragment key={p.participantId}>
              <motion.div
                initial={{ opacity: 0, x: fromLeft ? -60 : 60, scale: 0.7 }}
                animate={{ opacity: 1, x: 0, scale: 1 }}
                transition={{
                  delay: 0.12 * i,
                  type: "spring",
                  stiffness: 260,
                  damping: 20,
                }}
                className="flex flex-col items-center gap-2"
              >
                <div
                  className={
                    isSelf
                      ? "rounded-full ring-4 ring-primary arena-ring"
                      : "rounded-full ring-2 ring-white/15"
                  }
                >
                  <PlayerAvatar
                    name={p.displayName}
                    src={p.avatarUrl}
                    seed={p.participantId}
                    size="xl"
                  />
                </div>
                <span
                  className={
                    "text-[11px] md:text-sm font-black uppercase tracking-wide max-w-22 md:max-w-28 truncate text-center " +
                    (isSelf ? "text-primary" : "text-white")
                  }
                >
                  {p.displayName}
                </span>
                {isSelf && (
                  <span className="text-[9px] font-bold text-primary/70 tracking-[.2em] -mt-1.5">
                    YOU
                  </span>
                )}
              </motion.div>

              {isDuel && i === 0 && (
                <motion.div
                  initial={{ opacity: 0, scale: 0.4, rotate: -15 }}
                  animate={{ opacity: 1, scale: [1, 1.18, 1], rotate: 0 }}
                  transition={{ delay: 0.3, duration: 0.55 }}
                  className="flex flex-col items-center justify-center px-1"
                >
                  <Swords className="w-6 h-6 md:w-8 md:h-8 text-accent drop-shadow-[0_0_12px_hsl(var(--accent)/.6)]" />
                  <span className="text-[10px] font-black text-accent tracking-widest mt-0.5">
                    VS
                  </span>
                </motion.div>
              )}
            </React.Fragment>
          );
        })}

        {overflowCount > 0 && (
          <motion.div
            initial={{ opacity: 0, scale: 0.7 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.12 * visible.length }}
            className="flex flex-col items-center gap-2"
          >
            <div className="h-16 w-16 md:h-20 md:w-20 rounded-full bg-white/5 border-2 border-white/15 flex items-center justify-center text-sm font-black text-slate-300">
              +{overflowCount}
            </div>
            <span className="text-[11px] font-bold text-slate-400 tracking-wide">
              more
            </span>
          </motion.div>
        )}
      </div>

      {!isDuel && (
        <motion.div
          initial={{ opacity: 0, scale: 0.6 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{
            delay: 0.28,
            type: "spring",
            stiffness: 240,
            damping: 18,
          }}
          className="relative z-10 flex items-center gap-2 mt-4 text-accent"
        >
          <Zap className="w-3.5 h-3.5" />
          <span className="text-[10px] font-black uppercase tracking-[.3em]">
            Battle royale
          </span>
          <Zap className="w-3.5 h-3.5" />
        </motion.div>
      )}

      {/* Big countdown number, with a quick flash pulse on every tick */}
      <div className="relative z-10 mt-3">
        <AnimatePresence mode="popLayout">
          <motion.div
            key={countdownSeconds}
            initial={{ opacity: 0, y: 10, scale: 0.85 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 1.15 }}
            transition={{ duration: 0.25, ease: "easeOut" }}
            className="h-[clamp(6rem,14vw,9rem)] w-[clamp(6rem,14vw,9rem)] text-center font-display text-[clamp(6rem,14vw,9rem)] leading-[.9] font-extrabold tabular-nums text-primary drop-shadow-[0_0_32px_hsl(var(--primary)/.4)]"
          >
            {countdownSeconds}
          </motion.div>
        </AnimatePresence>
        <div
          key={`flash-${countdownSeconds}`}
          className="pointer-events-none absolute inset-0 rounded-full bg-primary/30 blur-2xl arena-flash"
        />
      </div>

      <p className="relative z-10 text-xs md:text-sm text-slate-300 mt-1 uppercase tracking-widest">
        Round {roundNumber} begins for everyone at once
      </p>
    </div>
  );
}
