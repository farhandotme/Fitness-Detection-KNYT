import type { NextFunction, Request, Response } from "express";
import { AppError } from "./errors.js";

type AsyncRoute = (
  req: Request,
  res: Response,
  next: NextFunction,
) => Promise<unknown>;

export function asyncHandler(fn: AsyncRoute) {
  return (req: Request, res: Response, next: NextFunction) => {
    fn(req, res, next).catch(next);
  };
}

export function requireParam(req: Request, name: string): string {
  const value = req.params[name];
  if (!value)
    throw AppError.badRequest(`Missing required URL parameter: ${name}`);
  return value;
}
