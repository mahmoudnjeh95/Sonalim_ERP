import stageConditionnement from "../../../assets/illustrations/production/stage-conditionnement.webp";
import stageExtrusion from "../../../assets/illustrations/production/stage-extrusion.webp";
import stageMelange from "../../../assets/illustrations/production/stage-melange.webp";
import MachineSvg from "../../../assets/icons/maintenance/machine.svg?react";
import { outlineIcon } from "../../../components/patterns/outlineIcon";
import { cn } from "../../../lib/utils";
import { fetchViewImageBlob, type ProductionStage } from "../api";
import { useAuthedImage } from "../useAuthedImage";
import type { MachineSummary } from "./api";

const MachineIcon = outlineIcon(MachineSvg);

const STAGE_ART: Record<ProductionStage, string> = {
  versement: stageMelange,
  extrusion: stageExtrusion,
  conditionnement: stageConditionnement,
};

/** The machine's own photo (the first view of its plan); else its stage's artwork; else the machine icon. */
function useMachinePicture(machine: MachineSummary): { src: string | null; isPhoto: boolean } {
  const { url } = useAuthedImage(fetchViewImageBlob, machine.photo_view_id, machine.photo_version);
  if (url) return { src: url, isPhoto: true };
  if (machine.production_stage) return { src: STAGE_ART[machine.production_stage], isPhoto: false };
  return { src: null, isPhoto: false };
}

// The brand navy of the login page, as a radial tile behind the machine.
const TILE = "relative grid place-items-center overflow-hidden bg-[radial-gradient(circle_at_50%_65%,#1A4A85_0%,#082B57_60%,#071F43_100%)]";

export function MachinePhotoTile({ machine, caption, className }: { machine: MachineSummary; caption?: string; className?: string }) {
  const { src, isPhoto } = useMachinePicture(machine);
  return (
    <div className={cn(TILE, "rounded-xl", className)}>
      {src ? (
        <img
          src={src}
          alt=""
          className={isPhoto ? "h-full w-full object-cover" : "w-[115%] max-w-none drop-shadow-[0_10px_18px_rgba(0,0,0,0.35)]"}
        />
      ) : (
        <MachineIcon aria-hidden className="h-12 w-12 text-white/70" />
      )}
      {caption && isPhoto && (
        <span className="absolute bottom-2 left-2 text-[10px] uppercase tracking-[0.14em] text-white/80">{caption}</span>
      )}
    </div>
  );
}

export function MachineThumb({ machine }: { machine: MachineSummary }) {
  const { src, isPhoto } = useMachinePicture(machine);
  return (
    <span className={cn(TILE, "h-7 w-9 shrink-0 rounded-md")}>
      {src ? (
        <img src={src} alt="" className={isPhoto ? "h-full w-full object-cover" : "w-[125%] max-w-none"} />
      ) : (
        <MachineIcon aria-hidden className="h-4 w-4 text-white/70" />
      )}
    </span>
  );
}
