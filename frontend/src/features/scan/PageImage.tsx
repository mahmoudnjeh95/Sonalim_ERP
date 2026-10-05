import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../lib/auth";
import { Skeleton } from "../../components/ui/skeleton";
import { fetchPageBlob } from "./scanApi";

/**
 * Caches the photo's Blob (shared across every consumer), then hands each
 * caller its own object URL made from that blob and revoked on cleanup — so
 * thumbnails and the viewer don't fight over one URL's lifetime, and nothing
 * stays pinned in memory after use.
 */
export function usePageImage(pageId: string | undefined) {
  const { session } = useAuth();
  const query = useQuery({
    queryKey: ["scan", "page-image", pageId],
    queryFn: () => fetchPageBlob(session!.token, pageId!),
    enabled: !!pageId,
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
  return { ...query, data: url };
}

/** The photo turned the way the OCR read it, so boxes (fractions of the upright page) line up. */
export function useUpright(url: string | undefined, rotation: number): string | null {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    if (!url) return;
    if (!rotation) {
      setSrc(url);
      return;
    }
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement("canvas");
      const sideways = rotation % 180 !== 0;
      canvas.width = sideways ? image.height : image.width;
      canvas.height = sideways ? image.width : image.height;
      const context = canvas.getContext("2d")!;
      context.translate(canvas.width / 2, canvas.height / 2);
      context.rotate((rotation * Math.PI) / 180);
      context.drawImage(image, -image.width / 2, -image.height / 2);
      setSrc(canvas.toDataURL("image/jpeg", 0.85));
    };
    image.src = url;
  }, [url, rotation]);
  return src;
}

export function PageImage({ pageId, rotation, className, alt }: { pageId: string; rotation: number; className?: string; alt: string }) {
  const image = usePageImage(pageId);
  const src = useUpright(image.data, rotation);
  return src ? <img src={src} alt={alt} className={className} /> : <Skeleton className={className} />;
}
