export class AppError extends Error {
  public readonly statusCode: number;
  public readonly code: string;
  public readonly details?: unknown;

  constructor(code: string, message: string, statusCode = 400, details?: unknown) {
    super(message);
    this.name = "AppError";
    this.code = code;
    this.statusCode = statusCode;
    this.details = details;
  }

  static notFound(message = "Resource not found") {
    return new AppError("NOT_FOUND", message, 404);
  }

  static badRequest(message: string, details?: unknown) {
    return new AppError("BAD_REQUEST", message, 400, details);
  }

  static forbidden(message = "Forbidden") {
    return new AppError("FORBIDDEN", message, 403);
  }

  static conflict(message: string) {
    return new AppError("CONFLICT", message, 409);
  }

  static unauthorized(message = "Unauthorized") {
    return new AppError("UNAUTHORIZED", message, 401);
  }
}
