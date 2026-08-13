import type { NextFunction, Request, Response } from "express";
import { ZodError } from "zod";
import { AppError } from "../utils/errors.js";
import { logger } from "../config/logger.js";

export function notFoundHandler(req: Request, res: Response) {
  res.status(404).json({
    code: "NOT_FOUND",
    message: `No route for ${req.method} ${req.path}`,
  });
}

export function errorHandler(
  err: unknown,
  req: Request,
  res: Response,
  _next: NextFunction,
) {
  if (err instanceof ZodError) {
    res.status(400).json({
      code: "VALIDATION_ERROR",
      message: "Invalid request",
      details: err.flatten(),
    });
    return;
  }

  if (err instanceof AppError) {
    if (err.statusCode >= 500) logger.error({ err }, "application error");
    res
      .status(err.statusCode)
      .json({ code: err.code, message: err.message, details: err.details });
    return;
  }

  logger.error({ err, path: req.path }, "unhandled error");
  res.status(500).json({ code: "INTERNAL", message: "Internal server error" });
}
