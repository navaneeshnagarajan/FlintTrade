import { Globe } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { FII_DII_DATA } from "../data";
import { DataNotice, SectionLabel } from "../shared";
import { formatCr, netColor } from "../utils";
import type { FiiDiiRow } from "../types";

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

export function FiiDiiFlowsTab() {
  const cashRows = FII_DII_DATA;
  const derivRows: FiiDiiRow[] = [
    { date: "2024-12-27", fii_buy: 184200, fii_sell: 168400, fii_net: 15800, dii_buy: 42800, dii_sell: 38400, dii_net: 4400 },
    { date: "2024-12-26", fii_buy: 152400, fii_sell: 174200, fii_net: -21800, dii_buy: 38400, dii_sell: 29800, dii_net: 8600 },
    { date: "2024-12-24", fii_buy: 198400, fii_sell: 142000, fii_net: 56400, dii_buy: 28400, dii_sell: 34200, dii_net: -5800 },
    { date: "2024-12-23", fii_buy: 124800, fii_sell: 198400, fii_net: -73600, dii_buy: 48200, dii_sell: 28800, dii_net: 19400 },
    { date: "2024-12-20", fii_buy: 168400, fii_sell: 148200, fii_net: 20200, dii_buy: 32800, dii_sell: 42400, dii_net: -9600 },
  ];

  return (
    <ScrollArea className="h-full">
      <div className="p-4">
        <DataNotice />
        <FiiDiiTable rows={cashRows} title="Capital Market Segment (₹ Cr)" />
        <FiiDiiTable rows={derivRows} title="Derivative Segment (₹ Cr)" />
      </div>
    </ScrollArea>
  );
}
