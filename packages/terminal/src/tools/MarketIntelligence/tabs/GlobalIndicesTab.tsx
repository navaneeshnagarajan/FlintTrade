import { useState, useMemo } from "react";
import { ArrowUpDown, TrendingDown, TrendingUp } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { GLOBAL_INDICES } from "../data";
import { DataNotice } from "../shared";
import type { GlobalIndex } from "../types";

export function GlobalIndicesTab() {
  const [sortField, setSortField] = useState<keyof GlobalIndex>("change_pct");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const sorted = useMemo(() => {
    return [...GLOBAL_INDICES].sort((a, b) => {
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

  const handleSort = (field: keyof GlobalIndex) => {
    if (sortField === field) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortDir("desc");
    }
  };

  const headers: { label: string; field: keyof GlobalIndex }[] = [
    { label: "Index", field: "name" },
    { label: "Region", field: "region" },
    { label: "LTP", field: "ltp" },
    { label: "Change", field: "change" },
    { label: "Change %", field: "change_pct" },
  ];

  return (
    <div className="p-4">
      <DataNotice text="Global indices data requires a market data provider. Showing representative values at close. Live data during market hours requires Settings configuration." />

      <div className="rounded-md border border-border-default overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="border-border-default hover:bg-transparent">
              {headers.map(({ label, field }) => (
                <TableHead
                  key={field}
                  className={["text-xs h-8 px-3 cursor-pointer select-none", sortField === field ? "text-primary" : "text-text-muted"].join(" ")}
                  onClick={() => handleSort(field)}
                >
                  {label}
                  {sortField === field && <ArrowUpDown size={9} className="inline ml-1 opacity-80" />}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.map((idx) => (
              <TableRow key={idx.name} className="border-border-default hover:bg-surface-card">
                <TableCell className="px-3 py-2">
                  <div className="text-xs font-semibold text-text-primary">{idx.name}</div>
                </TableCell>
                <TableCell className="px-3 py-2">
                  <Badge className="text-xxs h-4 px-1.5 bg-surface-card text-text-secondary border-border-default">
                    {idx.region}
                  </Badge>
                </TableCell>
                <TableCell className="px-3 py-2 font-mono text-xs text-text-primary">
                  {idx.ltp.toLocaleString("en-US", { maximumFractionDigits: 2 })}
                  <span className="text-xxs text-text-muted ml-1">{idx.currency}</span>
                </TableCell>
                <TableCell className={`px-3 py-2 font-mono text-xs ${idx.change >= 0 ? "text-profit" : "text-loss"}`}>
                  {idx.change >= 0 ? "+" : ""}{idx.change.toFixed(2)}
                </TableCell>
                <TableCell className={`px-3 py-2 font-mono text-xs font-semibold ${idx.change_pct >= 0 ? "text-profit" : "text-loss"}`}>
                  <span className="flex items-center gap-1">
                    {idx.change_pct >= 0 ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
                    {idx.change_pct >= 0 ? "+" : ""}{idx.change_pct.toFixed(2)}%
                  </span>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
