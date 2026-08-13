import { Router } from "express";
import { asyncHandler } from "../utils/asyncHandler.js";
import { AppError } from "../utils/errors.js";
import { env } from "../config/env.js";
import {
  loginAdminSchema,
  registerAdminSchema,
} from "../schemas/authSchemas.js";
import { AdminUserModel } from "../models/AdminUser.js";
import { hashPassword, verifyPassword } from "../utils/password.js";
import { signAdminToken } from "../utils/jwt.js";
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
