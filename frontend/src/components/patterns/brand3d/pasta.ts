/**
 * The plant's pasta, modelled in code: spaghetti 1.2, coquillettes, torsadés
 * and vermicelles (seed_client_product_list.py). One instanced mesh per shape,
 * satin in the brand's gold ramp; no model files to download.
 */
import { CatmullRomCurve3, Color, DoubleSide, Euler, InstancedMesh, Matrix4, Quaternion, TubeGeometry, Vector3, type BufferGeometry } from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { mixHex } from "./color";
import { BRAND, pastaSatin } from "./kit";
import { SHAPES, type PastaShape, type PieceSeed, type Pose } from "./motion";

const tube = (points: Vector3[], radius: number, tubular: number, radial: number): TubeGeometry =>
  new TubeGeometry(new CatmullRomCurve3(points), tubular, radius, radial, false);

/** Spaghetti 1.2: a long thin rod with a gentle bow, 1.8 long. */
function spaghetti(): BufferGeometry {
  return tube(
    Array.from({ length: 9 }, (_, i) => {
      const u = i / 8 - 0.5;
      return new Vector3(u * 1.8, 0.06 * Math.cos(u * Math.PI), 0);
    }),
    0.022,
    48,
    8,
  );
}

/** Coquillette: a short open elbow (an arc of 160°); the open ends show it is hollow. */
function coquillette(): BufferGeometry {
  return tube(
    Array.from({ length: 12 }, (_, i) => {
      const a = ((-80 + (160 * i) / 11) * Math.PI) / 180;
      return new Vector3(Math.sin(a) * 0.16, Math.cos(a) * 0.16 - 0.1, 0);
    }),
    0.055,
    24,
    16,
  );
}

/** Torsadé: three strands twisted around one axis, two turns over 0.6. */
function torsade(): BufferGeometry {
  const strands = [0, 1, 2].map((k) =>
    tube(
      Array.from({ length: 40 }, (_, i) => {
        const u = i / 39;
        const a = u * Math.PI * 4 + (k * Math.PI * 2) / 3;
        return new Vector3((u - 0.5) * 0.6, Math.cos(a) * 0.05, Math.sin(a) * 0.05);
      }),
      0.032,
      64,
      8,
    ),
  );
  const merged = mergeGeometries(strands);
  strands.forEach((s) => s.dispose());
  if (!merged) throw new Error("pasta: torsadé strands could not be merged");
  return merged;
}

/** Vermicelle: a fine, short, wavy strand. */
function vermicelle(): BufferGeometry {
  return tube(
    Array.from({ length: 10 }, (_, i) => {
      const u = i / 9 - 0.5;
      return new Vector3(u * 0.5, 0.03 * Math.sin(u * 14), 0.02 * Math.cos(u * 9));
    }),
    0.012,
    32,
    6,
  );
}

const BUILDERS: Record<PastaShape, () => BufferGeometry> = { spaghetti, coquillette, torsade, vermicelle };

export interface Pasta {
  meshes: InstancedMesh[];
  update(poses: readonly Pose[]): void;
  dispose(): void;
}

export function createPasta(seeds: readonly PieceSeed[]): Pasta {
  const material = pastaSatin({ side: DoubleSide });
  const colour = new Color();
  const groups = SHAPES.map((shape) => {
    const members = seeds.filter((s) => s.shape === shape);
    const mesh = new InstancedMesh(BUILDERS[shape](), material, Math.max(1, members.length));
    mesh.count = members.length;
    mesh.frustumCulled = false; // instances move every frame; their bounds are never recomputed
    members.forEach((s, j) => mesh.setColorAt(j, colour.set(mixHex(BRAND.gold, BRAND.goldLight, s.tone))));
    return { mesh, members };
  });
  const matrix = new Matrix4();
  const rotation = new Quaternion();
  const euler = new Euler();
  const position = new Vector3();
  const scale = new Vector3();

  return {
    meshes: groups.map((g) => g.mesh),
    update(poses) {
      for (const { mesh, members } of groups) {
        members.forEach((s, j) => {
          const pose = poses[s.index];
          euler.set(pose.rotation[0], pose.rotation[1], pose.rotation[2]);
          matrix.compose(position.set(...pose.position), rotation.setFromEuler(euler), scale.setScalar(pose.scale));
          mesh.setMatrixAt(j, matrix);
        });
        mesh.instanceMatrix.needsUpdate = true;
      }
    },
    dispose() {
      for (const { mesh } of groups) {
        mesh.geometry.dispose();
        mesh.dispose();
      }
      material.dispose();
    },
  };
}
