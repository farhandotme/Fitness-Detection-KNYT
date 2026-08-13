import jwt from "jsonwebtoken";
import { env } from "../config/env.js";

export interface AdminTokenPayload {
  sub: string; // admin user id
  username: string;
}

const ADMIN_TOKEN_TTL = "12h";

export function signAdminToken(payload: AdminTokenPayload): string {
  return jwt.sign(payload, env.JWT_SECRET, { expiresIn: ADMIN_TOKEN_TTL });
}

export function verifyAdminToken(token: string): AdminTokenPayload {
  return jwt.verify(token, env.JWT_SECRET) as AdminTokenPayload;
}
