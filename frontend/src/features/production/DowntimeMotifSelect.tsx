import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { useI18n } from "../../lib/i18n";

export const DOWNTIME_MOTIFS = [
  "format_change",
  "cleaning_extruder",
  "cleaning_dryer",
  "scheduled_maintenance",
  "team_break",
  "end_of_production",
  "extruder_failure",
  "die_jam",
  "dryer_failure",
  "cutter_failure",
  "packaging_failure",
  "film_jam",
  "conveyor_failure",
  "electrical_failure",
  "pneumatic_failure",
  "steam_failure",
  "semolina_shortage",
  "water_shortage",
  "dough_nonconformity",
  "qc_hold",
  "packaging_supply_shortage",
  "operator_shortage",
  "work_order_missing",
  "security_incident",
  "product_evacuation_pending",
  "other",
] as const;

export type DowntimeMotif = (typeof DOWNTIME_MOTIFS)[number];

/** What kind of intervention a stoppage was. */
export const DOWNTIME_TYPES = ["preventive", "corrective", "maintenance", "cleaning"] as const;
export type DowntimeType = (typeof DOWNTIME_TYPES)[number];

/** Which system a stoppage hit. */
export const DOWNTIME_CLASSIFICATIONS = [
  "pneumatic",
  "electric",
  "electronic",
  "mechanical",
  "hydraulic",
  "it",
  "other",
] as const;
export type DowntimeClassification = (typeof DOWNTIME_CLASSIFICATIONS)[number];

export function DowntimeMotifSelect({
  id,
  value,
  onChange,
  label,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  label?: string;
}) {
  const { t } = useI18n();

  const motifLabel = (motif: DowntimeMotif) =>
    t(`production.downtime.motif.${motif}` as Parameters<typeof t>[0]);

  return (
    <div className="space-y-1">
      {label && (
        <Label htmlFor={id} className="text-xs">
          {label}
        </Label>
      )}
      <Select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">—</option>
        {DOWNTIME_MOTIFS.map((motif) => (
          <option key={motif} value={motif}>
            {motifLabel(motif)}
          </option>
        ))}
      </Select>
    </div>
  );
}
