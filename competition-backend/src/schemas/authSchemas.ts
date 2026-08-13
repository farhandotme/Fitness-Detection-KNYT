import { z } from "zod";

export const registerAdminSchema = z.object({
  username: z
    .string()
    .trim()
    .min(3, "Username must be at least 3 characters")
    .max(40, "Username must be 40 characters or fewer")
    .regex(/^[a-zA-Z0-9_.-]+$/, "Username may only contain letters, numbers, . _ -"),
  password: z.string().min(8, "Password must be at least 8 characters").max(100),
  signupCode: z.string().min(1, "Signup code is required"),
});

export const loginAdminSchema = z.object({
  username: z.string().trim().min(1, "Username is required"),
  password: z.string().min(1, "Password is required"),
});

export const changePasswordSchema = z.object({
  currentPassword: z.string().min(1, "Current password is required"),
  newPassword: z.string().min(8, "New password must be at least 8 characters").max(100),
});

export type ChangePasswordInput = z.infer<typeof changePasswordSchema>;

export type RegisterAdminInput = z.infer<typeof registerAdminSchema>;
export type LoginAdminInput = z.infer<typeof loginAdminSchema>;
