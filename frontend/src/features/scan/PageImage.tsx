import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../lib/auth";
import { Skeleton } from "../../components/ui/skeleton";
import { fetchPageImage } from "./scanApi";

export function usePageImage(pageId: string | undefined) {
  const { session } = useAuth();
  return useQuery({
    queryKey: ["scan", "page-image", pageId],
    queryFn: () => fetchPageImage(session!.token, pageId!),
    enabled: !!pageId,
    staleTime: Infinity,
    gcTime: 10 * 60_000,
  });
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
