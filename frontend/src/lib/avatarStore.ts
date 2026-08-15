const AVATAR_KEY = "fitness_session_avatar";

function getApiBase(): string {
  return (
    import.meta.env.VITE_COMPETITION_API_URL ||
    localStorage.getItem("COMPETITION_API_BASE_OVERRIDE") ||
    "http://localhost:4000"
  ).replace(/\/+$/, "");
}

export interface StoredAvatar {
  url: string;
  publicId: string;
}

/**
 * A player's uploaded photo lives only in sessionStorage on their own
 * device (we only ever keep the Cloudinary URL/publicId here, never the
 * image itself) - so it's gone the moment the tab closes. We also delete
 * it explicitly, both from here and from Cloudinary, the moment a player
 * leaves/finishes a competition - see deleteMyAvatar() and its call sites
 * in hooks/useCompetitionRoom.ts and CompetitionResultsPage. It's a
 * "just for this game" profile picture, never a persisted account asset.
 */
export function getMyAvatar(): StoredAvatar | null {
  try {
    const raw = sessionStorage.getItem(AVATAR_KEY);
    return raw ? (JSON.parse(raw) as StoredAvatar) : null;
  } catch {
    return null;
  }
}

function setMyAvatarRecord(avatar: StoredAvatar): void {
  try {
    sessionStorage.setItem(AVATAR_KEY, JSON.stringify(avatar));
  } catch {
    // Storage full/unavailable (e.g. private browsing) - fail silently,
    // the upload already succeeded server-side; worst case it just isn't
    // remembered for a page refresh in this tab.
  }
}

function clearMyAvatarRecord(): void {
  try {
    sessionStorage.removeItem(AVATAR_KEY);
  } catch {
    // no-op
  }
}

const MAX_UPLOAD_BYTES = 8 * 1024 * 1024; // 8MB - Cloudinary crops/compresses server-side, this just stops absurd uploads

export class AvatarUploadsDisabledError extends Error {}

/**
 * Uploads straight from this browser to Cloudinary - the photo never
 * passes through our own server. We only ask our backend for a one-time
 * signed authorization first (POST /api/avatars/signature), which is also
 * how Cloudinary knows to face-crop it to a small square automatically
 * (see competition-backend/src/services/avatarService.ts).
 *
 * Throws AvatarUploadsDisabledError if this deployment has no Cloudinary
 * configured - callers should treat that as "just use the generated
 * avatar", not as an error to show the player.
 */
export async function uploadAvatarPhoto(file: File): Promise<StoredAvatar> {
  if (!file.type.startsWith("image/")) {
    throw new Error("Please choose an image file");
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    throw new Error("That image is too large (8MB max)");
  }

  const sigRes = await fetch(`${getApiBase()}/api/avatars/signature`, { method: "POST" });
  if (sigRes.status === 503) {
    throw new AvatarUploadsDisabledError();
  }
  if (!sigRes.ok) {
    const body = await sigRes.json().catch(() => ({ message: sigRes.statusText }));
    throw new Error(body.message || "Couldn't start the photo upload");
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

  const uploadRes = await fetch(`https://api.cloudinary.com/v1_1/${sig.cloudName}/image/upload`, {
    method: "POST",
    body: form,
  });
  if (!uploadRes.ok) {
    throw new Error("Photo upload failed - please try again");
  }
  const uploaded = (await uploadRes.json()) as { secure_url: string };

  const avatar: StoredAvatar = { url: uploaded.secure_url, publicId: sig.publicId };
  setMyAvatarRecord(avatar);
  return avatar;
}

/** Deletes the current player's uploaded photo, both locally and from Cloudinary. Safe to call even if nothing was ever uploaded. */
export function deleteMyAvatar(): void {
  const current = getMyAvatar();
  clearMyAvatarRecord();
  if (!current) return;
  requestServerDelete(current.publicId);
}

/**
 * Discards one specific uploaded avatar (used by AvatarPicker's "remove
 * photo" button, before the player has even joined a room). Also clears
 * sessionStorage if this happens to be the currently-remembered avatar.
 */
export function discardAvatar(avatar: StoredAvatar): void {
  const current = getMyAvatar();
  if (current?.publicId === avatar.publicId) clearMyAvatarRecord();
  requestServerDelete(avatar.publicId);
}

function requestServerDelete(publicId: string): void {
  // `keepalive` lets this request outlive the page navigation that
  // typically triggers it (leaving a room, heading home from results),
  // same idea as navigator.sendBeacon but works for us here since we need
  // a JSON body. Best-effort: if it's lost, the participant record it was
  // attached to gets torn down server-side anyway (see
  // competition-backend/src/services/competitionService.ts), which cleans
  // it up independently.
  fetch(`${getApiBase()}/api/avatars/delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ publicId }),
    keepalive: true,
  }).catch(() => {
    // no-op - best effort
  });
}

// ---------------------------------------------------------------------
// Generated cartoon avatars - shown for any player who hasn't uploaded a
// photo (or hasn't uploaded one *yet*, for other players still browsing
// the lobby). Deterministic per seed (their participantId, or their name
// where no id exists yet) so the same person keeps the same face for the
// whole session, but different players land on very different-looking
// faces - entirely generated client-side, no network calls, no third-party
// avatar service dependency.
// ---------------------------------------------------------------------

function hashStringToSeed(str: string): number {
  let h = 1779033703 ^ str.length;
  for (let i = 0; i < str.length; i++) {
    h = Math.imul(h ^ str.charCodeAt(i), 3432918353);
    h = (h << 13) | (h >>> 19);
  }
  return h >>> 0;
}

/** Mulberry32 PRNG - tiny, deterministic, good enough distribution for picking cosmetic traits. */
function mulberry32(seed: number) {
  let a = seed;
  return function next() {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function pick<T>(rand: () => number, options: readonly T[]): T {
  return options[Math.floor(rand() * options.length) % options.length];
}

const BG_COLORS = ["#F87171", "#FB923C", "#FBBF24", "#A3E635", "#34D399", "#22D3EE", "#60A5FA", "#A78BFA", "#F472B6", "#FB7185"] as const;
const SKIN_TONES = ["#FFDBB4", "#EDB98A", "#D08B5B", "#AE5D29", "#8D5524", "#5C3A21"] as const;
const HAIR_COLORS = ["#2C1B18", "#4A2C1B", "#8C5A2B", "#D4A24C", "#A85C32", "#111111", "#6B4226"] as const;

/** Cute, flat-illustration-style face - deterministic from `seed`. Returns an inline SVG data URI ready to drop straight into an <img src>. */
export function generateCartoonAvatar(seed: string): string {
  const rand = mulberry32(hashStringToSeed(seed || "player"));

  const bg = pick(rand, BG_COLORS);
  const skin = pick(rand, SKIN_TONES);
  const hairColor = pick(rand, HAIR_COLORS);
  const hairStyle = pick(rand, ["bald", "short", "curly", "bun", "long", "flat-top"] as const);
  const eyeStyle = pick(rand, ["dot", "open", "happy", "wink"] as const);
  const browStyle = pick(rand, ["flat", "angled", "raised"] as const);
  const mouthStyle = pick(rand, ["smile", "grin", "flat", "o"] as const);
  const hasBlush = rand() < 0.5;
  const hasGlasses = rand() < 0.3;

  const eye = (cx: number) => {
    switch (eyeStyle) {
      case "dot":
        return `<circle cx="${cx}" cy="62" r="3.2" fill="#20241f"/>`;
      case "open":
        return `<ellipse cx="${cx}" cy="62" rx="4.5" ry="5.5" fill="#20241f"/>`;
      case "happy":
        return `<path d="M ${cx - 5} 62 Q ${cx} 56 ${cx + 5} 62" stroke="#20241f" stroke-width="2.6" fill="none" stroke-linecap="round"/>`;
      case "wink":
        return cx < 50
          ? `<path d="M ${cx - 5} 62 Q ${cx} 57 ${cx + 5} 62" stroke="#20241f" stroke-width="2.6" fill="none" stroke-linecap="round"/>`
          : `<ellipse cx="${cx}" cy="62" rx="4.5" ry="5.5" fill="#20241f"/>`;
    }
  };

  const brow = (cx: number, side: "l" | "r") => {
    switch (browStyle) {
      case "flat":
        return `<rect x="${cx - 6}" y="50" width="12" height="2.4" rx="1.2" fill="${hairColor}"/>`;
      case "angled":
        return `<path d="M ${cx - 6} ${side === "l" ? 52 : 49} L ${cx + 6} ${side === "l" ? 49 : 52}" stroke="${hairColor}" stroke-width="2.4" stroke-linecap="round"/>`;
      case "raised":
        return `<path d="M ${cx - 6} 51 Q ${cx} 47 ${cx + 6} 51" stroke="${hairColor}" stroke-width="2.4" fill="none" stroke-linecap="round"/>`;
    }
  };

  const mouth = () => {
    switch (mouthStyle) {
      case "smile":
        return `<path d="M 43 78 Q 50 84 57 78" stroke="#7a3b2e" stroke-width="2.6" fill="none" stroke-linecap="round"/>`;
      case "grin":
        return `<path d="M 41 77 Q 50 88 59 77 Z" fill="#7a3b2e"/>`;
      case "flat":
        return `<rect x="43" y="79" width="14" height="2.2" rx="1.1" fill="#7a3b2e"/>`;
      case "o":
        return `<ellipse cx="50" cy="80" rx="4" ry="5" fill="#7a3b2e"/>`;
    }
  };

  const hair = () => {
    switch (hairStyle) {
      case "bald":
        return "";
      case "short":
        return `<path d="M 22 46 Q 22 12 50 12 Q 78 12 78 46 L 78 38 Q 78 22 50 22 Q 22 22 22 38 Z" fill="${hairColor}"/>`;
      case "curly":
        return `<g fill="${hairColor}"><circle cx="26" cy="30" r="10"/><circle cx="38" cy="18" r="11"/><circle cx="52" cy="14" r="11"/><circle cx="66" cy="18" r="11"/><circle cx="76" cy="30" r="10"/></g>`;
      case "bun":
        return `<path d="M 22 44 Q 22 14 50 14 Q 78 14 78 44 L 78 34 Q 78 24 50 24 Q 22 24 22 34 Z" fill="${hairColor}"/><circle cx="50" cy="8" r="8" fill="${hairColor}"/>`;
      case "long":
        return `<path d="M 20 70 Q 16 20 50 12 Q 84 20 80 70 L 74 70 Q 76 30 50 22 Q 24 30 26 70 Z" fill="${hairColor}"/>`;
      case "flat-top":
        return `<rect x="26" y="10" width="48" height="20" rx="4" fill="${hairColor}"/>`;
    }
  };

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <circle cx="50" cy="50" r="50" fill="${bg}"/>
  <circle cx="50" cy="56" r="30" fill="${skin}"/>
  ${hasBlush ? `<circle cx="32" cy="70" r="5" fill="#F87171" opacity="0.35"/><circle cx="68" cy="70" r="5" fill="#F87171" opacity="0.35"/>` : ""}
  ${brow(38, "l")}
  ${brow(62, "r")}
  ${eye(38)}
  ${eye(62)}
  ${mouth()}
  ${hasGlasses ? `<g stroke="#20241f" stroke-width="2" fill="none" opacity="0.75"><circle cx="38" cy="62" r="9"/><circle cx="62" cy="62" r="9"/><line x1="47" y1="62" x2="53" y2="62"/></g>` : ""}
  ${hair()}
</svg>`;

  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}
