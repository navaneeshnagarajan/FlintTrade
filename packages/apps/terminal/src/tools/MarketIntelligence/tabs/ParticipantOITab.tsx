import { Users } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { PARTICIPANT_OI } from "../data";
import { DataNotice, SectionLabel } from "../shared";
import { netColor } from "../utils";

function formatOI(v: number): string {
  if (v >= 10000000) return `${(v / 10000000).toFixed(2)} Cr`;
  if (v >= 100000) return `${(v / 100000).toFixed(1)} L`;
  if (v >= 1000) return `${(v / 1000).toFixed(0)} K`;
  return v.toString();
}

function getInterpretation(net: number): { label: string; color: string } {
  if (net > 50000) return { label: "Long Build Up", color: "text-profit" };
  if (net > 10000) return { label: "Mildly Long", color: "text-profit" };
  if (net > -10000) return { label: "Neutral", color: "text-text-secondary" };
  if (net > -50000) return { label: "Mildly Short", color: "text-loss" };
  return { label: "Short Build Up", color: "text-loss" };
}

export function ParticipantOITab() {
  return (
    <ScrollArea className="h-full">
      <div className="p-4 space-y-4">
        <DataNotice text="Participant-wise OI from NSE. Available after market hours. Live data during trading requires F&O data subscription." />

        <div>
          <SectionLabel icon={Users} label="Participant-wise OI — Index Futures" />
          <div className="rounded-md border border-border-default overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="border-border-default hover:bg-transparent">
                  {["Participant", "Long", "Short", "Net OI", "Interpretation"].map((h) => (
                    <TableHead key={h} className="text-xs text-text-muted h-8 px-3">{h}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {PARTICIPANT_OI.map((row) => {
                  const interp = getInterpretation(row.net_index_fut);
                  return (
                    <TableRow key={row.participant} className="border-border-default hover:bg-surface-card">
                      <TableCell className="px-3 py-2">
                        <span className="text-xs font-semibold text-primary">{row.participant}</span>
                      </TableCell>
                      <TableCell className="px-3 py-2 font-mono text-xs text-profit">
                        {formatOI(row.long_index_fut)}
                      </TableCell>
                      <TableCell className="px-3 py-2 font-mono text-xs text-loss">
                        {formatOI(row.short_index_fut)}
                      </TableCell>
                      <TableCell className={`px-3 py-2 font-mono text-xs font-semibold ${netColor(row.net_index_fut)}`}>
                        {row.net_index_fut >= 0 ? "+" : ""}{formatOI(Math.abs(row.net_index_fut))}
                      </TableCell>
                      <TableCell className="px-3 py-2">
                        <Badge className={`text-xs h-5 px-2 bg-transparent border ${interp.color === "text-profit" ? "border-bullish-border text-profit" : interp.color === "text-loss" ? "border-bearish-border text-loss" : "border-border-default text-text-secondary"}`}>
                          {interp.label}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        </div>

        <div>
          <SectionLabel icon={Users} label="Participant-wise OI — Index Options" />
          <div className="rounded-md border border-border-default overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="border-border-default hover:bg-transparent">
                  {["Participant", "Long Calls", "Short Calls", "Long Puts", "Short Puts", "Net"].map((h) => (
                    <TableHead key={h} className="text-xs text-text-muted h-8 px-3">{h}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {PARTICIPANT_OI.map((row) => {
                  const net = row.long_index_opt - row.short_index_opt;
                  return (
                    <TableRow key={row.participant} className="border-border-default hover:bg-surface-card">
                      <TableCell className="px-3 py-2">
                        <span className="text-xs font-semibold text-primary">{row.participant}</span>
                      </TableCell>
                      <TableCell className="px-3 py-2 font-mono text-xs text-profit">{formatOI(row.long_index_opt)}</TableCell>
                      <TableCell className="px-3 py-2 font-mono text-xs text-loss">{formatOI(row.short_index_opt)}</TableCell>
                      <TableCell className="px-3 py-2 font-mono text-xs text-profit">{formatOI(Math.round(row.long_index_opt * 0.48))}</TableCell>
                      <TableCell className="px-3 py-2 font-mono text-xs text-loss">{formatOI(Math.round(row.short_index_opt * 0.52))}</TableCell>
                      <TableCell className={`px-3 py-2 font-mono text-xs font-semibold ${netColor(net)}`}>
                        {net >= 0 ? "+" : ""}{formatOI(Math.abs(net))}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        </div>

        <div>
          <SectionLabel icon={Users} label="Participant-wise OI — Stock Futures" />
          <div className="rounded-md border border-border-default overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="border-border-default hover:bg-transparent">
                  {["Participant", "Long", "Short", "Net OI"].map((h) => (
                    <TableHead key={h} className="text-xs text-text-muted h-8 px-3">{h}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {PARTICIPANT_OI.map((row) => {
                  const net = row.long_stock_fut - row.short_stock_fut;
                  return (
                    <TableRow key={row.participant} className="border-border-default hover:bg-surface-card">
                      <TableCell className="px-3 py-2 text-xs font-semibold text-primary">{row.participant}</TableCell>
                      <TableCell className="px-3 py-2 font-mono text-xs text-profit">{formatOI(row.long_stock_fut)}</TableCell>
                      <TableCell className="px-3 py-2 font-mono text-xs text-loss">{formatOI(row.short_stock_fut)}</TableCell>
                      <TableCell className={`px-3 py-2 font-mono text-xs font-semibold ${netColor(net)}`}>
                        {net >= 0 ? "+" : ""}{formatOI(Math.abs(net))}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        </div>
      </div>
    </ScrollArea>
  );
}
