import type { Server, Socket } from "socket.io";
import { logger } from "../config/logger.js";
import {
  createRoomSchema,
  joinRoomSchema,
  leaveCompetitionSchema,
  reconnectSchema,
  scoreUpdateSchema,
} from "../schemas/socketSchemas.js";
import {
  getRoomSnapshot,
  handleParticipantDisconnect,
  leaveCompetition,
  reconnectToCompetition,
  submitScore,
} from "../services/competitionService.js";
import { createRoom, joinRoom } from "../services/roomService.js";
import { competitionEngine } from "../services/competitionEngine.js";
import { AppError } from "../utils/errors.js";
import { verifyAdminToken } from "../utils/jwt.js";
import { z } from "zod";

interface SocketSession {
  competitionId?: string;
  participantId?: string;
}

const sessions = new WeakMap<Socket, SocketSession>();

// Lightweight per-socket rate limit for join/reconnect - these are the two
// events that can create Mongo/Redis writes on every call, so a misbehaving
// or malicious client hammering them is worth throttling. score:update is
// deliberately NOT limited here since it's expected to fire ~every 120ms
// during a live round (see frontend CompetitionPlayPage) - that's normal.
const JOIN_WINDOW_MS = 10_000;
const JOIN_MAX_ATTEMPTS = 5;
const joinAttempts = new WeakMap<Socket, number[]>();

function isRateLimited(socket: Socket): boolean {
  const now = Date.now();
  const attempts = (joinAttempts.get(socket) ?? []).filter((t) => now - t < JOIN_WINDOW_MS);
  attempts.push(now);
  joinAttempts.set(socket, attempts);
  return attempts.length > JOIN_MAX_ATTEMPTS;
}

function sendError(socket: Socket, err: unknown) {
  if (err instanceof AppError) {
    socket.emit("error", { code: err.code, message: err.message });
  } else {
    logger.error({ err }, "unexpected socket error");
    socket.emit("error", { code: "INTERNAL", message: "Something went wrong. Please try again." });
  }
}

const spectateSchema = z.object({
  competitionId: z.string().trim().min(1),
  adminToken: z.string().trim().min(1),
});

const eventWatchSchema = z.object({
  eventId: z.string().trim().min(1),
});

export function registerSocketHandlers(io: Server): void {
  competitionEngine.attach(io);

  io.on("connection", (socket: Socket) => {
    sessions.set(socket, {});
    logger.debug({ socketId: socket.id }, "socket connected");

    // A participant creating their own room from the event's lobby (see
    // services/roomService.ts) - they're seated in it immediately.
    socket.on("room:create", async (payload) => {
      try {
        if (isRateLimited(socket)) {
          throw AppError.badRequest("Too many attempts, please wait a moment and try again");
        }
        const input = createRoomSchema.parse(payload);
        const result = await createRoom(input);

        socket.join(result.competitionId);
        sessions.set(socket, { competitionId: result.competitionId, participantId: result.participantId });

        socket.emit("competition:joined", result);
      } catch (err) {
        sendError(socket, err);
      }
    });

    // A participant joining a specific room they picked from the lobby
    // (public - no password, or private - correct password required).
    socket.on("room:join", async (payload) => {
      try {
        if (isRateLimited(socket)) {
          throw AppError.badRequest("Too many attempts, please wait a moment and try again");
        }
        const input = joinRoomSchema.parse(payload);
        const result = await joinRoom(input);

        socket.join(result.competitionId);
        sessions.set(socket, { competitionId: result.competitionId, participantId: result.participantId });

        socket.emit("competition:joined", result);
      } catch (err) {
        sendError(socket, err);
      }
    });

    socket.on("competition:reconnect", async (payload) => {
      try {
        if (isRateLimited(socket)) {
          throw AppError.badRequest("Too many reconnect attempts, please wait a moment and try again");
        }
        const input = reconnectSchema.parse(payload);
        const room = await reconnectToCompetition(input.competitionId, input.participantId, input.participantToken);

        socket.join(input.competitionId);
        sessions.set(socket, { competitionId: input.competitionId, participantId: input.participantId });

        socket.emit("competition:reconnected", { room });
        socket.to(input.competitionId).emit("room:state", room);
      } catch (err) {
        sendError(socket, err);
      }
    });

    socket.on("score:update", async (payload) => {
      try {
        const input = scoreUpdateSchema.parse(payload);
        const session = sessions.get(socket);
        if (!session || session.competitionId !== input.competitionId || session.participantId !== input.participantId) {
          throw AppError.forbidden("Not a member of this competition room");
        }
        await submitScore(input.competitionId, input.participantId, input.participantToken, input.round, input.score);
      } catch (err) {
        sendError(socket, err);
      }
    });

    socket.on("competition:leave", async (payload) => {
      try {
        const input = leaveCompetitionSchema.parse(payload);
        const result = await leaveCompetition(input.competitionId, input.participantId, input.participantToken);
        socket.leave(input.competitionId);

        if (result.hostLeft) {
          // The host owns this room - everyone still in it gets kicked out
          // with an explicit reason instead of a generic state update.
          io.to(input.competitionId).emit("room:closed", {
            competitionId: input.competitionId,
            reason: "The room was closed because the host left.",
          });
          io.in(input.competitionId).socketsLeave(input.competitionId);
        } else {
          await competitionEngine.onParticipantCountChanged(input.competitionId);
          const room = await getRoomSnapshot(input.competitionId);
          if (room) io.to(input.competitionId).emit("room:state", room);
        }
        sessions.set(socket, {});
      } catch (err) {
        sendError(socket, err);
      }
    });

    // Admin dashboard "watch live" view - joins the same Socket.IO room as
    // participants so it receives every room:state broadcast the engine
    // already sends, but is never added to the competition's participant
    // list (see services/roomService.ts) - purely read-only, doesn't
    // occupy a seat and can't submit scores.
    socket.on("admin:spectate", async (payload) => {
      try {
        const input = spectateSchema.parse(payload);
        try {
          verifyAdminToken(input.adminToken);
        } catch {
          throw AppError.unauthorized("Invalid or expired admin session, please log in again");
        }

        const room = await getRoomSnapshot(input.competitionId);
        if (!room) throw AppError.notFound("Competition room not found");

        socket.join(input.competitionId);
        socket.emit("admin:spectating", { room });
      } catch (err) {
        sendError(socket, err);
      }
    });

    // Public join/results pages subscribe to a scheduled event's phase
    // (registration opens/closes, goes live, gets cancelled) so their
    // countdowns update the moment services/eventScheduler.ts broadcasts a
    // transition, instead of waiting on a poll. Read-only, no auth needed -
    // this is the same information the public GET /api/events/:id returns.
    socket.on("event:watch", (payload) => {
      const input = eventWatchSchema.safeParse(payload);
      if (!input.success) return;
      socket.join(`event:${input.data.eventId}`);
    });

    socket.on("event:unwatch", (payload) => {
      const input = eventWatchSchema.safeParse(payload);
      if (!input.success) return;
      socket.leave(`event:${input.data.eventId}`);
    });

    socket.on("disconnect", async () => {
      const session = sessions.get(socket);
      if (session?.competitionId && session.participantId) {
        const { competitionId, participantId } = session;
        try {
          await handleParticipantDisconnect(
            competitionId,
            participantId,
            async () => {
              // Only fires if the grace period expires with no reconnect -
              // the seat is actually freed at that point, so re-run the
              // same "did this change the room" checks a normal leave
              // triggers.
              await competitionEngine.onParticipantCountChanged(competitionId);
              const room = await getRoomSnapshot(competitionId);
              if (room) io.to(competitionId).emit("room:state", room);
            },
            async () => {
              // Only fires if the *host's* grace period expires with no
              // reconnect - the room has just been destroyed, so kick
              // everyone still in it out with an explicit reason.
              io.to(competitionId).emit("room:closed", {
                competitionId,
                reason: "The room was closed because the host disconnected.",
              });
              io.in(competitionId).socketsLeave(competitionId);
            },
          );
          // Broadcast the immediate "Reconnecting..." state too, so other
          // participants see it without waiting for the grace period.
          const room = await getRoomSnapshot(competitionId);
          if (room) io.to(competitionId).emit("room:state", room);
        } catch (err) {
          logger.error({ err }, "error handling socket disconnect");
        }
      }
      sessions.delete(socket);
      logger.debug({ socketId: socket.id }, "socket disconnected");
    });
  });
}
