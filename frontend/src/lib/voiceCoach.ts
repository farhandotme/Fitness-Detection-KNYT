/**
 * Shared voice engine: a small wrapper around the browser's SpeechSynthesis
 * API used both for practice instructions (see hooks/usePracticeVoice.ts)
 * and live-match hype (see hooks/useVoiceCoach.ts). Every call picks a
 * `profile` - "coach" for calm setup/form instructions, "announcer" for
 * arena cheering - which maps to a different rate/pitch (and, where the
 * browser offers one, a different underlying voice) so the two contexts
 * don't sound like the same person just talking faster.
 *
 * This module owns exactly one thing: making sure lines are spoken
 * one-at-a-time, never overlapping, never interrupted mid-sentence, and
 * never spammy. Everything else (rate limiting per topic, choosing
 * wording, which profile to use where) lives in the hooks that call speak().
 *
 * One nuance specific to the "coach" (practice) profile: a queued line can
 * go stale before its turn comes (e.g. "fix your position" queued behind
 * the opening instructions, spoken 4 seconds later after the player has
 * already fixed it). For "coach" lines only, a fresher speak() call for the
 * same dedupeKey overwrites the still-waiting line in place instead of
 * stacking behind it, and hooks can call clearPending(key) to drop a queued
 * line outright once its underlying condition is no longer true. The
 * "announcer" (arena) profile is untouched and behaves exactly as before.
 */

export type VoicePriority = "high" | "normal" | "low";
export type VoiceProfile = "coach" | "announcer";

interface SpeakOptions {
  /** Higher priority lines jump ahead of lower ones still waiting in the
   * short queue below - but never interrupt whichever line is already
   * being spoken. "high" is for round start/stop, "normal" for standings
   * and milestones, "low" for ambient encouragement and form nudges. */
  priority?: VoicePriority;
  /** "coach" is the calm, clear voice used only in practice (setup/form
   * instructions) - never heard in the arena. "announcer" is the hyped-up
   * in-match voice (cheering, reps, standings) - never gives instructions.
   * Keeping these as two distinct pitch/rate profiles (and, where the
   * browser offers more than one decent voice, two different voices) is
   * what makes the arena read as "hype commentator" rather than "the same
   * coach who just spoke a rulebook at you". Defaults to "announcer". */
  profile?: VoiceProfile;
  /** Only meaningful for the announcer profile - "peak" is for the big
   * moments (GO, milestones, lead changes): faster and higher-pitched than
   * "normal" ambient chatter, so the biggest lines actually land bigger. */
  intensity?: "normal" | "peak";
  /** Lines sharing a dedupeKey are rate-limited against each other via
   * cooldownMs, so e.g. "you're behind by N" can't fire every score tick. */
  dedupeKey?: string;
  /** Minimum time between two lines with the same dedupeKey. */
  cooldownMs?: number;
}

interface QueueItem {
  text: string;
  priority: VoicePriority;
  profile: VoiceProfile;
  intensity: "normal" | "peak";
  /** Only set/used for profile "coach" - lets a fresher line for the same
   * topic overwrite one that's still waiting in the queue instead of
   * piling up behind it (see the "coach" branch of speak() below). */
  dedupeKey?: string;
}

const PRIORITY_RANK: Record<VoicePriority, number> = {
  high: 0,
  normal: 1,
  low: 2,
};

// Keep the queue short and current - a coaching line still waiting behind
// two others by the time its turn comes is stale (the game state has moved
// on), so we cap it rather than let commentary lag behind what's on screen.
const MAX_QUEUE = 2;

// Two separate voice searches, in priority order. Where a browser exposes
// several good voices, the announcer deliberately reaches for a different
// one than the coach so the arena doesn't just sound like the practice
// instructor talking faster - it sounds like a different person entirely.
// Both fall back to whatever's available if none of these match.
const COACH_VOICE_NAMES = [
  "Google US English",
  "Microsoft Aria Online (Natural) - English (United States)",
  "Microsoft Zira Desktop - English (United States)",
  "Samantha",
  "Daniel",
];

const ANNOUNCER_VOICE_NAMES = [
  "Microsoft Guy Online (Natural) - English (United States)",
  "Google UK English Male",
  "Microsoft Ryan Online (Natural) - English (United Kingdom)",
  "Alex",
  "Fred",
];

// Rate/pitch per profile+intensity. SpeechSynthesis has no SSML/emphasis
// control, so these two knobs (plus phrasing/punctuation chosen by the
// callers in hooks/useVoiceCoach.ts and hooks/usePracticeVoice.ts) are the
// entire toolkit for making the arena feel like a hype announcer instead
// of the same flat instructional voice reading faster.
const VOICE_PARAMS: Record<VoiceProfile, { normal: { rate: number; pitch: number }; peak: { rate: number; pitch: number } }> = {
  coach: {
    normal: { rate: 0.94, pitch: 0.98 },
    peak: { rate: 0.94, pitch: 0.98 }, // coach never has a "peak" moment - stays calm and clear
  },
  announcer: {
    normal: { rate: 1.08, pitch: 1.1 },
    peak: { rate: 1.18, pitch: 1.24 },
  },
};

class VoiceCoach {
  private queue: QueueItem[] = [];
  private speaking = false;
  private enabled = true;
  private unlocked = false;
  private coachVoice: SpeechSynthesisVoice | null = null;
  private announcerVoice: SpeechSynthesisVoice | null = null;
  private lastSpokenAt = new Map<string, number>();
  // Practice-only (profile "coach") bookkeeping - kept entirely separate
  // from `lastSpokenAt` above so the arena/announcer path (which still
  // rate-limits from *enqueue* time exactly as before) is untouched. Coach
  // lines rate-limit from when they actually finish speaking instead, and
  // a fresher line for the same topic overwrites one still waiting rather
  // than queuing behind it - see speak() and processQueue() below. This is
  // what stops a stale correction ("fix your position") from playing after
  // the player has already fixed it.
  private coachLastSpokenAt = new Map<string, number>();

  constructor() {
    if (!this.supported()) return;
    this.pickVoices();
    window.speechSynthesis.onvoiceschanged = () => this.pickVoices();
  }

  private supported(): boolean {
    return typeof window !== "undefined" && "speechSynthesis" in window;
  }

  private pickVoices() {
    const voices = window.speechSynthesis.getVoices();
    if (!voices.length) return;

    const find = (names: string[]) =>
      names.map((n) => voices.find((v) => v.name === n)).find((v): v is SpeechSynthesisVoice => Boolean(v));

    this.coachVoice =
      find(COACH_VOICE_NAMES) ??
      voices.find((v) => v.lang === "en-US" && /natural|neural/i.test(v.name)) ??
      voices.find((v) => v.lang?.startsWith("en")) ??
      voices[0] ??
      null;

    this.announcerVoice =
      find(ANNOUNCER_VOICE_NAMES) ??
      // Prefer a voice distinct from the coach's if the browser has more than one.
      voices.find((v) => v.lang?.startsWith("en") && v.name !== this.coachVoice?.name) ??
      this.coachVoice;
  }

  setEnabled(enabled: boolean) {
    this.enabled = enabled;
    if (!enabled) this.cancelAll();
  }

  isEnabled(): boolean {
    return this.enabled;
  }

  /**
   * Warms up the speech engine from inside a real user gesture (tap/click/
   * key press). Some mobile browsers silently refuse the very first
   * speak() call of a page unless one has happened, so a single silent
   * utterance "unlocks" every call after it for the rest of the session.
   */
  unlock() {
    if (this.unlocked || !this.supported()) return;
    this.unlocked = true;
    const warmUp = new SpeechSynthesisUtterance(" ");
    warmUp.volume = 0;
    window.speechSynthesis.speak(warmUp);
  }

  speak(text: string, opts: SpeakOptions = {}): void {
    if (!this.enabled || !this.supported()) return;
    const { priority = "normal", profile = "announcer", intensity = "normal", dedupeKey, cooldownMs = 0 } = opts;

    if (profile === "coach") {
      // Practice path: rate-limit against when a line was last actually
      // SPOKEN (not enqueued), and if a line for this same topic is still
      // waiting in the queue, overwrite its text in place rather than
      // queuing a second one behind it. Both changes exist for the same
      // reason - by the time a queued line's turn comes, the player's
      // position may have already changed, and stale advice is worse than
      // no advice.
      if (dedupeKey) {
        const pending = this.queue.find((item) => item.dedupeKey === dedupeKey);
        if (pending) {
          pending.text = text;
          pending.priority = priority;
          pending.intensity = intensity;
          return; // already queued and now current - nothing else to do
        }
        if (cooldownMs > 0) {
          const last = this.coachLastSpokenAt.get(dedupeKey) ?? 0;
          if (Date.now() - last < cooldownMs) return;
        }
      }
      this.queue.push({ text, priority, profile, intensity, dedupeKey });
      this.queue.sort((a, b) => PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority]);
      if (this.queue.length > MAX_QUEUE) this.queue.length = MAX_QUEUE;
      this.processQueue();
      return;
    }

    if (dedupeKey && cooldownMs > 0) {
      const last = this.lastSpokenAt.get(dedupeKey) ?? 0;
      if (Date.now() - last < cooldownMs) return;
    }
    if (dedupeKey) this.lastSpokenAt.set(dedupeKey, Date.now());

    this.queue.push({ text, priority, profile, intensity });
    // Stable sort (spec-guaranteed) - equal-priority lines keep their
    // arrival order, higher priority moves earlier without ever touching
    // whatever is already mid-sentence out on the speaker.
    this.queue.sort((a, b) => PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority]);
    if (this.queue.length > MAX_QUEUE) this.queue.length = MAX_QUEUE;

    this.processQueue();
  }

  /**
   * Drops a still-waiting (not yet spoken) practice line for this topic, if
   * one exists - used when the underlying condition it was about to report
   * is no longer true by the time it would have played (e.g. the player
   * already fixed their position). Never touches whatever is currently
   * mid-sentence; only prevents a now-stale line from starting next.
   */
  clearPending(dedupeKey: string) {
    this.queue = this.queue.filter((item) => item.dedupeKey !== dedupeKey);
  }

  private processQueue() {
    if (this.speaking || this.queue.length === 0 || !this.supported()) return;
    const item = this.queue.shift()!;
    const utterance = new SpeechSynthesisUtterance(item.text);
    const voice = item.profile === "coach" ? this.coachVoice : this.announcerVoice;
    if (voice) utterance.voice = voice;
    utterance.lang = voice?.lang || "en-US";
    const params = VOICE_PARAMS[item.profile][item.intensity];
    utterance.rate = params.rate;
    utterance.pitch = params.pitch;
    utterance.volume = 1.0;

    if (item.profile === "coach" && item.dedupeKey) {
      this.coachLastSpokenAt.set(item.dedupeKey, Date.now());
    }

    this.speaking = true;
    const done = () => {
      this.speaking = false;
      this.processQueue();
    };
    utterance.onend = done;
    utterance.onerror = done;

    window.speechSynthesis.speak(utterance);
  }

  /** Stops whatever's playing and drops anything queued - used when a
   * round/room ends or the player leaves the match. */
  cancelAll() {
    this.queue = [];
    this.speaking = false;
    if (this.supported()) window.speechSynthesis.cancel();
  }
}

export const voiceCoach = new VoiceCoach();

// Unlocks on the very first tap/click/keypress anywhere in the app so
// audio is ready well before a match actually starts, without needing
// every page that might precede the play screen to wire this up itself.
if (typeof window !== "undefined" && "speechSynthesis" in window) {
  const unlockOnce = () => {
    voiceCoach.unlock();
    window.removeEventListener("pointerdown", unlockOnce);
    window.removeEventListener("keydown", unlockOnce);
  };
  window.addEventListener("pointerdown", unlockOnce, { once: true });
  window.addEventListener("keydown", unlockOnce, { once: true });
}
