import { Router } from "express";
import { asyncHandler } from "../utils/asyncHandler.js";
import { AppError } from "../utils/errors.js";
import { env } from "../config/env.js";
import {
  changePasswordSchema,
  loginAdminSchema,
  registerAdminSchema,
} from "../schemas/authSchemas.js";
import { AdminUserModel } from "../models/AdminUser.js";
import { hashPassword, verifyPassword } from "../utils/password.js";
import { signAdminToken, verifyAdminToken } from "../utils/jwt.js";
import { logger } from "../config/logger.js";

export const authRoutes = Router();

// POST /api/admin/auth/register - create a new admin account.
// Requires ADMIN_SIGNUP_CODE (set in .env) so this isn't wide open to any
// visitor, while still letting you create your own admin login for testing
// without a full user-management system (v1 has no participant accounts at
// all, per the spec - this is purely for the small number of people who
// create/manage events).
authRoutes.post(
  "/register",
  asyncHandler(async (req, res) => {
    if (!env.ADMIN_REGISTRATION_ENABLED) {
      throw AppError.forbidden("Admin registration is currently closed");
    }

    const input = registerAdminSchema.parse(req.body);

    if (input.signupCode !== env.ADMIN_SIGNUP_CODE) {
      throw AppError.forbidden("Invalid admin signup code");
    }

    const username = input.username.toLowerCase();
    const existing = await AdminUserModel.findOne({ username });
    if (existing) throw AppError.conflict("That username is already taken");

    const passwordHash = await hashPassword(input.password);
    const admin = await AdminUserModel.create({ username, passwordHash });

    const token = signAdminToken({
      sub: String(admin._id),
      username: admin.username,
    });
    logger.info({ username: admin.username }, "admin account registered");
    res.status(201).json({ token, username: admin.username });
  }),
);

// POST /api/admin/auth/login
authRoutes.post(
  "/login",
  asyncHandler(async (req, res) => {
    const input = loginAdminSchema.parse(req.body);
    const username = input.username.toLowerCase();

    const admin = await AdminUserModel.findOne({ username });
    if (!admin || !(await verifyPassword(input.password, admin.passwordHash))) {
      throw AppError.unauthorized("Invalid username or password");
    }

    const token = signAdminToken({
      sub: String(admin._id),
      username: admin.username,
    });
    res.json({ token, username: admin.username });
  }),
);

// POST /api/admin/auth/change-password - requires a valid admin session
// (unlike register/login, which issue one). Re-verifies the current
// password server-side rather than trusting the session alone, so a
// hijacked-but-not-yet-expired token can't silently take over the account.
authRoutes.post(
  "/change-password",
  asyncHandler(async (req, res) => {
    const header = req.header("authorization");
    const token = header?.startsWith("Bearer ") ? header.slice(7) : null;
    if (!token) throw AppError.unauthorized("Missing admin session token");

    let claims;
    try {
      claims = verifyAdminToken(token);
    } catch {
      throw AppError.unauthorized(
        "Invalid or expired admin session, please log in again",
      );
    }

    const input = changePasswordSchema.parse(req.body);
    const admin = await AdminUserModel.findById(claims.sub);
    if (!admin) throw AppError.unauthorized("Account no longer exists");

    const valid = await verifyPassword(
      input.currentPassword,
      admin.passwordHash,
    );
    if (!valid) throw AppError.unauthorized("Current password is incorrect");

    admin.passwordHash = await hashPassword(input.newPassword);
    await admin.save();

    logger.info({ username: admin.username }, "admin password changed");
    // Issue a fresh token so the session keeps working without a re-login,
    // consistent with register/login above.
    const newToken = signAdminToken({
      sub: String(admin._id),
      username: admin.username,
    });
    res.json({ token: newToken, username: admin.username });
  }),
);
