import { cn } from "../../../lib/utils";
import { SECTIONS } from "./sectionConfig";
import type { SectionKey, SectionState } from "./shiftApi";
import { StatusNode } from "./StatusNode";
import { T, useLabel } from "./shiftText";

const DONE = new Set(["submitted", "nothing_to_report"]);

/** The least width a step keeps; below nine of them the strip scrolls sideways rather than squeeze the names. */
const STEP_MIN_WIDTH = 104;

/**
 * The shift as the sequence it is: the fiches in paper order, one node each along a
 * horizontal line, with the short name under it. The stretch of line between two
 * sections turns green once both are handed in. Clicking a node opens that section.
 */
export function ShiftRail({
  states,
  onJump,
  className,
}: {
  states: SectionState[];
  onJump: (key: SectionKey) => void;
  className?: string;
}) {
  const label = useLabel();
  const byKey = new Map(states.map((state) => [state.key, state]));
  const statusOf = (key: SectionKey) => byKey.get(key)?.status ?? "empty";
  const done = SECTIONS.filter((section) => DONE.has(statusOf(section.key))).length;

  return (
    <nav aria-label={label(T.progress)} className={cn("rounded-xl border border-border bg-background px-3 pb-1.5 pt-2.5 shadow-soft", className)}>
      <h2 className="mb-1 text-xs font-semibold tracking-tight">
        {label(T.progress)} <span className="tabular-nums text-muted-foreground">{done}/{SECTIONS.length}</span>
      </h2>

      <div className="overflow-x-auto scrollbar-thin">
        <ol className="flex" style={{ minWidth: SECTIONS.length * STEP_MIN_WIDTH }}>
          {SECTIONS.map((section, index) => {
            const status = statusOf(section.key);
            const next = SECTIONS[index + 1];
            const tooltip = `${label(section.title)} (${label(T.status[status])})`;
            return (
              <li key={section.key} className="relative flex-1">
                {/* The line to the next node, behind both of them. */}
                {next && (
                  <span
                    aria-hidden
                    className={cn(
                      "absolute left-1/2 top-[15px] h-0.5 w-full transition-colors duration-500",
                      DONE.has(status) && DONE.has(statusOf(next.key)) ? "bg-success" : "bg-border",
                    )}
                  />
                )}
                <button
                  type="button"
                  onClick={() => onJump(section.key)}
                  title={tooltip}
                  aria-label={tooltip}
                  className="relative flex w-full flex-col items-center gap-1 rounded-md px-1 py-1.5 transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <span className="relative z-10 rounded-full bg-background">
                    <StatusNode status={status} size={20} />
                  </span>
                  <span
                    className={cn(
                      "max-w-full truncate text-[12px] leading-tight",
                      status === "returned" ? "font-medium text-destructive" : DONE.has(status) ? "text-foreground" : "text-foreground/80",
                    )}
                  >
                    {label(section.short)}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      </div>
    </nav>
  );
}
