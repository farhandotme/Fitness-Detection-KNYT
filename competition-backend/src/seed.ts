import { connectMongo, disconnectMongo } from "./config/db.js";
import { EventModel } from "./models/Event.js";
import { logger } from "./config/logger.js";

// exerciseId values must match an `id` in the frontend's
// src/config/exercises.ts catalog - that's the contract between the two.
const sampleEvents = [
  {
    name: "Push-Up Championship",
    exerciseId: "pushup",
    exerciseName: "Push-Up",
    exerciseMode: "reps" as const,
    rounds: 2,
    roundDurationSeconds: 60,
    breakDurationSeconds: 15,
    maxParticipants: 5,
    description: "Two 60-second rounds. Most good reps across both rounds wins.",
    status: "live" as const,
  },
  {
    name: "Squat Sprint",
    exerciseId: "squat",
    exerciseName: "Squat",
    exerciseMode: "reps" as const,
    rounds: 3,
    roundDurationSeconds: 45,
    breakDurationSeconds: 15,
    maxParticipants: 5,
    description: "Three fast 45-second rounds of bodyweight squats.",
    status: "live" as const,
  },
  {
    name: "Plank Hold Showdown",
    exerciseId: "plank_hold",
    exerciseName: "Plank Hold",
    exerciseMode: "hold" as const,
    rounds: 1,
    roundDurationSeconds: 90,
    breakDurationSeconds: 15,
    maxParticipants: 5,
    description: "One round. Longest good-form hold time wins.",
    status: "live" as const,
  },
];

async function seed() {
  await connectMongo();
  for (const event of sampleEvents) {
    const existing = await EventModel.findOne({ name: event.name });
    if (existing) {
      logger.info({ name: event.name }, "event already exists, skipping");
      continue;
    }
    await EventModel.create(event);
    logger.info({ name: event.name }, "created sample event");
  }
  await disconnectMongo();
}

seed()
  .then(() => process.exit(0))
  .catch((err) => {
    logger.error({ err }, "seed failed");
    process.exit(1);
  });
