import { nanoid } from "nanoid";
import { cloudinary } from "../config/cloudinary.js";
import { env } from "../config/env.js";
import { logger } from "../config/logger.js";
import { AppError } from "../utils/errors.js";

// Square, face-cropped, auto-compressed - every avatar Cloudinary ever
// hands back is already the right shape for the little circular avatars
// the frontend renders, so no client-side cropping logic is needed and a
// phone photo never blows up a leaderboard row.
const AVATAR_TRANSFORMATION = "c_fill,g_face,h_512,w_512,q_auto,f_auto";

export interface AvatarUploadSignature {
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
      "AVATAR_UPLOADS_DISABLED",
      "Photo avatars aren't configured on this server yet - Cloudinary credentials are missing.",
      503,
    );
  }
}

/**
 * A player never uploads through our server - the image bytes go straight
 * from their browser to Cloudinary. We only ever hand out a short-lived
 * signature authorizing exactly one upload to exactly one publicId, which
 * keeps large binaries off this process entirely (important once a room
 * fills with 5 people all uploading a photo at once) while still stopping
 * anyone from writing to arbitrary publicIds in our Cloudinary account.
 */
export function createAvatarUploadSignature(): AvatarUploadSignature {
  assertConfigured();

  const timestamp = Math.round(Date.now() / 1000);
  // Namespaced under CLOUDINARY_AVATAR_FOLDER so deleteAvatar below can
  // safely refuse to touch anything outside it.
  const publicId = `${env.CLOUDINARY_AVATAR_FOLDER}/${nanoid(16)}`;

  const paramsToSign = {
    public_id: publicId,
    timestamp,
    transformation: AVATAR_TRANSFORMATION,
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
    transformation: AVATAR_TRANSFORMATION,
  };
}

function isOurAvatarPublicId(publicId: string): boolean {
  return publicId.startsWith(`${env.CLOUDINARY_AVATAR_FOLDER}/`);
}

/**
 * Deletes one uploaded avatar. This is what makes the photo "just for the
 * time being" real rather than a UI trick - it's called the moment a
 * player's seat is actually freed (see competitionService.ts) or a room is
 * torn down (destroyRoomAsHostLeft), and again explicitly from the frontend
 * when someone navigates away from a finished competition's results page.
 */
export async function deleteAvatar(publicId: string): Promise<void> {
  assertConfigured();
  if (!isOurAvatarPublicId(publicId)) {
    throw AppError.forbidden("Not an avatar image this server manages");
  }
  await cloudinary.uploader.destroy(publicId, { resource_type: "image" });
}

/** Fire-and-forget variant for internal cleanup paths that must never let an avatar-delete failure block a leave/teardown flow. */
export function deleteAvatarBestEffort(
  publicId: string | null | undefined,
): void {
  if (!publicId || !env.cloudinaryConfigured) return;
  if (!isOurAvatarPublicId(publicId)) return;
  cloudinary.uploader
    .destroy(publicId, { resource_type: "image" })
    .catch((err) => {
      logger.warn(
        { err, publicId },
        "failed to delete avatar from Cloudinary (non-fatal)",
      );
    });
}
