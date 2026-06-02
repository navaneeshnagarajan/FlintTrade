import { FlintBaselineSparkline } from "@flinttrade/design-system";
import type { EquityPoint } from "./types";

interface Props {
  curve: EquityPoint[];
}

export function EquityCurveSparkline({ curve }: Props) {
  if (curve.length < 2) return null;

  const isPositive = curve[curve.length - 1].equity >= 10000;

  return (
    <FlintBaselineSparkline
      points={curve.map((point) => point.equity)}
      baseline={10000}
      positive={isPositive}
      ariaLabel="Strategy equity curve"
      className="w-full h-10"
    />
  );
}
