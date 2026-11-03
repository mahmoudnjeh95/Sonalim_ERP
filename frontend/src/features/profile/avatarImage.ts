// A profile photo is shown at 28-96px; 256 keeps it crisp on a retina screen and
// leaves the stored row at a few tens of kilobytes.
const AVATAR_SIDE = 256;

function toBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

/**
 * A chosen photo made upright (EXIF), cropped to its centre square and re-encoded small.
 * Doing it here rather than server-side keeps the upload itself tiny on the plant's network.
 */
export async function prepareAvatar(file: File): Promise<string> {
  const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  const side = Math.min(bitmap.width, bitmap.height);
  const sourceX = (bitmap.width - side) / 2;
  const sourceY = (bitmap.height - side) / 2;
  const canvas = document.createElement("canvas");
  canvas.width = AVATAR_SIDE;
  canvas.height = AVATAR_SIDE;
  canvas.getContext("2d")!.drawImage(bitmap, sourceX, sourceY, side, side, 0, 0, AVATAR_SIDE, AVATAR_SIDE);
  bitmap.close();
  const blob = await new Promise<Blob>((resolve, reject) =>
    canvas.toBlob((result) => (result ? resolve(result) : reject(new Error("encode"))), "image/jpeg", 0.85),
  );
  return await toBase64(blob);
}
