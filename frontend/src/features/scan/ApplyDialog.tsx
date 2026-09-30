// Minimal stub replaced by Task 23 (the apply dialog: what will be written, blocking values, confirm).
import type { SectionKey } from "../production/shift/shiftApi";
import type { Missing } from "./reviewModel";
import type { ReviewValues, SessionDetail, ShiftState } from "./scanApi";

export function ApplyDialog(props: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  session: SessionDetail;
  values: ReviewValues;
  shift: ShiftState | null;
  writing: SectionKey[];
  missing: Missing[];
  doubts: number;
}) {
  void props;
  return null;
}
