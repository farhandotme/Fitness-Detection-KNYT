import { useEffect, useRef } from "react";
import { voiceCoach } from "@/lib/voiceCoach";
import type { ParticipantIdentity, RoomStateSnapshot } from "@/types/competition";
import type { ExerciseConfig } from "@/config/exercises";
import type { HoldData, RepData } from "./useExerciseSocket";

// Hyped, varied, game-announcer lines - never instructional (no form/position
// cues here; that's practice's job, see hooks/usePracticeVoice.ts). Rotated
// in order per bucket (not random) so the same one never fires twice in a
// row, and every call goes through voiceCoach with profile: "announcer" so
// it reads as a different voice/energy than practice mode entirely.
const ENCOURAGEMENT_LINES = [
  "Let's go, let's go!",
  "You've got this, keep pushing!",
  "Dig deep, stay with it!",
  "Don't slow down now!",
  "Keep that pace up!",
];

const GOOD_REP_LINES = ["Nice rep!", "Clean!", "That's the one!", "Textbook!", "Boom, got it!"];

const goRepFor = (round: number) => (round <= 1 ? ["Go go go!", "And we're live!"] : [`Round ${round}, go!`, "Go time!"]);

const ENCOURAGEMENT_INTERVAL_MS = 25_000;
const POSITION_COOLDOWN_MS = 10_000;
const GOOD_REP_COOLDOWN_MS = 6_000;
const MILESTONE_COOLDOWN_MS = 3_000;

/**
 * Drives the shared voiceCoach off the live room + exercise-engine state
 * for one competition screen (see pages/events/CompetitionPlayPage.tsx).
 * Pure side-effect hook - renders nothing, just calls voiceCoach.speak()
 * at the right moments. `enabled` is the player's mute toggle.
 *
 * Arena voice is hype ONLY - reps, standings, "who's winning", cheering.
 * It never gives form/position instruction; that lives in practice mode
 * (usePracticeVoice.ts) so a player mid-match never gets talked at like
 * they're back in a tutorial.
 */
export function useVoiceCoach(
  room: RoomStateSnapshot | null,
  identity: ParticipantIdentity | null,
  exercise: ExerciseConfig | undefined,
  data: RepData | HoldData | null,
  enabled: boolean,
): void {
  const readyAnnouncedForRoundRef = useRef<number | null>(null);
  const goAnnouncedForRoundRef = useRef<number | null>(null);
  const doneAnnouncedForRoundRef = useRef<number | null>(null);
  const milestonesRef = useRef<Set<number>>(new Set());
  const lastPositionKeyRef = useRef<string | null>(null);
  const leadAnnouncedRef = useRef(false);
  const encouragementIdxRef = useRef(0);
  const goodRepIdxRef = useRef(0);
  const encouragementTimerRef = useRef<number | null>(null);

  // A new round resets which rep/hold milestones have already been called
  // out, so round 2 announces "5 reps" again instead of staying silent
  // because round 1 already crossed that count.
  useEffect(() => {
    milestonesRef.current = new Set();
  }, [room?.currentRound]);

  // Round lifecycle: get ready -> go -> round complete. Every line here is
  // "peak" intensity - these are the biggest beats of the match.
  useEffect(() => {
    if (!enabled || !room) return;

    if (room.status === "COUNTDOWN" && readyAnnouncedForRoundRef.current !== room.currentRound) {
      readyAnnouncedForRoundRef.current = room.currentRound;
      voiceCoach.speak(`Round ${room.currentRound + 1}! Get ready!`, {
        profile: "announcer",
        intensity: "peak",
        priority: "high",
        dedupeKey: `round-ready-${room.currentRound}`,
        cooldownMs: 500,
      });
    }

    if (room.status === "ROUND_RUNNING" && goAnnouncedForRoundRef.current !== room.currentRound) {
      goAnnouncedForRoundRef.current = room.currentRound;
      const lines = goRepFor(room.currentRound);
      voiceCoach.speak(lines[room.currentRound % lines.length], {
        profile: "announcer",
        intensity: "peak",
        priority: "high",
        dedupeKey: `round-go-${room.currentRound}`,
        cooldownMs: 500,
      });
    }

    if (
      (room.status === "ROUND_FINISHED" || room.status === "BREAK") &&
      doneAnnouncedForRoundRef.current !== room.currentRound
    ) {
      doneAnnouncedForRoundRef.current = room.currentRound;
      voiceCoach.speak(`Round ${room.currentRound} in the books! Nice work!`, {
        profile: "announcer",
        intensity: "normal",
        priority: "normal",
        dedupeKey: `round-done-${room.currentRound}`,
        cooldownMs: 500,
      });
    }
  }, [enabled, room?.status, room?.currentRound]);

  // Rep/hold milestones and good-rep hype, driven off the raw exercise-engine
  // stream (see hooks/useExerciseSocket.ts). Deliberately does NOT speak
  // position/posture guidance - that's instructional and belongs in
  // practice only, never mid-match.
  useEffect(() => {
    if (!enabled || !room || room.status !== "ROUND_RUNNING" || !exercise || !data) return;

    if (exercise.mode === "reps") {
      const d = data as RepData;
      const milestone = Math.floor((d.rep_count ?? 0) / 5) * 5;
      if (milestone > 0 && !milestonesRef.current.has(milestone)) {
        milestonesRef.current.add(milestone);
        voiceCoach.speak(`${milestone} reps! Keep firing!`, {
          profile: "announcer",
          intensity: "peak",
          priority: "normal",
          dedupeKey: "milestone",
          cooldownMs: MILESTONE_COOLDOWN_MS,
        });
      }

      if (d.rep_completed && d.rep_form_quality === "good") {
        const line = GOOD_REP_LINES[goodRepIdxRef.current % GOOD_REP_LINES.length];
        goodRepIdxRef.current += 1;
        voiceCoach.speak(line, {
          profile: "announcer",
          intensity: "normal",
          priority: "low",
          dedupeKey: "good-rep",
          cooldownMs: GOOD_REP_COOLDOWN_MS,
        });
      }
    } else {
      const d = data as HoldData;
      const milestone = Math.floor((d.hold_seconds ?? 0) / 10) * 10;
      if (milestone > 0 && !milestonesRef.current.has(milestone)) {
        milestonesRef.current.add(milestone);
        voiceCoach.speak(`${milestone} seconds! Hold that line!`, {
          profile: "announcer",
          intensity: "peak",
          priority: "normal",
          dedupeKey: "milestone",
          cooldownMs: MILESTONE_COOLDOWN_MS,
        });
      }

      if (d.is_holding && d.hold_quality === "good") {
        const line = GOOD_REP_LINES[goodRepIdxRef.current % GOOD_REP_LINES.length];
        goodRepIdxRef.current += 1;
        voiceCoach.speak(line, {
          profile: "announcer",
          intensity: "normal",
          priority: "low",
          dedupeKey: "good-rep",
          cooldownMs: GOOD_REP_COOLDOWN_MS,
        });
      }
    }
  }, [enabled, room?.status, exercise, data]);

  // Standings: who's ahead, by how much, and whether the lead just changed
  // hands - always framed as something to close, never just "you're losing".
  useEffect(() => {
    if (!enabled || !room || room.status !== "ROUND_RUNNING" || !identity) return;

    const board = room.leaderboard;
    const meIdx = board.findIndex((e) => e.participantId === identity.participantId);
    if (meIdx === -1) return;
    const me = board[meIdx];
    const unit = exercise?.mode === "hold" ? "second" : "rep";

    if (me.rank === 1) {
      if (!leadAnnouncedRef.current) {
        leadAnnouncedRef.current = true;
        voiceCoach.speak("You're in the lead! Don't let up!", {
          profile: "announcer",
          intensity: "peak",
          priority: "normal",
          dedupeKey: "position",
          cooldownMs: POSITION_COOLDOWN_MS,
        });
      }
      return;
    }
    leadAnnouncedRef.current = false;

    const ahead = board[meIdx - 1];
    if (!ahead) return;
    const gap = Math.max(1, Math.round(ahead.score - me.score));
    // Bucket the gap so we only speak again once it's meaningfully changed
    // (or the rival ahead of us changed), not on every single point tick.
    const bucketKey = `${ahead.participantId}:${Math.ceil(gap / 2)}`;
    if (lastPositionKeyRef.current === bucketKey) return;
    lastPositionKeyRef.current = bucketKey;

    voiceCoach.speak(
      `${ahead.displayName} is ahead by ${gap} ${unit}${gap === 1 ? "" : "s"}! Time to chase!`,
      {
        profile: "announcer",
        intensity: "normal",
        priority: "normal",
        dedupeKey: "position",
        cooldownMs: POSITION_COOLDOWN_MS,
      },
    );
  }, [enabled, room?.leaderboard, room?.status, identity, exercise?.mode]);

  // Ambient encouragement - low priority, spaced out, never piles up.
  useEffect(() => {
    const clear = () => {
      if (encouragementTimerRef.current) {
        window.clearInterval(encouragementTimerRef.current);
        encouragementTimerRef.current = null;
      }
    };
    if (!enabled || !room || room.status !== "ROUND_RUNNING") {
      clear();
      return;
    }
    if (encouragementTimerRef.current) return clear;

    encouragementTimerRef.current = window.setInterval(() => {
      const line = ENCOURAGEMENT_LINES[encouragementIdxRef.current % ENCOURAGEMENT_LINES.length];
      encouragementIdxRef.current += 1;
      voiceCoach.speak(line, {
        profile: "announcer",
        intensity: "normal",
        priority: "low",
        dedupeKey: "encourage",
        cooldownMs: ENCOURAGEMENT_INTERVAL_MS - 1000,
      });
    }, ENCOURAGEMENT_INTERVAL_MS);

    return clear;
  }, [enabled, room?.status]);

  // Full stop when this screen goes away.
  useEffect(() => {
    return () => {
      voiceCoach.cancelAll();
    };
  }, []);
}
