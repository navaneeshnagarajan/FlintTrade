import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { TableRow, TableCell } from "@/components/ui/table";

export function StatCard({
  label,
  value,
  sub,
  positive,
  icon,
}: {
  label: string;
  value: string;
  sub?: string;
  positive?: boolean;
  icon?: React.ReactNode;
}) {
  return (
    <Card className="bg-surface-card border-border-default">
      <CardContent className="p-3">
        <div className="flex items-center justify-between mb-1">
          <div className="text-xs text-text-secondary uppercase tracking-wider">
            {label}
          </div>
          {icon && (
            <div className="text-text-muted opacity-60">{icon}</div>
          )}
        </div>
        <div
          className={`text-lg font-bold font-mono tabular-nums ${
            positive === undefined
              ? "text-text-primary"
              : positive
                ? "text-profit"
                : "text-loss"
          }`}
        >
          {value}
        </div>
        {sub && (
          <div className="text-xs text-text-muted mt-0.5">{sub}</div>
        )}
      </CardContent>
    </Card>
  );
}

export function SkeletonRows({ count }: { count: number }) {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <TableRow key={i} className="border-border-subtle">
          {Array.from({ length: 10 }).map((_, j) => (
            <TableCell key={j} className="py-1.5">
              <Skeleton className="h-3 w-full bg-surface-elevated" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}
