import React, { useRef, useState } from "react";
import { Camera, X, AlertTriangle, Loader2 } from "lucide-react";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import {
  uploadAvatarPhoto,
  discardAvatar,
  AvatarUploadsDisabledError,
  type StoredAvatar,
} from "@/lib/avatarStore";

interface AvatarPickerProps {
  name: string;
  value: StoredAvatar | null;
  onChange: (avatar: StoredAvatar | null) => void;
}

/**
 * Shown wherever a player picks a display name before joining/creating a
 * room. Uploading is entirely optional - skip it and everyone (including
 * this player) just sees a generated cartoon face instead (see
 * PlayerAvatar). Whatever's picked here uploads immediately to Cloudinary
 * and is visible to every other participant in the room - it only lives
 * for this session though, see lib/avatarStore.ts.
 */
export function AvatarPicker({ name, value, onChange }: AvatarPickerProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploadsDisabled, setUploadsDisabled] = useState(false);
  const [uploading, setUploading] = useState(false);

  const handleFile = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    setUploading(true);
    try {
      const avatar = await uploadAvatarPhoto(file);
      onChange(avatar);
    } catch (err) {
      if (err instanceof AvatarUploadsDisabledError) {
        setUploadsDisabled(true);
      } else {
        setError(
          err instanceof Error ? err.message : "Couldn't use that image",
        );
      }
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  if (uploadsDisabled) return null;

  return (
    <div className="flex items-center gap-4">
      <div className="relative">
        <PlayerAvatar name={name || "Player"} src={value?.url} size="lg" />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={uploading}
          data-testid="button-pick-avatar"
          aria-label="Upload a profile photo"
          className="absolute -bottom-1 -right-1 w-6 h-6 rounded-full bg-primary text-primary-foreground flex items-center justify-center shadow-md hover:brightness-110 transition-all disabled:opacity-60"
        >
          {uploading ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Camera className="w-3.5 h-3.5" />
          )}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          onChange={(e) => handleFile(e.target.files?.[0])}
          className="hidden"
          data-testid="input-avatar-file"
        />
      </div>
      <div className="min-w-0">
        <p className="text-xs font-black uppercase tracking-wider text-muted-foreground mb-1">
          Profile photo
        </p>
        {uploading ? (
          <p className="text-xs text-muted-foreground">Uploading...</p>
        ) : value ? (
          <button
            type="button"
            onClick={() => {
              discardAvatar(value);
              onChange(null);
            }}
            data-testid="button-clear-avatar"
            className="inline-flex items-center gap-1 text-xs font-bold text-muted-foreground hover:text-destructive transition-colors"
          >
            <X className="w-3 h-3" />
            Remove photo
          </button>
        ) : (
          <p className="text-xs text-muted-foreground">
            Optional - everyone in the room will see it, just for this game.
          </p>
        )}
        {error && (
          <p className="text-xs text-destructive font-semibold mt-1 flex items-center gap-1">
            <AlertTriangle className="w-3 h-3" />
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
