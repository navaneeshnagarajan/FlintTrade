import { useState, useMemo } from "react";
import { ArrowUpDown } from "lucide-react";
import { FlintLinearMeter } from "@flinttrade/design-system";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DELIVERY_DATA } from "../data";
import { DataNotice } from "../shared";
import type { DeliveryRow } from "../types";

export function DeliveryDataTab() {
  const [sortField, setSortField] = useState<keyof DeliveryRow>("delivery_pct");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const sorted = useMemo(() => {
    return [...DELIVERY_DATA].sort((a, b) => {
      const av = a[sortField];
      const bv = b[sortField];
      if (typeof av === "number" && typeof bv === "number") {
        return sortDir === "desc" ? bv - av : av - bv;
      }
      return sortDir === "desc"
        ? String(bv).localeCompare(String(av))
        : String(av).localeCompare(String(bv));
    });
  }, [sortField, sortDir]);

  const handleSort = (field: keyof DeliveryRow) => {
    if (sortField === field) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else { setSortField(field); setSortDir("desc"); }
  };

  const headers: { label: string; field: keyof DeliveryRow }[] = [
    { label: "Symbol", field: "symbol" },
    { label: "Open", field: "open" },
    { label: "High", field: "high" },
    { label: "Low", field: "low" },
    { label: "Close", field: "close" },
    { label: "Volume (L)", field: "volume_lakh" },
    { label: "Delivery %", field: "delivery_pct" },
  ];

  const sortStateFor = (field: keyof DeliveryRow) => {
    if (sortField !== field) return "none";
    return sortDir === "asc" ? "ascending" : "descending";
  };

  return (
    <div className="p-4">
      <DataNotice text="Delivery data from NSE bhavcopy. Available after 6 PM on trading days. High delivery % indicates institutional interest and conviction." />

      <div className="rounded-md border border-border-default overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="border-border-default hover:bg-transparent">
              {headers.map(({ label, field }) => (
                <TableHead
                  key={field}
                  aria-sort={sortStateFor(field)}
                  className={["h-8 px-2 text-xs", sortField === field ? "text-primary" : "text-text-muted"].join(" ")}
                >
                  <button
                    type="button"
                    aria-label={`Sort by ${label}`}
                    className="inline-flex items-center gap-1 rounded-sm text-left hover:text-primary focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary"
                    onClick={() => handleSort(field)}
                  >
                    <span>{label}</span>
                    {sortField === field && <ArrowUpDown size={9} className="opacity-80" aria-hidden="true" />}
                  </button>
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.map((row) => {
              const changeAmt = row.close - row.open;
              const changePct = ((changeAmt / row.open) * 100);
              const deliveryColor = row.delivery_pct >= 60 ? "text-profit" : row.delivery_pct >= 45 ? "text-warning" : "text-text-secondary";
              const deliveryFill = row.delivery_pct >= 60 ? "#10b981" : row.delivery_pct >= 45 ? "#f59e0b" : "#6b7280";
              return (
                <TableRow key={row.symbol} className="border-border-default hover:bg-surface-card">
                  <TableCell className="px-2 py-1.5">
                    <div className="text-xs font-semibold font-mono text-primary">{row.symbol}</div>
                    <div className={`text-xs font-mono ${changePct >= 0 ? "text-profit" : "text-loss"}`}>
                      {changePct >= 0 ? "+" : ""}{changePct.toFixed(2)}%
                    </div>
                  </TableCell>
                  <TableCell className="px-2 py-1.5 font-mono text-xs text-text-secondary">{row.open.toFixed(1)}</TableCell>
                  <TableCell className="px-2 py-1.5 font-mono text-xs text-profit">{row.high.toFixed(1)}</TableCell>
                  <TableCell className="px-2 py-1.5 font-mono text-xs text-loss">{row.low.toFixed(1)}</TableCell>
                  <TableCell className="px-2 py-1.5 font-mono text-xs text-text-primary">{row.close.toFixed(1)}</TableCell>
                  <TableCell className="px-2 py-1.5 font-mono text-xs text-text-secondary">{row.volume_lakh.toFixed(1)}L</TableCell>
                  <TableCell className="px-2 py-1.5">
                    <div className="flex items-center gap-2">
                      <FlintLinearMeter
                        ariaLabel={`${row.symbol} delivery percentage`}
                        value={row.delivery_pct}
                        fillColor={deliveryFill}
                        heightClassName="h-1.5"
                        className="flex-1"
                      />
                      <span className={`font-mono text-xs font-semibold w-10 text-right ${deliveryColor}`}>
                        {row.delivery_pct.toFixed(1)}%
                      </span>
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-center gap-4 mt-3 text-xs">
        <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-400 inline-block" /><span className="text-text-muted">High delivery ≥60%</span></div>
        <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-400 inline-block" /><span className="text-text-muted">Medium 45–60%</span></div>
        <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-gray-500 inline-block" /><span className="text-text-muted">Low &lt;45%</span></div>
      </div>
    </div>
  );
}
