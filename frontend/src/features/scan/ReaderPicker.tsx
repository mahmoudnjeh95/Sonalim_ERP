import { Cloud, Server } from "lucide-react";
import { cn } from "../../lib/utils";
import { useLabel } from "../production/shift/shiftText";
import type { Reader, ReadersInfo } from "./scanApi";
import { READER_HINTS, READER_LABELS, S } from "./scanText";

const ICONS = { ocr: Server, claude: Cloud } as const;
const READERS: Reader[] = ["ocr", "claude"];

/** Local OCR or Claude: a two-way switch, with what each choice means for the photos. */
export function ReaderPicker({
  value, readers, onChange, disabled,
}: { value: Reader; readers: ReadersInfo | undefined; onChange: (reader: Reader) => void; disabled?: boolean }) {
  const label = useLabel();
  return (
    <div className="space-y-1">
      <div role="radiogroup" aria-label={label(S.reader)} className="inline-flex rounded-md border border-border p-0.5">
        {READERS.map((reader) => {
          const Icon = ICONS[reader];
          const available = readers?.available[reader] ?? false;
          const selected = value === reader;
          return (
            <button
              key={reader}
              type="button"
              role="radio"
              aria-checked={selected}
              disabled={disabled || !available}
              title={available ? label(READER_HINTS[reader]) : label(S.readerUnavailable)}
              onClick={() => !selected && onChange(reader)}
              className={cn(
                "inline-flex h-8 items-center gap-1.5 rounded px-3 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
                selected ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted",
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {label(READER_LABELS[reader])}
            </button>
          );
        })}
      </div>
      <p className="text-xs text-muted-foreground">{label(READER_HINTS[value])}</p>
    </div>
  );
}
