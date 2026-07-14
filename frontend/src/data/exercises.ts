/**
 * Central exercise registry.
 *
 * This is the single source of truth the search/library page reads from.
 * Today it holds a handful of entries; it's shaped so it can grow to
 * hundreds or thousands of exercises without changing any UI code:
 *
 *   - `status: "available"` exercises are wired to a real detector + route
 *     and are clickable.
 *   - `status: "coming_soon"` exercises show up in search/browse (so the
 *     library "feels" like the full catalog) but are visibly disabled.
 *
 * When the catalog grows, this array can be swapped for a fetch() from an
 * API without touching ExerciseLibraryPage — it only depends on the
 * `ExerciseMeta` shape below.
 */

export type ExerciseStatus = "available" | "coming_soon";

export type ExerciseCategory =
  | "Cardio"
  | "Lower Body"
  | "Upper Body"
  | "Core"
  | "Full Body"
  | "Mobility";

export interface ExerciseMeta {
  id: string;
  name: string;
  category: ExerciseCategory;
  difficulty: "Beginner" | "Intermediate" | "Advanced";
  equipment: "Bodyweight" | "Dumbbell" | "Barbell" | "Band" | "Machine";
  emoji: string;
  description: string;
  /** Free-text search hooks beyond the name. */
  tags: string[];
  status: ExerciseStatus;
  /** Only set for `available` exercises. */
  route?: string;
}

export const EXERCISES: ExerciseMeta[] = [
  // ---- Live, fully-tracked exercises ----
  {
    id: "jumping-jacks",
    name: "Jumping Jacks",
    category: "Cardio",
    difficulty: "Beginner",
    equipment: "Bodyweight",
    emoji: "🤸",
    description:
      "Full-body cardio rep counter — tracks arm/leg extension, sync, tempo and stability in real time.",
    tags: ["cardio", "warmup", "jumping jack", "star jump", "full body"],
    status: "available",
    route: "/exercises/jumping-jacks",
  },
  {
    id: "squat",
    name: "Squat",
    category: "Lower Body",
    difficulty: "Beginner",
    equipment: "Bodyweight",
    emoji: "🏋️",
    description:
      "Knee-angle based rep counter with posture and depth form checks.",
    tags: ["legs", "glutes", "quads", "lower body"],
    status: "available",
    route: "/squat",
  },
  {
    id: "bicep-curl",
    name: "Bicep Curl",
    category: "Upper Body",
    difficulty: "Beginner",
    equipment: "Dumbbell",
    emoji: "💪",
    description: "Elbow-angle rep counter for single-arm curls.",
    tags: ["arms", "biceps", "curl", "upper body"],
    status: "available",
    route: "/reps",
  },
  {
    id: "pushup",
    name: "Push-up",
    category: "Upper Body",
    difficulty: "Intermediate",
    equipment: "Bodyweight",
    emoji: "🙌",
    description: "Elbow/torso tracking rep counter with plank-form checks.",
    tags: ["chest", "triceps", "upper body", "plank"],
    status: "available",
    route: "/pushup",
  },

  // ---- Catalog preview: coming soon (shows the library scales) ----
  {
    id: "lunge",
    name: "Lunge",
    category: "Lower Body",
    difficulty: "Beginner",
    equipment: "Bodyweight",
    emoji: "🦵",
    description: "Alternating forward lunge rep counter.",
    tags: ["legs", "glutes", "lower body"],
    status: "coming_soon",
  },
  {
    id: "burpee",
    name: "Burpee",
    category: "Full Body",
    difficulty: "Advanced",
    equipment: "Bodyweight",
    emoji: "🔥",
    description: "Squat-thrust-jump combo movement tracker.",
    tags: ["cardio", "full body", "hiit"],
    status: "coming_soon",
  },
  {
    id: "mountain-climber",
    name: "Mountain Climber",
    category: "Cardio",
    difficulty: "Intermediate",
    equipment: "Bodyweight",
    emoji: "⛰️",
    description: "Plank-position knee-drive rep counter.",
    tags: ["cardio", "core", "hiit"],
    status: "coming_soon",
  },
  {
    id: "plank",
    name: "Plank Hold",
    category: "Core",
    difficulty: "Beginner",
    equipment: "Bodyweight",
    emoji: "🧘",
    description: "Hold-time and hip-sag form tracker.",
    tags: ["core", "abs", "isometric"],
    status: "coming_soon",
  },
  {
    id: "high-knees",
    name: "High Knees",
    category: "Cardio",
    difficulty: "Beginner",
    equipment: "Bodyweight",
    emoji: "🏃",
    description: "In-place sprint knee-height tracker.",
    tags: ["cardio", "warmup"],
    status: "coming_soon",
  },
  {
    id: "lateral-raise",
    name: "Lateral Raise",
    category: "Upper Body",
    difficulty: "Beginner",
    equipment: "Dumbbell",
    emoji: "🙆",
    description: "Shoulder abduction rep counter.",
    tags: ["shoulders", "arms", "upper body"],
    status: "coming_soon",
  },
  {
    id: "shoulder-press",
    name: "Shoulder Press",
    category: "Upper Body",
    difficulty: "Intermediate",
    equipment: "Dumbbell",
    emoji: "🏋️‍♀️",
    description: "Overhead press rep counter.",
    tags: ["shoulders", "upper body"],
    status: "coming_soon",
  },
  {
    id: "deadlift",
    name: "Deadlift",
    category: "Full Body",
    difficulty: "Advanced",
    equipment: "Barbell",
    emoji: "🏋️‍♂️",
    description: "Hip-hinge form and rep tracker.",
    tags: ["back", "legs", "posterior chain"],
    status: "coming_soon",
  },
  {
    id: "situp",
    name: "Sit-up",
    category: "Core",
    difficulty: "Beginner",
    equipment: "Bodyweight",
    emoji: "🔃",
    description: "Torso-curl rep counter.",
    tags: ["core", "abs"],
    status: "coming_soon",
  },
  {
    id: "russian-twist",
    name: "Russian Twist",
    category: "Core",
    difficulty: "Intermediate",
    equipment: "Bodyweight",
    emoji: "🌀",
    description: "Rotational core rep counter.",
    tags: ["core", "obliques"],
    status: "coming_soon",
  },
  {
    id: "glute-bridge",
    name: "Glute Bridge",
    category: "Lower Body",
    difficulty: "Beginner",
    equipment: "Bodyweight",
    emoji: "🌉",
    description: "Hip-lift rep counter.",
    tags: ["glutes", "lower body"],
    status: "coming_soon",
  },
  {
    id: "arm-circles",
    name: "Arm Circles",
    category: "Mobility",
    difficulty: "Beginner",
    equipment: "Bodyweight",
    emoji: "🔄",
    description: "Shoulder mobility rep/timer tracker.",
    tags: ["mobility", "warmup", "shoulders"],
    status: "coming_soon",
  },
  {
    id: "jump-squat",
    name: "Jump Squat",
    category: "Lower Body",
    difficulty: "Advanced",
    equipment: "Bodyweight",
    emoji: "🦘",
    description: "Explosive squat + jump rep counter.",
    tags: ["legs", "plyometric", "cardio"],
    status: "coming_soon",
  },
  {
    id: "tricep-dip",
    name: "Tricep Dip",
    category: "Upper Body",
    difficulty: "Intermediate",
    equipment: "Bodyweight",
    emoji: "🪑",
    description: "Elbow-flexion dip rep counter.",
    tags: ["arms", "triceps", "upper body"],
    status: "coming_soon",
  },
  {
    id: "calf-raise",
    name: "Calf Raise",
    category: "Lower Body",
    difficulty: "Beginner",
    equipment: "Bodyweight",
    emoji: "🦶",
    description: "Ankle-extension rep counter.",
    tags: ["calves", "lower body"],
    status: "coming_soon",
  },
];

/** True if a search term matches an exercise's name/category/tags. */
export function matchesQuery(
  exercise: ExerciseMeta,
  rawQuery: string,
): boolean {
  const q = rawQuery.trim().toLowerCase();
  if (!q) return true;
  return (
    exercise.name.toLowerCase().includes(q) ||
    exercise.category.toLowerCase().includes(q) ||
    exercise.equipment.toLowerCase().includes(q) ||
    exercise.tags.some((t) => t.toLowerCase().includes(q))
  );
}

export const CATEGORIES: ExerciseCategory[] = [
  "Cardio",
  "Lower Body",
  "Upper Body",
  "Core",
  "Full Body",
  "Mobility",
];
