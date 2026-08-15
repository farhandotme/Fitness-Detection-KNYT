import { getAdminToken, clearAdminSession } from "@/lib/adminApi";

function getApiBase(): string {
  return (
    import.meta.env.VITE_COMPETITION_API_URL ||
    localStorage.getItem("COMPETITION_API_BASE_OVERRIDE") ||
    "http://localhost:4000"
  ).replace(/\/+$/, "");
}

export interface UploadedEventImage {
  url: string;
  publicId: string;
}

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024; // 10MB - Cloudinary resizes/compresses server-side, this just stops absurd uploads

export class EventImageUploadsDisabledError extends Error {}

/**
 * Uploads straight from the admin's browser to Cloudinary - the image
 * never passes through our own server. We only ask the backend for a
 * one-time signed authorization first (POST /api/admin/events/image-signature),
 * which is also how Cloudinary knows to resize it into a wide banner shape
 * automatically (see competition-backend/src/services/eventImageService.ts).
 *
 * Throws EventImageUploadsDisabledError if this deployment has no
 * Cloudinary configured.
 */
export async function uploadEventImage(
  file: File,
): Promise<UploadedEventImage> {
  if (!file.type.startsWith("image/")) {
    throw new Error("Please choose an image file");
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    throw new Error("That image is too large (10MB max)");
  }

  const token = getAdminToken();
  const sigRes = await fetch(
    `${getApiBase()}/api/admin/events/image-signature`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    },
  );
  if (sigRes.status === 401) {
    clearAdminSession();
    throw new Error("Your admin session expired - please log in again");
  }
  if (sigRes.status === 503) {
    throw new EventImageUploadsDisabledError();
  }
  if (!sigRes.ok) {
    const body = await sigRes
      .json()
      .catch(() => ({ message: sigRes.statusText }));
    throw new Error(body.message || "Couldn't start the image upload");
  }
  const sig = (await sigRes.json()) as {
    cloudName: string;
    apiKey: string;
    timestamp: number;
    signature: string;
    publicId: string;
    transformation: string;
  };

  const form = new FormData();
  form.append("file", file);
  form.append("api_key", sig.apiKey);
  form.append("public_id", sig.publicId);
  form.append("timestamp", String(sig.timestamp));
  form.append("signature", sig.signature);
  form.append("transformation", sig.transformation);

  const uploadRes = await fetch(
    `https://api.cloudinary.com/v1_1/${sig.cloudName}/image/upload`,
    {
      method: "POST",
      body: form,
    },
  );
  if (!uploadRes.ok) {
    throw new Error("Image upload failed - please try again");
  }
  const uploaded = (await uploadRes.json()) as { secure_url: string };

  return { url: uploaded.secure_url, publicId: sig.publicId };
}

/** Deletes a previously uploaded cover image from Cloudinary. Safe to call for an image that was never saved to an event yet (e.g. removed from the form before submit). */
export function deleteEventImage(publicId: string): void {
  const token = getAdminToken();
  fetch(`${getApiBase()}/api/admin/events/image-delete`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ publicId }),
  }).catch(() => {
    // no-op - best effort, an orphaned Cloudinary asset isn't worth
    // blocking the admin's flow over.
  });
}
