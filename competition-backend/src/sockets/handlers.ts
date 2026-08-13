import type { Server, Socket } from "socket.io";
import { logger } from "../config/logger.js";
import {
  joinCompetitionSchema,
  leaveCompetitionSchema,
  reconnectSchema,
  scoreUpdateSchema,
} from "../schemas/socketSchemas.js";
import {
  getRoomSnapshot,
  joinEvent,
  leaveCompetition,
  markParticipantDisconnected,
  reconnectToCompetition,
  submitScore,
} from "../services/competitionService.js";
import { competitionEngine } from "../services/competitionEngine.js";
import { AppError } from "../utils/errors.js";

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

export function registerSocketHandlers(io: Server): void {
  competitionEngine.attach(io);

  io.on("connection", (socket: Socket) => {
    sessions.set(socket, {});
    logger.debug({ socketId: socket.id }, "socket connected");

    socket.on("competition:join", async (payload) => {
      try {
        if (isRateLimited(socket)) {
          throw AppError.badRequest("Too many join attempts, please wait a moment and try again");
        }
        const input = joinCompetitionSchema.parse(payload);
        const result = await joinEvent(input.eventId, input.displayName, input.deviceId);

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
        await leaveCompetition(input.competitionId, input.participantId, input.participantToken);
        socket.leave(input.competitionId);
        await competitionEngine.onParticipantCountChanged(input.competitionId);
        const room = await getRoomSnapshot(input.competitionId);
        if (room) io.to(input.competitionId).emit("room:state", room);
        sessions.set(socket, {});
      } catch (err) {
        sendError(socket, err);
      }
    });

    socket.on("disconnect", async () => {
      const session = sessions.get(socket);
      if (session?.competitionId && session.participantId) {
        try {
          await markParticipantDisconnected(session.competitionId, session.participantId);
          const room = await getRoomSnapshot(session.competitionId);
          if (room) io.to(session.competitionId).emit("room:state", room);
        } catch (err) {
          logger.error({ err }, "error handling socket disconnect");
        }
      }
      sessions.delete(socket);
      logger.debug({ socketId: socket.id }, "socket disconnected");
    });
  });
}
