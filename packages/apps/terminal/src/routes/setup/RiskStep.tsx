/**
 * RiskStep — risk management configuration step in the setup wizard (Advanced only).
 */

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { riskSchema } from "@/lib/schemas/riskSchema";
import type { RiskFormValues } from "@/lib/schemas/riskSchema";

export type { RiskFormValues };

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface RiskStepProps {
  onComplete: (values: RiskFormValues) => void;
  defaultValues?: Partial<RiskFormValues>;
}

export function RiskStep({ onComplete, defaultValues }: RiskStepProps) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<RiskFormValues>({
    resolver: zodResolver(riskSchema),
    defaultValues: {
      maxPositionLots:    defaultValues?.maxPositionLots    ?? 10,
      mtmStoploss:        defaultValues?.mtmStoploss        ?? 5000,
      mtmTarget:          defaultValues?.mtmTarget          ?? 10000,
      maxOrdersPerMinute: defaultValues?.maxOrdersPerMinute ?? 30,
    },
  });

  return (
    <form onSubmit={handleSubmit(onComplete)} className="space-y-5">
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <Label htmlFor="maxPositionLots" className="text-text-secondary text-xs uppercase tracking-wider">
            Position Lot Reference
          </Label>
          <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
            <Input
              id="maxPositionLots"
              type="number"
              min={0}
              title="Stored locally as a reference; current position rows are not converted to lots."
              aria-label="Position lot reference"
              className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
              {...register("maxPositionLots", { valueAsNumber: true })}
            />
          </div>
          {errors.maxPositionLots && (
            <p className="text-red-400 text-xs">{errors.maxPositionLots.message}</p>
          )}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="maxOrdersPerMinute" className="text-text-secondary text-xs uppercase tracking-wider">
            Order-Rate Reference / Min
          </Label>
          <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
            <Input
              id="maxOrdersPerMinute"
              type="number"
              min={1}
              title="Stored locally as a reference; rolling order placement rate is not currently measured."
              aria-label="Order-rate reference per minute"
              className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
              {...register("maxOrdersPerMinute", { valueAsNumber: true })}
            />
          </div>
          {errors.maxOrdersPerMinute && (
            <p className="text-red-400 text-xs">{errors.maxOrdersPerMinute.message}</p>
          )}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="mtmStoploss" className="text-text-secondary text-xs uppercase tracking-wider">
            MTM Stop-loss (INR)
          </Label>
          <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
            <Input
              id="mtmStoploss"
              type="number"
              min={0}
              title="Local MTM warning threshold; it does not automatically flatten positions."
              aria-label="MTM stoploss in INR"
              className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
              {...register("mtmStoploss", { valueAsNumber: true })}
            />
          </div>
          {errors.mtmStoploss && (
            <p className="text-red-400 text-xs">{errors.mtmStoploss.message}</p>
          )}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="mtmTarget" className="text-text-secondary text-xs uppercase tracking-wider">
            MTM Target (INR)
          </Label>
          <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
            <Input
              id="mtmTarget"
              type="number"
              min={0}
              title="Local MTM profit target used by terminal monitoring."
              aria-label="MTM profit target in INR"
              className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
              {...register("mtmTarget", { valueAsNumber: true })}
            />
          </div>
          {errors.mtmTarget && (
            <p className="text-red-400 text-xs">{errors.mtmTarget.message}</p>
          )}
        </div>
      </div>

      <p className="text-text-muted text-xs">
        These values are stored locally for terminal reference and MTM monitoring; they are not
        backend or broker enforcement. Configure backend daily-loss stops later in Settings.
      </p>

      <Button type="submit" className="w-full bg-primary hover:bg-primary/90 text-primary-foreground">
        Continue
        <ArrowRight className="size-4 ml-2" />
      </Button>
    </form>
  );
}
