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
  //
  // Freshness matters more than completeness here: if a line is still
  // waiting in the queue (behind the opening instruction, or another
  // correction) when the underlying problem it describes stops being true,
  // we drop it via clearPending rather than let it play late and say
  // something that's no longer accurate. voiceCoach.speak() itself also
  // overwrites an already-queued line for the same topic in place, so at
  // most one line per topic is ever waiting, and it's always the current
  // one by the time it's spoken.
  useEffect(() => {
    if (!enabled || !sessionStarted || !countdownDone || isPaused || !data) return;

    if (data.framing_ok === false && data.framing_message) {
      voiceCoach.clearPending("practice-position");
      voiceCoach.clearPending("practice-good-form");
      voiceCoach.speak(data.framing_message, {
        profile: "coach",
        priority: "normal",
        dedupeKey: "practice-framing",
        cooldownMs: FRAMING_COOLDOWN_MS,
      });
      return; // fix framing before anything else matters
    }
    // Framing's fine now - don't let a stale "step back into frame" line
    // that's still queued from a moment ago fire late.
    voiceCoach.clearPending("practice-framing");

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

      const correction = d.position_message && !d.position_ok ? d.position_message : null;
      // `feedback` is a separate, general-purpose coaching line the pose
      // backend sends alongside (not instead of) position_message - e.g.
      // two-sided exercises reporting "your left arm is falling behind"
      // have nowhere else to put that. It's exactly what's shown in the
      // on-screen "Coach Feedback" panel, so it needs the same voice
      // treatment as everything else here.
      const feedback = d.feedback && d.feedback.trim().length > 0 ? d.feedback : null;

      if (correction || feedback) {
        voiceCoach.clearPending("practice-good-form");
        if (correction) {
          voiceCoach.speak(correction, {
            profile: "coach",
            priority: "normal",
            dedupeKey: "practice-position",
            cooldownMs: POSITION_COOLDOWN_MS,
          });
        } else {
          voiceCoach.clearPending("practice-position");
        }
        // Skip if it's just repeating the correction verbatim.
        if (feedback && feedback !== correction) {
          voiceCoach.speak(feedback, {
            profile: "coach",
            priority: "normal",
            dedupeKey: "practice-feedback",
            cooldownMs: POSITION_COOLDOWN_MS,
          });
        } else {
          voiceCoach.clearPending("practice-feedback");
        }
      } else {
        // Nothing to correct right now - drop any stale correction/feedback
        // line still waiting so it can't play late and say something no
        // longer true.
        voiceCoach.clearPending("practice-position");
        voiceCoach.clearPending("practice-feedback");
        if (d.rep_completed && d.rep_form_quality === "good") {
          voiceCoach.speak("That's good form, keep it there.", {
            profile: "coach",
            priority: "low",
            dedupeKey: "practice-good-form",
            cooldownMs: GOOD_FORM_COOLDOWN_MS,
          });
        }
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

      const correction = d.posture_messages?.[0] && !d.posture_ok ? d.posture_messages[0] : null;
      const feedback = d.feedback && d.feedback.trim().length > 0 ? d.feedback : null;

      if (correction || feedback) {
        voiceCoach.clearPending("practice-good-form");
        if (correction) {
          voiceCoach.speak(correction, {
            profile: "coach",
            priority: "normal",
            dedupeKey: "practice-position",
            cooldownMs: POSITION_COOLDOWN_MS,
          });
        } else {
          voiceCoach.clearPending("practice-position");
        }
        if (feedback && feedback !== correction) {
          voiceCoach.speak(feedback, {
            profile: "coach",
            priority: "normal",
            dedupeKey: "practice-feedback",
            cooldownMs: POSITION_COOLDOWN_MS,
          });
        } else {
          voiceCoach.clearPending("practice-feedback");
        }
      } else {
        voiceCoach.clearPending("practice-position");
        voiceCoach.clearPending("practice-feedback");
        if (d.is_holding && d.hold_quality === "good") {
          voiceCoach.speak("Good position, hold it right there.", {
            profile: "coach",
            priority: "low",
            dedupeKey: "practice-good-form",
            cooldownMs: GOOD_FORM_COOLDOWN_MS,
          });
        }
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
