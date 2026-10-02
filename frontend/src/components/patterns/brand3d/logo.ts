/**
 * The simple 3D logo: logo-mark.svg as polished gold wire. The ring is a tube
 * that draws itself clockwise from the top (the SVG's own build), each glyph
 * stroke a round-ended tube along its path. Built from the SVG file itself.
 */
import {
  AdditiveBlending,
  Color,
  CubicBezierCurve3,
  Curve,
  CurvePath,
  Group,
  LineCurve3,
  Mesh,
  MeshBasicMaterial,
  PlaneGeometry,
  SphereGeometry,
  TubeGeometry,
  Vector3,
  type BufferGeometry,
  type Material,
} from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import logoSvg from "../../../assets/animations/logo-mark.svg?raw";
import { BRAND, goldMetal, softDisc } from "./kit";
import { parseLogoSvg, toLogoSpace } from "./logoPaths";
import type { Vec2 } from "./math";
import type { LogoState } from "./timeline";

export interface LogoOptions {
  /** Ring tube radius in logo units (the ring's radius is 0.88). */
  ringTube?: number;
  /** Multiplier on the SVG stroke widths: the bake thickens small icons. */
  strokeScale?: number;
  /** Soft additive gold glow behind the mark. */
  halo?: boolean;
}

export interface Logo3D {
  group: Group;
  set(state: LogoState): void;
  dispose(): void;
}

const RING_SEGMENTS = 256;
const RING_RADIAL = 16;

/** A circle in the logo's plane from the top, clockwise (the SVG rotates its stroke by -90°). */
class RingCurve extends Curve<Vector3> {
  constructor(private readonly radius: number) {
    super();
  }

  override getPoint(u: number, target = new Vector3()): Vector3 {
    const a = Math.PI / 2 - u * Math.PI * 2;
    return target.set(Math.cos(a) * this.radius, Math.sin(a) * this.radius, 0);
  }
}

export function createLogo({ ringTube = 0.035, strokeScale = 1, halo = true }: LogoOptions = {}): Logo3D {
  const spec = parseLogoSvg(logoSvg);
  const half = spec.viewBox / 2;
  const ringRadius = spec.ring.r / half;
  const group = new Group();
  const geometries: BufferGeometry[] = [];
  const materials: Material[] = [];

  const ringGeometry = new TubeGeometry(new RingCurve(ringRadius), RING_SEGMENTS, ringTube, RING_RADIAL, true);
  const ringMaterial = goldMetal({ emissive: new Color(BRAND.gold), emissiveIntensity: 0 });
  const ring = new Mesh(ringGeometry, ringMaterial);

  // The SVG's faint full ring under the drawn one, at 18 %.
  const faintGeometry = new TubeGeometry(new RingCurve(ringRadius), 128, ringTube * 0.6, 8, true);
  const faintMaterial = new MeshBasicMaterial({ color: BRAND.gold, transparent: true, opacity: 0, depthWrite: false });
  const faint = new Mesh(faintGeometry, faintMaterial);

  const toV = (p: Vec2) => {
    const [x, y] = toLogoSpace(p, spec);
    return new Vector3(x, y, 0);
  };
  const unit = spec.glyph.scale / half;
  const parts: BufferGeometry[] = [];
  for (const stroke of spec.glyph.strokes) {
    const radius = (stroke.width / 2) * unit * strokeScale;
    for (const sub of stroke.subpaths) {
      const path = new CurvePath<Vector3>();
      let from = sub.start;
      for (const seg of sub.segments) {
        path.add(seg.kind === "L" ? new LineCurve3(toV(from), toV(seg.to)) : new CubicBezierCurve3(toV(from), toV(seg.c1), toV(seg.c2), toV(seg.to)));
        from = seg.to;
      }
      parts.push(new TubeGeometry(path, Math.max(16, sub.segments.length * 48), radius, 12, false));
      // Round caps, like the SVG's stroke-linecap="round".
      if (!sub.closed) {
        for (const end of [sub.start, from]) {
          const v = toV(end);
          parts.push(new SphereGeometry(radius, 12, 8).translate(v.x, v.y, v.z));
        }
      }
    }
  }
  const glyphGeometry = mergeGeometries(parts);
  parts.forEach((part) => part.dispose());
  if (!glyphGeometry) throw new Error("logo: the glyph tubes could not be merged");
  const glyphMaterial = goldMetal({ transparent: true, opacity: 0 });
  const glyph = new Mesh(glyphGeometry, glyphMaterial);

  group.add(faint, ring, glyph);
  geometries.push(ringGeometry, faintGeometry, glyphGeometry);
  materials.push(ringMaterial, faintMaterial, glyphMaterial);

  let haloMaterial: MeshBasicMaterial | null = null;
  if (halo) {
    haloMaterial = new MeshBasicMaterial({ map: softDisc(128), color: BRAND.gold, transparent: true, opacity: 0, blending: AdditiveBlending, depthWrite: false });
    const haloGeometry = new PlaneGeometry(3.2, 3.2);
    const glow = new Mesh(haloGeometry, haloMaterial);
    glow.position.z = -0.3;
    group.add(glow);
    geometries.push(haloGeometry);
    materials.push(haloMaterial);
  }

  return {
    group,
    set({ ring: drawn, glyph: risen, flash }) {
      ringGeometry.setDrawRange(0, Math.floor(drawn * RING_SEGMENTS) * RING_RADIAL * 6);
      ring.visible = drawn > 0;
      ringMaterial.emissiveIntensity = flash * 5; // well above the bloom threshold: the one flash when the ring closes
      faintMaterial.opacity = 0.18 * Math.min(1, drawn * 5);
      glyph.visible = risen > 0;
      glyphMaterial.opacity = risen;
      glyph.position.y = (1 - risen) * -0.12; // rises into the ring
      if (haloMaterial) haloMaterial.opacity = 0.35 * drawn;
    },
    dispose() {
      geometries.forEach((g) => g.dispose());
      haloMaterial?.map?.dispose();
      materials.forEach((m) => m.dispose());
    },
  };
}
