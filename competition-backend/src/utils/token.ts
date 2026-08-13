import { createHash, randomBytes } from "node:crypto";
import { customAlphabet } from "nanoid";

// Unambiguous alphabet for human-facing short IDs (room codes).
const shortIdAlphabet = customAlphabet("ABCDEFGHJKLMNPQRSTUVWXYZ23456789", 6);

export function generateParticipantToken(): string {
  return randomBytes(24).toString("base64url");
}

export function hashToken(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}

export function verifyToken(token: string, tokenHash: string): boolean {
  return hashToken(token) === tokenHash;
}

export function generateRoomCode(): string {
  return shortIdAlphabet();
}
