import { Schema, model, type InferSchemaType } from "mongoose";

// A minimal admin account. v1 has no *participant* accounts (see the
// competition spec, section 13) but event creation is still gated behind a
// real login rather than a single shared secret, so an admin can register
// their own account, log in, and manage events from the admin page.
const adminUserSchema = new Schema(
  {
    username: {
      type: String,
      required: true,
      trim: true,
      lowercase: true,
      unique: true,
      minlength: 3,
      maxlength: 40,
    },
    passwordHash: { type: String, required: true },
  },
  { timestamps: true },
);

export type AdminUserDoc = InferSchemaType<typeof adminUserSchema>;
export const AdminUserModel = model("AdminUser", adminUserSchema);
