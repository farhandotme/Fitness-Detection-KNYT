import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { generateCartoonAvatar } from "@/lib/avatarStore";
import { cn } from "@/lib/utils";

const SIZE_CLASSES = {
  sm: "h-7 w-7",
  md: "h-9 w-9",
  lg: "h-14 w-14",
  xl: "h-16 w-16 md:h-20 md:w-20",
} as const;

interface PlayerAvatarProps {
  /** Display name - shown to screen readers, no longer used to derive the fallback face (see `seed`). */
  name: string;
  /** Real photo URL, if this player uploaded one this session. Broadcast by the server to every participant in the room, not just themselves - see types/competition.ts ParticipantPublic. */
  src?: string | null;
  /**
   * What determines this player's generated cartoon face when `src` is
   * absent. Pass their stable participantId where available so their face
   * doesn't change on re-render; falls back to `name` where no id exists
   * yet (e.g. lobby room-browse previews).
   */
  seed?: string;
  size?: keyof typeof SIZE_CLASSES;
  /** Highlights this avatar as belonging to the current viewer. */
  isSelf?: boolean;
  className?: string;
}

/**
 * Every player gets an avatar - their own uploaded photo if they picked one
 * for this session (visible to everyone else in the room too), otherwise a
 * generated cartoon face that's different for every person, so the UI
 * never shows a blank/empty circle.
 */
export function PlayerAvatar({ name, src, seed, size = "md", isSelf, className }: PlayerAvatarProps) {
  const fallbackSrc = generateCartoonAvatar(seed || name || "player");
  return (
    <Avatar
      className={cn(
        SIZE_CLASSES[size],
        "shrink-0",
        isSelf && "ring-2 ring-primary ring-offset-2 ring-offset-background",
        className,
      )}
    >
      <AvatarImage src={src || fallbackSrc} alt={name} className="object-cover" />
      <AvatarFallback>
        <img src={fallbackSrc} alt={name} className="h-full w-full object-cover" />
      </AvatarFallback>
    </Avatar>
  );
}
