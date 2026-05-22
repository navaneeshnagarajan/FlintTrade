/**
 * SIPCard — Active SIPs list with next date.
 */

import { BentoCard } from "@/components/bento/BentoCard";
import { RefreshCw } from "lucide-react";
import { format, addDays } from "date-fns";

interface SIPItem {
  id: string;
  fundName: string;
  amount: number;
  nextDate: Date;
}

// Placeholder SIPs — will come from MF API in Phase 2
const PLACEHOLDER_SIPS: SIPItem[] = [
  { id: "1", fundName: "Nifty Index Fund",   amount: 5000,  nextDate: addDays(new Date(), 3) },
  { id: "2", fundName: "Flexi Cap Fund",     amount: 3000,  nextDate: addDays(new Date(), 7) },
  { id: "3", fundName: "Mid Cap 150 Index",  amount: 2000,  nextDate: addDays(new Date(), 12) },
];

export function SIPCard() {
  return (
    <BentoCard size="default" label="Active SIPs" data-testid="sip-card">
      <div className="p-4 h-full flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <RefreshCw size={13} className="text-text-muted" aria-hidden="true" />
          <p className="text-[10px] font-medium uppercase tracking-widest text-text-muted">
            Active SIPs
          </p>
        </div>

        <div className="flex-1 space-y-2">
          {PLACEHOLDER_SIPS.map((sip) => (
            <div
              key={sip.id}
              className="flex items-center justify-between py-1"
            >
              <div className="min-w-0">
                <p className="text-xs text-text-primary truncate">{sip.fundName}</p>
                <p className="text-[10px] text-text-muted">
                  Next: {format(sip.nextDate, "dd MMM")}
                </p>
              </div>
              <span className="font-mono text-xs font-medium text-text-secondary shrink-0 ml-2">
                ₹{sip.amount.toLocaleString("en-IN")}
              </span>
            </div>
          ))}
        </div>
      </div>
    </BentoCard>
  );
}
