import { Globe } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getFiiDiiData } from "@/services/ftApi.screener";
import type { FiiDiiSnapshot } from "@/services/ftApi.screener";
import { FII_DII_DATA } from "../data";
import { DataNotice, SectionLabel } from "../shared";
import { formatCr, formatOINum, netColor } from "../utils";
import type { FiiDiiRow } from "../types";

/** Days of cash-segment history to request from the backend. */
const FII_DII_DAYS = 10;

function FiiDiiTable({ rows, title }: { rows: FiiDiiRow[]; title: string }) {
  return (
    <div className="mb-5">
      <SectionLabel icon={Globe} label={title} />
      <div className="rounded-md border border-border-default overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="border-border-default hover:bg-transparent">
              {["Date", "FII Buy", "FII Sell", "FII Net", "DII Buy", "DII Sell", "DII Net"].map((h) => (
                <TableHead key={h} className="text-xs text-text-muted h-8 px-2">{h}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={`${title}-${row.date}`} className="border-border-default hover:bg-surface-card text-xs">
                <TableCell className="px-2 py-1.5 font-mono text-text-secondary">{row.date}</TableCell>
                <TableCell className="px-2 py-1.5 font-mono text-text-primary">{formatCr(row.fii_buy)}</TableCell>
                <TableCell className="px-2 py-1.5 font-mono text-text-primary">{formatCr(row.fii_sell)}</TableCell>
                <TableCell className={`px-2 py-1.5 font-mono font-semibold ${netColor(row.fii_net)}`}>
                  {row.fii_net >= 0 ? "+" : ""}{formatCr(Math.abs(row.fii_net))}
                </TableCell>
                <TableCell className="px-2 py-1.5 font-mono text-text-primary">{formatCr(row.dii_buy)}</TableCell>
                <TableCell className="px-2 py-1.5 font-mono text-text-primary">{formatCr(row.dii_sell)}</TableCell>
                <TableCell className={`px-2 py-1.5 font-mono font-semibold ${netColor(row.dii_net)}`}>
                  {row.dii_net >= 0 ? "+" : ""}{formatCr(Math.abs(row.dii_net))}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

interface DerivRow {
  label: string;
  long: number;
  short: number;
  net: number;
}

/**
 * Derivative-segment participant positioning for the latest trading day, built
 * from the real snapshot's long/short/net open-interest fields (contract counts,
 * not rupees — so these render with {@link formatOINum}, never {@link formatCr}).
 */
function DerivativeStatsTable({ snapshot }: { snapshot: FiiDiiSnapshot }) {
  const rows: DerivRow[] = [
    { label: "FII Index Futures", long: snapshot.fii_idx_fut_long, short: snapshot.fii_idx_fut_short, net: snapshot.fii_idx_fut_net },
    { label: "FII Stock Futures", long: snapshot.fii_stk_fut_long, short: snapshot.fii_stk_fut_short, net: snapshot.fii_stk_fut_net },
    { label: "FII Index Call", long: snapshot.fii_idx_call_long, short: snapshot.fii_idx_call_short, net: snapshot.fii_idx_call_net },
    { label: "FII Index Put", long: snapshot.fii_idx_put_long, short: snapshot.fii_idx_put_short, net: snapshot.fii_idx_put_net },
    { label: "DII Index Futures", long: snapshot.dii_idx_fut_long, short: snapshot.dii_idx_fut_short, net: snapshot.dii_idx_fut_net },
    { label: "DII Stock Futures", long: snapshot.dii_stk_fut_long, short: snapshot.dii_stk_fut_short, net: snapshot.dii_stk_fut_net },
  ];
  return (
    <div className="mb-5">
      <SectionLabel icon={Globe} label={`Derivative Positioning — ${snapshot.trade_date} (contracts)`} />
      <div className="rounded-md border border-border-default overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="border-border-default hover:bg-transparent">
              {["Segment", "Long", "Short", "Net"].map((h) => (
                <TableHead key={h} className="text-xs text-text-muted h-8 px-2">{h}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.label} className="border-border-default hover:bg-surface-card text-xs">
                <TableCell className="px-2 py-1.5 text-text-secondary">{r.label}</TableCell>
                <TableCell className="px-2 py-1.5 font-mono text-text-primary">{formatOINum(r.long)}</TableCell>
                <TableCell className="px-2 py-1.5 font-mono text-text-primary">{formatOINum(r.short)}</TableCell>
                <TableCell className={`px-2 py-1.5 font-mono font-semibold ${netColor(r.net)}`}>
                  {r.net >= 0 ? "+" : ""}{formatOINum(Math.abs(r.net))}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

export function FiiDiiFlowsTab() {
  const { data, isLoading } = useQuery({
    queryKey: ["screener", "fii-dii", FII_DII_DAYS],
    queryFn: () => getFiiDiiData(FII_DII_DAYS),
    staleTime: 5 * 60_000,
    refetchInterval: 5 * 60_000,
  });

  // The backend flags sample data explicitly; only then do we show the demo
  // affordance. Live data renders without it.
  const isSample = data?.is_sample_data ?? true;
  const snapshots: FiiDiiSnapshot[] = data?.trend?.snapshots?.length
    ? data.trend.snapshots
    : data?.latest
      ? [data.latest]
      : [];

  // Real cash-segment rows map field-for-field onto the table; fall back to the
  // representative sample only while the request is in flight or empty.
  const cashRows: FiiDiiRow[] = snapshots.length
    ? snapshots.map((s) => ({
        date: s.trade_date,
        fii_buy: s.fii_buy,
        fii_sell: s.fii_sell,
        fii_net: s.fii_net,
        dii_buy: s.dii_buy,
        dii_sell: s.dii_sell,
        dii_net: s.dii_net,
      }))
    : FII_DII_DATA;

  return (
    <ScrollArea className="h-full">
      <div className="p-4">
        {(isSample || !snapshots.length) && (
          <DataNotice text={isLoading ? "Loading live FII/DII flows…" : undefined} />
        )}
        <FiiDiiTable rows={cashRows} title="Capital Market Segment (₹ Cr)" />
        {data?.latest && <DerivativeStatsTable snapshot={data.latest} />}
      </div>
    </ScrollArea>
  );
}
