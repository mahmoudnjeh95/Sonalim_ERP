import { Select } from "../../components/ui/select";
import { taxCodeLabel, type TaxCode } from "./api";

interface Props {
  id?: string;
  codes: TaxCode[];
  /** The line's code; null for a line that only has a rate (written before tax codes). */
  taxCode: string | null | undefined;
  rate: number;
  onChange: (taxCode: string | null, rate: number) => void;
  disabled?: boolean;
}

const RATE_PREFIX = "rate:";

/**
 * The tax of one line, chosen by code (TVA18 · 18 %, EXO · 0 %). A line that has a rate no active code carries
 * keeps it as a plain "x %" choice, so editing an old document never changes its VAT behind the user's back.
 */
export function TaxCodeSelect({ id, codes, taxCode, rate, onChange, disabled }: Props) {
  const known = taxCode ? codes.find((code) => code.code === taxCode) : undefined;
  const value = known ? known.code : `${RATE_PREFIX}${Number(rate) || 0}`;
  return (
    <Select
      id={id}
      value={value}
      disabled={disabled}
      onChange={(event) => {
        const chosen = codes.find((code) => code.code === event.target.value);
        if (chosen) onChange(chosen.code, Number(chosen.rate));
      }}
    >
      {!known && <option value={value}>{`${Number(rate) || 0} %`}</option>}
      {codes.map((code) => (
        <option key={code.id} value={code.code}>
          {taxCodeLabel(code)}
        </option>
      ))}
    </Select>
  );
}
