import { useEffect, useRef } from "react";
import { voiceCoach } from "@/lib/voiceCoach";
import type { ExerciseConfig } from "@/config/exercises";
import type { HoldData, RepData } from "./useExerciseSocket";
import type { ReadinessVerdict } from "@/utils/readinessVerdict";

const FRAMING_COOLDOWN_MS = 9_000;
const POSITION_COOLDOWN_MS = 8_000;
const GOOD_FORM_COOLDOWN_MS = 12_000;
const MILESTONE_COOLDOWN_MS = 3_000;

/**
 * Practice-only spoken coaching: how to get set up, live position/form
 * corrections, and the readiness verdict at the end. Everything here uses
 * voiceCoach's "coach" profile (calm, clear, instructional) and NONE of it
 * is heard in the arena - the arena's voice (hooks/useVoiceCoach.ts) is
 * hype-only and never gives form guidance. Pure side-effect hook, renders
 * nothing.
 */
export function usePracticeVoice(
  exercise: ExerciseConfig,
  sessionStarted: boolean,
  countdownDone: boolean,
  isPaused: boolean,
  data: RepData | HoldData | null,
  enabled: boolean,
): void {
  const openedRef = useRef(false);
  const milestonesRef = useRef<Set<number>>(new Set());

  // Opening instruction, spoken once the countdown finishes and tracking
  // actually starts - reads the exercise's setup tip aloud so a player who
  // isn't looking at the screen still knows how to get into position.
  useEffect(() => {
    if (!enabled || !sessionStarted || !countdownDone || openedRef.current) return;
    openedRef.current = true;
    milestonesRef.current = new Set();
    voiceCoach.speak(`Let's begin. ${exercise.setupTip}`, {
      profile: "coach",
      priority: "high",
      dedupeKey: "practice-open",
      cooldownMs: 500,
    });
  }, [enabled, sessionStarted, countdownDone, exercise.setupTip]);

  useEffect(() => {
    if (!sessionStarted) openedRef.current = false;
  }, [sessionStarted]);

  // Live framing/position/form guidance - straight from whatever the pose
  // backend is already sending (position_message, posture_messages,
  // framing_message), just read aloud so the player doesn't have to keep
  // glancing at the screen to know what to fix.
  useEffect(() => {
    if (!enabled || !sessionStarted || !countdownDone || isPaused || !data) return;

    if (data.framing_ok === false && data.framing_message) {
      voiceCoach.speak(data.framing_message, {
        profile: "coach",
        priority: "normal",
        dedupeKey: "practice-framing",
        cooldownMs: FRAMING_COOLDOWN_MS,
      });
      return; // fix framing before anything else matters
    }

    if (exercise.mode === "reps") {
      const d = data as RepData;
      const milestone = Math.floor((d.rep_count ?? 0) / 5) * 5;
      if (milestone > 0 && !milestonesRef.current.has(milestone)) {
        milestonesRef.current.add(milestone);
        voiceCoach.speak(`${milestone} reps done.`, {
          profile: "coach",
          priority: "normal",
          dedupeKey: "practice-milestone",
          cooldownMs: MILESTONE_COOLDOWN_MS,
        });
      }

      if (d.position_message && !d.position_ok) {
        voiceCoach.speak(d.position_message, {
          profile: "coach",
          priority: "normal",
          dedupeKey: "practice-position",
          cooldownMs: POSITION_COOLDOWN_MS,
        });
      } else if (d.rep_completed && d.rep_form_quality === "good") {
        voiceCoach.speak("That's good form, keep it there.", {
          profile: "coach",
          priority: "low",
          dedupeKey: "practice-good-form",
          cooldownMs: GOOD_FORM_COOLDOWN_MS,
        });
      }
    } else {
      const d = data as HoldData;
      const milestone = Math.floor((d.hold_seconds ?? 0) / 10) * 10;
      if (milestone > 0 && !milestonesRef.current.has(milestone)) {
        milestonesRef.current.add(milestone);
        voiceCoach.speak(`${milestone} seconds held.`, {
          profile: "coach",
          priority: "normal",
          dedupeKey: "practice-milestone",
          cooldownMs: MILESTONE_COOLDOWN_MS,
        });
      }

      if (d.posture_messages?.[0] && !d.posture_ok) {
        voiceCoach.speak(d.posture_messages[0], {
          profile: "coach",
          priority: "normal",
          dedupeKey: "practice-position",
          cooldownMs: POSITION_COOLDOWN_MS,
        });
      } else if (d.is_holding && d.hold_quality === "good") {
        voiceCoach.speak("Good position, hold it right there.", {
          profile: "coach",
          priority: "low",
          dedupeKey: "practice-good-form",
          cooldownMs: GOOD_FORM_COOLDOWN_MS,
        });
      }
    }
  }, [enabled, sessionStarted, countdownDone, isPaused, data, exercise.mode]);

  useEffect(() => {
    return () => {
      voiceCoach.cancelAll();
    };
  }, []);
}

/** Speaks the end-of-session readiness verdict once. Called separately from
 * the completion screen (not the live hook above) since it fires after
 * tracking has already stopped. */
export function speakReadinessVerdict(verdict: ReadinessVerdict, enabled: boolean): void {
  if (!enabled) return;
  voiceCoach.speak(verdict.speech, {
    profile: "coach",
    priority: "high",
    dedupeKey: "practice-verdict",
    cooldownMs: 500,
  });
}
