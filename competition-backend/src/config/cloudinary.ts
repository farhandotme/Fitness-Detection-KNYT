import { v2 as cloudinary } from "cloudinary";
import { env } from "./env.js";

// Only configured when all three CLOUDINARY_* vars are present (env.ts
// enforces that they're set as an all-or-nothing trio). Everything in
// services/avatarService.ts checks env.cloudinaryConfigured before touching
// this, so it's safe for `cloudinary.config()` to simply be a no-op here
// when avatar photo uploads are disabled for this deployment.
if (env.cloudinaryConfigured) {
  cloudinary.config({
    cloud_name: env.CLOUDINARY_CLOUD_NAME,
    api_key: env.CLOUDINARY_API_KEY,
    api_secret: env.CLOUDINARY_API_SECRET,
    secure: true,
  });
}

export { cloudinary };
