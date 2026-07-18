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
  // ---- Live, fully-tracked exercises ----
  {
    id: "jumping-jacks",
    name: "Jumping Jacks",
    category: "Cardio",
    difficulty: "Beginner",
    equipment: "Bodyweight",
    emoji: "🤸",
    description:
      "Full-body cardio rep counter with arm and leg synchronization.",
    tags: ["cardio", "warmup", "full body", "jumping jack"],
    status: "available",
    route: "/exercises/jumping-jacks",
  },
  {
    id: "squat",
    name: "Squat",
    category: "Lower Body",
    difficulty: "Beginner",
    equipment: "Bodyweight",
    emoji: "🦵",
    description: "Tracks squat depth, posture, knee alignment and repetitions.",
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
    description: "Tracks elbow angle, curl range of motion and repetitions.",
    tags: ["arms", "biceps", "curl"],
    status: "available",
    route: "/reps",
  },
  {
    id: "pushup",
    name: "Push-up",
    category: "Upper Body",
    difficulty: "Intermediate",
    equipment: "Bodyweight",
    emoji: "🏋️",
    description: "Tracks push-up depth, body alignment and repetitions.",
    tags: ["pushup", "chest", "triceps", "upper body"],
    status: "available",
    route: "/pushup",
  },

  {
    id: "lunge",
    name: "Lunge",
    category: "Lower Body",
    difficulty: "Beginner",
    equipment: "Bodyweight",
    emoji: "🚶",
    description: "Tracks forward lunges with balance and knee alignment.",
    tags: ["legs", "glutes", "lunges"],
    status: "available",
    route: "/exercises/lunge",
  },
  {
    id: "high-knees",
    name: "High Knees",
    category: "Cardio",
    difficulty: "Beginner",
    equipment: "Bodyweight",
    emoji: "🏃",
    description:
      "Counts high-knee reps while monitoring knee height and cadence.",
    tags: ["cardio", "warmup", "running"],
    status: "available",
    route: "/exercises/high-knees",
  },
  {
    id: "mountain-climber",
    name: "Mountain Climber",
    category: "Cardio",
    difficulty: "Intermediate",
    equipment: "Bodyweight",
    emoji: "🧗",
    description: "Tracks alternating knee drives from a plank position.",
    tags: ["core", "cardio", "hiit"],
    status: "available",
    route: "/exercises/mountain-climber",
  },
  {
    id: "plank",
    name: "Plank Hold",
    category: "Core",
    difficulty: "Beginner",
    equipment: "Bodyweight",
    emoji: "🧘",
    description: "Measures hold duration and body alignment.",
    tags: ["core", "abs", "isometric"],
    status: "available",
    route: "/exercises/plank-hold",
  },
  {
    id: "shoulder-press",
    name: "Shoulder Press",
    category: "Upper Body",
    difficulty: "Intermediate",
    equipment: "Dumbbell",
    emoji: "🏋️‍♀️",
    description: "Tracks overhead shoulder press repetitions.",
    tags: ["shoulders", "arms", "press"],
    status: "available",
    route: "/exercises/shoulder-press",
  },
  {
    id: "lateral-raise",
    name: "Lateral Raise",
    category: "Upper Body",
    difficulty: "Beginner",
    equipment: "Dumbbell",
    emoji: "🙆",
    description: "Tracks shoulder abduction and arm symmetry.",
    tags: ["shoulders", "arms"],
    status: "available",
    route: "/exercises/lateral-raise",
  },
  {
    id: "Muay Thai Jab",
    name: "Muay Thai Jab",
    category: "Upper Body",
    difficulty: "Beginner",
    equipment: "Bodyweight",
    emoji: "🥊",
    description: "Tracks shoulder abduction and arm symmetry.",
    tags: ["shoulders", "arms"],
    status: "available",
    route: "/muay_thai_jab",
  },
  {
    id: "dead-bug",
    name: "Dead Bug",
    category: "Core",
    difficulty: "Intermediate",
    equipment: "Bodyweight",
    emoji: "🐞",
    description: "Tracks opposite arm-leg coordination.",
    tags: ["core", "stability"],
    status: "available",
    route: "/dead_bug",
  },
  {
    id: "side-plank",
    name: "Side Plank",
    category: "Core",
    difficulty: "Intermediate",
    equipment: "Bodyweight",
    emoji: "📏",
    description: "Tracks side plank hold and body alignment.",
    tags: ["core", "obliques"],
    status: "available",
    route: "/side_plank",
  },
  {
    id: "glute-bridge",
    name: "Bridge Pose",
    category: "Lower Body",
    difficulty: "Beginner",
    equipment: "Bodyweight",
    emoji: "🌉",
    description: "Tracks hip lift height and repetitions.",
    tags: ["glutes", "hips"],
    status: "available",
    route: "/bridge_pose",
  },
  {
    id: "arm-circles",
    name: "Arm Circles",
    category: "Mobility",
    difficulty: "Beginner",
    equipment: "Bodyweight",
    emoji: "🔄",
    description: "Shoulder mobility exercise with repetition tracking.",
    tags: ["warmup", "mobility", "shoulders"],
    status: "coming_soon",
  },
  {
    id: "butt-kicks",
    name: "Butt Kicks",
    category: "Cardio",
    difficulty: "Beginner",
    equipment: "Bodyweight",
    emoji: "🏃‍♂️",
    description: "Tracks heel-to-glute movement and cadence.",
    tags: ["cardio", "warmup"],
    status: "coming_soon",
  },
  {
    id: "calf-raise",
    name: "Calf Raise",
    category: "Lower Body",
    difficulty: "Beginner",
    equipment: "Bodyweight",
    emoji: "🦶",
    description: "Counts calf raises while monitoring ankle extension.",
    tags: ["calves", "legs"],
    status: "coming_soon",
  },
  {
    id: "wall-sit",
    name: "Wall Sit",
    category: "Lower Body",
    difficulty: "Beginner",
    equipment: "Bodyweight",
    emoji: "🪑",
    description: "Measures hold time and squat angle.",
    tags: ["legs", "isometric", "wall"],
    status: "coming_soon",
  },
  {
    id: "bird-dog",
    name: "Bird Dog",
    category: "Core",
    difficulty: "Intermediate",
    equipment: "Bodyweight",
    emoji: "🐦",
    description: "Core stability exercise with balance tracking.",
    tags: ["core", "balance"],
    status: "coming_soon",
  },
  {
    id: "cat-cow",
    name: "Cat-Cow",
    category: "Mobility",
    difficulty: "Beginner",
    equipment: "Bodyweight",
    emoji: "🐈",
    description: "Tracks spinal mobility and posture.",
    tags: ["mobility", "stretch"],
    status: "coming_soon",
  },
  {
    id: "cobra-pose",
    name: "Cobra Pose",
    category: "Mobility",
    difficulty: "Beginner",
    equipment: "Bodyweight",
    emoji: "🐍",
    description: "Yoga back extension posture tracker.",
    tags: ["yoga", "stretch", "back"],
    status: "coming_soon",
  },
  {
    id: "downward-dog",
    name: "Downward Dog",
    category: "Mobility",
    difficulty: "Beginner",
    equipment: "Bodyweight",
    emoji: "🐕",
    description: "Tracks shoulder, hip and leg alignment.",
    tags: ["yoga", "stretch"],
    status: "coming_soon",
  },
  {
    id: "warrior-ii",
    name: "Warrior II",
    category: "Mobility",
    difficulty: "Intermediate",
    equipment: "Bodyweight",
    emoji: "⚔️",
    description: "Yoga balance and posture assessment.",
    tags: ["yoga", "balance"],
    status: "coming_soon",
  },
  {
    id: "chair-pose",
    name: "Chair Pose",
    category: "Mobility",
    difficulty: "Beginner",
    equipment: "Bodyweight",
    emoji: "🪑",
    description: "Tracks squat depth with overhead arm position.",
    tags: ["yoga", "legs"],
    status: "coming_soon",
  },
  {
    id: "tree-pose",
    name: "Tree Pose",
    category: "Mobility",
    difficulty: "Intermediate",
    equipment: "Bodyweight",
    emoji: "🌳",
    description: "Single-leg balance and stability assessment.",
    tags: ["balance", "yoga"],
    status: "coming_soon",
  },

  {
    id: "russian-twist",
    name: "Russian Twist",
    category: "Core",
    difficulty: "Intermediate",
    equipment: "Bodyweight",
    emoji: "🌀",
    description: "Tracks torso rotation and core engagement.",
    tags: ["core", "obliques"],
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
