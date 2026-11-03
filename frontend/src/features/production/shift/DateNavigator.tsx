import { useState } from "react";
import { ChevronLeft, ChevronRight, Calendar } from "lucide-react";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "../../../components/ui/dialog";

interface DateNavigatorProps {
  date: string; // ISO 8601 YYYY-MM-DD
  onDateChange: (date: string) => void;
}

function addDays(date: string, days: number): string {
  const d = new Date(date + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + days);
  const year = d.getUTCFullYear();
  const month = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function DateNavigator({ date, onDateChange }: DateNavigatorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [tempDate, setTempDate] = useState(date);

  const handlePrevDay = () => onDateChange(addDays(date, -1));
  const handleNextDay = () => onDateChange(addDays(date, 1));

  const handleConfirmDate = () => {
    onDateChange(tempDate);
    setIsOpen(false);
  };

  return (
    <>
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="sm"
          onClick={handlePrevDay}
          aria-label="Previous day"
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>

        <button
          onClick={() => {
            setTempDate(date);
            setIsOpen(true);
          }}
          className="flex items-center gap-2 rounded px-3 py-1 text-sm font-medium hover:bg-muted"
          aria-label={`Select date, currently ${date}`}
        >
          <Calendar className="h-4 w-4" />
          {date}
        </button>

        <Button
          variant="ghost"
          size="sm"
          onClick={handleNextDay}
          aria-label="Next day"
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>

      <Dialog open={isOpen} onOpenChange={setIsOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Select Date</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <Input
              type="date"
              value={tempDate}
              onChange={(e) => setTempDate(e.target.value)}
              aria-label="Select date"
            />
            <div className="flex justify-end gap-2 pt-4">
              <Button variant="ghost" onClick={() => setIsOpen(false)}>
                Cancel
              </Button>
              <Button onClick={handleConfirmDate}>Apply</Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
