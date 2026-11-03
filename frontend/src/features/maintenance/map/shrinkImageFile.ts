// Same budget and step-down strategy as features/scan/imagePrep.ts (12MP phone
// photo, 10MB server limit), but producing a File for a multipart upload
// instead of a base64 string for a JSON body — the view/checkpoint-map image
// endpoints take `multipart: label, image`, not JSON.
const MAX_SIDE = 4096;
const MIN_SIDE = 1200;
const MAX_BYTES = 10 * 1024 * 1024;
const QUALITIES = [0.92, 0.85, 0.75, 0.65];

function encode(canvas: HTMLCanvasElement, quality: number): Promise<Blob> {
  return new Promise<Blob>((resolve, reject) =>
    canvas.toBlob((result) => (result ? resolve(result) : reject(new Error("encode"))), "image/jpeg", quality),
  );
}

/** A photo made upright (EXIF), scaled down and re-encoded as JPEG, returned as a File ready for FormData. */
export async function shrinkImageToFile(file: File): Promise<File> {
  const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  const longest = Math.max(bitmap.width, bitmap.height);
  let side = Math.min(MAX_SIDE, longest);
  try {
    for (;;) {
      const scale = side / longest;
      const width = Math.round(bitmap.width * scale);
      const height = Math.round(bitmap.height * scale);
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      canvas.getContext("2d")!.drawImage(bitmap, 0, 0, width, height);
      let blob: Blob | null = null;
      for (const quality of QUALITIES) {
        blob = await encode(canvas, quality);
        if (blob.size <= MAX_BYTES) break;
      }
      if (blob!.size <= MAX_BYTES || side <= MIN_SIDE) {
        const name = file.name.replace(/\.[^.]+$/, "") + ".jpg";
        return new File([blob!], name, { type: "image/jpeg" });
      }
      side = Math.max(MIN_SIDE, Math.round(side * 0.8));
    }
  } finally {
    bitmap.close();
  }
}
