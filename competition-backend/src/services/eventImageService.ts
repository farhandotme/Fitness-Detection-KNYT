import { nanoid } from "nanoid";
import { cloudinary } from "../config/cloudinary.js";
import { env } from "../config/env.js";
import { logger } from "../config/logger.js";
import { AppError } from "../utils/errors.js";

// Wide banner shape, auto-compressed - these are shown as event cover /
// advertising images (join screen banner, event card thumbnail, admin
// dashboard), never cropped to a face like avatars are.
const EVENT_IMAGE_TRANSFORMATION = "c_fill,g_auto,w_1600,h_900,q_auto,f_auto";

// Admins may attach at most this many cover images to a single event (see
// models/Event.ts `imageUrls`). Enforced again here so a signature can't be
// requested to sneak past the limit the schema/model already enforce.
export const MAX_EVENT_IMAGES = 3;

export interface EventImageUploadSignature {
  cloudName: string;
  apiKey: string;
  timestamp: number;
  signature: string;
  publicId: string;
  transformation: string;
}

function assertConfigured(): void {
  if (!env.cloudinaryConfigured) {
    throw new AppError(
      "EVENT_IMAGE_UPLOADS_DISABLED",
      "Cover image uploads aren't configured on this server yet - Cloudinary credentials are missing.",
      503,
    );
  }
}

/**
 * Same direct-to-Cloudinary pattern as avatarService's
 * createAvatarUploadSignature: the admin's browser uploads the file bytes
 * straight to Cloudinary using this short-lived signature, so multi-MB
 * banner images never pass through this server. Called once per image the
 * admin adds (up to MAX_EVENT_IMAGES).
 */
export function createEventImageUploadSignature(): EventImageUploadSignature {
  assertConfigured();

  const timestamp = Math.round(Date.now() / 1000);
  const publicId = `${env.CLOUDINARY_EVENT_IMAGE_FOLDER}/${nanoid(16)}`;

  const paramsToSign = {
    public_id: publicId,
    timestamp,
    transformation: EVENT_IMAGE_TRANSFORMATION,
  };

  const signature = cloudinary.utils.api_sign_request(
    paramsToSign,
    env.CLOUDINARY_API_SECRET!,
  );

  return {
    cloudName: env.CLOUDINARY_CLOUD_NAME!,
    apiKey: env.CLOUDINARY_API_KEY!,
    timestamp,
    signature,
    publicId,
    transformation: EVENT_IMAGE_TRANSFORMATION,
  };
}

function isOurEventImagePublicId(publicId: string): boolean {
  return publicId.startsWith(`${env.CLOUDINARY_EVENT_IMAGE_FOLDER}/`);
}

/** Deletes one uploaded event cover image. Called when an admin removes an image from the form before/after saving. */
export async function deleteEventImage(publicId: string): Promise<void> {
  assertConfigured();
  if (!isOurEventImagePublicId(publicId)) {
    throw AppError.forbidden("Not an event image this server manages");
  }
  await cloudinary.uploader.destroy(publicId, { resource_type: "image" });
}

/** Fire-and-forget variant for internal cleanup paths (e.g. event deletion) that must never block on Cloudinary. */
export function deleteEventImageBestEffort(
  publicId: string | null | undefined,
): void {
  if (!publicId || !env.cloudinaryConfigured) return;
  if (!isOurEventImagePublicId(publicId)) return;
  cloudinary.uploader
    .destroy(publicId, { resource_type: "image" })
    .catch((err) => {
      logger.warn(
        { err, publicId },
        "failed to delete event image from Cloudinary (non-fatal)",
      );
    });
}
