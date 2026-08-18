import type { NextFunction, Request, Response } from "express";
import { AppError } from "./errors.js";

type AsyncRoute = (req: Request, res: Response, next: NextFunction) => Promise<unknown>;

export function asyncHandler(fn: AsyncRoute) {
  return (req: Request, res: Response, next: NextFunction) => {
    fn(req, res, next).catch(next);
  };
}

/**
 * Express's ParamsDictionary types every value as `string`, but this
 * project's tsconfig has `noUncheckedIndexedAccess`, which correctly makes
 * indexed access `string | undefined` since a param can be missing at
 * runtime (e.g. a malformed route). Route handlers should always go through
 * this rather than `req.params.x` directly.
 */
export function requireParam(req: Request, name: string): string {
  const value = req.params[name];
  if (!value) throw AppError.badRequest(`Missing required URL parameter: ${name}`);
  return value;
}
