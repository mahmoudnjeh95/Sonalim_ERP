import { useEffect, useState } from "react";
import { cn } from "../../lib/utils";
import { useMyAvatar } from "./api";

/** The person's initials, from their name when there is one and their e-mail otherwise. */
export function initialsOf(name: string | null | undefined, email: string | null | undefined): string {
  const source = (name ?? "").trim() || (email ?? "").split("@")[0]?.replace(/[._-]+/g, " ") || "";
  const parts = source.split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  const letters = parts.length === 1 ? parts[0].slice(0, 2) : parts[0][0] + parts[parts.length - 1][0];
  return letters.toUpperCase();
}

/**
 * The signed-in person's photo, or their initials until they set one.
 *
 * The blob is cached once by useMyAvatar and each consumer makes its own object URL
 * (revoked on cleanup), so the sidebar and the profile page never fight over one URL's
 * lifetime -- the same arrangement as the scan module's page images.
 */
export function UserAvatar({
  name,
  email,
  className,
}: {
  name: string | null | undefined;
  email: string | null | undefined;
  className?: string;
}) {
  const { data: blob } = useMyAvatar();
  const [url, setUrl] = useState<string | undefined>(undefined);

  useEffect(() => {
    if (!blob) {
      setUrl(undefined);
      return;
    }
    const objectUrl = URL.createObjectURL(blob);
    setUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [blob]);

  const shape = cn("shrink-0 overflow-hidden rounded-full object-cover", className);
  if (url) return <img src={url} alt="" className={shape} />;
  return (
    <span
      aria-hidden
      className={cn(
        shape,
        "flex items-center justify-center bg-gradient-to-br from-primary/15 to-accent/15 text-[0.7em] font-semibold text-primary",
      )}
    >
      {initialsOf(name, email)}
    </span>
  );
}
