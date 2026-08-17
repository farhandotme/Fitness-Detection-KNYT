export type ReadinessLevel = "ready" | "almost" | "practice_more";

export interface ReadinessVerdict {
  level: ReadinessLevel;
  headline: string;
  detail: string;
  /** Spoken once via voiceCoach (profile: "announcer") when the verdict is revealed. */
  speech: string;
  goodRatio: number;
}

/**
 * Turns a finished practice session's good-vs-flawed counts into a simple
 * three-tier verdict. Deliberately coarse (three buckets, not a percentage
 * score) - the point is a quick "should I go compete" signal, not a
 * training report.
 */
export function computeReadinessVerdict(good: number, flawed: number): ReadinessVerdict {
  const total = good + flawed;
  const goodRatio = total > 0 ? good / total : 0;

  if (total === 0) {
    return {
      level: "practice_more",
      headline: "Let's get some reps in",
      detail: "We didn't catch any completed reps that session - try again with your full body in frame.",
      speech: "Let's get some real reps in before you head to the arena.",
      goodRatio: 0,
    };
  }

  if (goodRatio >= 0.75) {
    return {
      level: "ready",
      headline: "You're good to go!",
      detail: `${good} of ${total} reps had solid form. You're ready for the arena.`,
      speech: "You are good to go! That form is ready for the arena.",
      goodRatio,
    };
  }

  if (goodRatio >= 0.45) {
    return {
      level: "almost",
      headline: "Getting there",
      detail: `${good} of ${total} reps had solid form. A bit more practice will help - but you can head to the arena whenever you're ready.`,
      speech: "You're getting there. A little more practice would help, but it's your call.",
      goodRatio,
    };
  }

  return {
    level: "practice_more",
    headline: "A bit more practice first",
    detail: `${good} of ${total} reps had solid form. Run through it again and focus on the form cues before you compete.`,
    speech: "Let's practice a bit more before jumping into a match.",
    goodRatio,
  };
}
