import type { PageUpload } from "./scanApi";

// A 12-megapixel phone photo at full size. Larger sensors are scaled to it: iOS Safari cannot draw
// a canvas much over 16 million pixels, and the handwriting gains nothing past this.
const MAX_SIDE = 4096;
// Below this the handwriting is no longer worth reading; the budget gives way instead.
const MIN_SIDE = 1200;
// A page is sent as it is up to 10 MB (the server's limit); only a bigger one is compressed. It
// travels as base64 inside JSON (+33 %), which the proxies in front of the app must accept (16 MB).
// When a proxy refuses it anyway (413), the page is sent again under the next, smaller budget; the
// last one keeps the request under nginx's 1 MB default.
export const UPLOAD_BUDGETS = [10 * 1024 * 1024, 3 * 1024 * 1024, 700 * 1024];
const QUALITIES = [0.92, 0.85, 0.75, 0.65];

function toBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

function encode(canvas: HTMLCanvasElement, quality: number): Promise<Blob> {
  return new Promise<Blob>((resolve, reject) =>
    canvas.toBlob((result) => (result ? resolve(result) : reject(new Error("encode"))), "image/jpeg", quality),
  );
}

/**
 * A photo made upright (EXIF), scaled down and re-encoded as JPEG before it is sent: the quality
 * steps down first, then the size, until the page fits `maxBytes`.
 */
export async function prepareImage(file: File, maxBytes = UPLOAD_BUDGETS[0]): Promise<PageUpload> {
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
        if (blob.size <= maxBytes) break;
      }
      if (blob!.size <= maxBytes || side <= MIN_SIDE) {
        return { filename: file.name, content_type: "image/jpeg", width, height, data_base64: await toBase64(blob!) };
      }
      side = Math.max(MIN_SIDE, Math.round(side * 0.8));
    }
  } finally {
    bitmap.close();
  }
}
