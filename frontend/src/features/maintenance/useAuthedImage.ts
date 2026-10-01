import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../lib/auth";

/**
 * Fetches an authenticated image (the maintenance API never exposes a plain
 * `<img src>` URL — every view/checkpoint photo needs a Bearer token) as a
 * Blob, then hands back an object URL made from it, revoked on cleanup or
 * when the blob changes. Mirrors `features/scan/PageImage.tsx`'s
 * `usePageImage`.
 *
 * `fetchBlob` is the plain async function to call (e.g. `fetchViewImageBlob`,
 * `fetchCheckEntryPhotoBlob`), `id` is the resource id (fetch skipped while
 * null/undefined), and `version` is an opaque cache-buster (e.g. a view's
 * `updated_at`): it is part of the query key and is handed to `fetchBlob` too,
 * which puts it in the URL -- the server lets the browser cache a photo for a
 * day, so without it a replaced photo would still come from the browser's cache.
 */
export function useAuthedImage(
  fetchBlob: (token: string, id: string, version?: string) => Promise<Blob>,
  id: string | null | undefined,
  version?: string | number | null,
) {
  const { session } = useAuth();
  const token = session?.token;
  const query = useQuery({
    // Deliberately outside the ["maintenance"] prefix every maintenance write invalidates: a view
    // photo is versioned by `version` and an entry photo never changes, so recording a point must
    // not download the machine photo again (and blink it on screen).
    queryKey: ["maintenance-image", id, version ?? null],
    queryFn: () => fetchBlob(token!, id!, version === null || version === undefined ? undefined : String(version)),
    enabled: !!token && !!id,
    staleTime: Infinity,
    gcTime: 10 * 60_000,
  });
  const blob = query.data;
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
  return { ...query, url };
}
