import { useState, useMemo } from "react";
import { ArrowUpDown } from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { INDIA_SECTORS } from "../data";
import { DataNotice, ReturnBadge, TfButton } from "../shared";
import { getReturnValue } from "../utils";
import { TIMEFRAMES } from "../types";
import type { TF } from "../types";

export function SectorRotationTab() {
  const [sortTf, setSortTf] = useState<TF>("1M");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const sorted = useMemo(() => {
    return [...INDIA_SECTORS].sort((a, b) => {
      const av = getReturnValue(a, sortTf) ?? -Infinity;
      const bv = getReturnValue(b, sortTf) ?? -Infinity;
      return sortDir === "desc" ? bv - av : av - bv;
    });
  }, [sortTf, sortDir]);

  const handleTfSort = (tf: TF) => {
    if (sortTf === tf) {
      setSortDir(sortDir === "desc" ? "asc" : "desc");
    } else {
      setSortTf(tf);
      setSortDir("desc");
    }
  };

  return (
    <div className="p-4">
      <DataNotice />
      <div className="flex items-center gap-1.5 mb-3">
        <span className="text-xs text-text-muted">Sort by:</span>
        {TIMEFRAMES.map((tf) => (
          <TfButton key={tf} tf={tf} active={sortTf === tf} onClick={() => handleTfSort(tf)} />
        ))}
        <button
          onClick={() => setSortDir(sortDir === "desc" ? "asc" : "desc")}
          className="ml-auto text-xs px-2 py-0.5 rounded border bg-surface-card text-text-muted border-border-default hover:border-border-strong flex items-center gap-1"
        >
          <ArrowUpDown size={10} />
          {sortDir === "desc" ? "High to Low" : "Low to High"}
        </button>
      </div>

      <div className="rounded-md border border-border-default overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="border-border-default hover:bg-transparent">
              <TableHead className="text-xs text-text-muted h-8 px-3 w-44">Sector</TableHead>
              <TableHead className="text-xs text-text-muted h-8 px-2">Price</TableHead>
              {TIMEFRAMES.map((tf) => (
                <TableHead
                  key={tf}
                  className={["text-xs h-8 px-2 cursor-pointer select-none", sortTf === tf ? "text-primary" : "text-text-muted"].join(" ")}
                  onClick={() => handleTfSort(tf)}
                >
                  {tf}
                  {sortTf === tf && <ArrowUpDown size={9} className="inline ml-1 opacity-80" />}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.map((sector, i) => (
              <TableRow key={sector.ticker} className="border-border-default hover:bg-surface-card">
                <TableCell className="px-3 py-1.5">
                  <span className="text-xs text-text-muted mr-2 font-mono">{i + 1}</span>
                  <span className="text-xs text-text-primary">{sector.name}</span>
                </TableCell>
                <TableCell className="px-2 py-1.5 font-mono text-xs text-text-secondary">
                  {sector.current_price?.toLocaleString("en-IN", { maximumFractionDigits: 0 }) ?? "--"}
                </TableCell>
                {TIMEFRAMES.map((tf) => (
                  <TableCell key={tf} className="px-2 py-1.5">
                    <ReturnBadge value={getReturnValue(sector, tf)} size="xs" />
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
