/**
 * Camera framing for the brand scene. Pure. `fitDistance` keeps a composition
 * on screen at any aspect (the kit's 9:16 "narrow slice" trap); `placeInSlot`
 * puts the 3D logo exactly over a DOM box (the skill's "measure, never guess").
 */

export interface Rect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface SlotPlacement {
  x: number;
  y: number;
  z: number;
  /** World height the box covers at that depth. */
  size: number;
}

/** The logo sits this far in front of the camera in a login slot: nearer than any pasta (see motion.test.ts). */
export const LOGO_SLOT_DEPTH = 3;

const halfTan = (fovDeg: number) => Math.tan((fovDeg * Math.PI) / 360);

/** Camera distance that shows a sphere of `radius` around the target on the screen's shorter axis (vertical fov). */
export function fitDistance(radius: number, fovDeg: number, aspect: number): number {
  return radius / (halfTan(fovDeg) * Math.min(1, aspect));
}

/** Camera-space position, and world height, for an object `depth` in front of the camera to fill `rect` (CSS px) of a `vw` × `vh` viewport. */
export function placeInSlot(rect: Rect, vw: number, vh: number, fovDeg: number, depth: number): SlotPlacement {
  const halfH = depth * halfTan(fovDeg);
  const halfW = halfH * (vw / vh);
  const ndcX = ((rect.left + rect.width / 2) / vw) * 2 - 1;
  const ndcY = 1 - ((rect.top + rect.height / 2) / vh) * 2;
  return { x: ndcX * halfW, y: ndcY * halfH, z: -depth, size: (Math.min(rect.width, rect.height) / vh) * 2 * halfH };
}
