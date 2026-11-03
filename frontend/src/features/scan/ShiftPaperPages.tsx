import { useQuery } from "@tanstack/react-query";
import { Images } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { Button } from "../../components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "../../components/ui/dialog";
import { useLabel } from "../production/shift/shiftText";
import { PageImage } from "./PageImage";
import { listShiftPages } from "./scanApi";
import { FORM_LABELS, S } from "./scanText";

/** The paper fiches a shift report was filled from, for whoever checks or validates it. */
export function ShiftPaperPages({ shiftReportId }: { shiftReportId: string }) {
  const { session } = useAuth();
  const label = useLabel();
  const pages = useQuery({ queryKey: ["scan", "shift-pages", shiftReportId], queryFn: () => listShiftPages(session!.token, shiftReportId) });
  if (!pages.data?.length) return null;
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Images className="h-4 w-4" />
          {`${label(S.paperPages)} (${pages.data.length})`}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-5xl">
        <DialogHeader>
          <DialogTitle>{label(S.paperPages)}</DialogTitle>
        </DialogHeader>
        <div className="grid grid-cols-1 max-h-[75vh] gap-3 overflow-y-auto sm:grid-cols-2">
          {pages.data.map((page) => (
            <figure key={page.id} className="space-y-1">
              <PageImage pageId={page.id} rotation={page.rotation} alt={label(S.photo)} className="w-full rounded-md border border-border" />
              <figcaption className="text-xs text-muted-foreground">{page.form_type ? label(FORM_LABELS[page.form_type]) : "—"}</figcaption>
            </figure>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
