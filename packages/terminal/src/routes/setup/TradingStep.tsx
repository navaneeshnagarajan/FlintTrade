/**
 * TradingStep — trading defaults configuration step in the setup wizard.
 */

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// ---------------------------------------------------------------------------
// Schema
// ---------------------------------------------------------------------------

export const tradingDefaultsSchema = z.object({
  defaultExchange: z.string().min(1, "Exchange is required"),
  defaultProduct: z.string().min(1, "Product is required"),
  defaultQty: z.number().int().min(1, "Minimum 1").max(9999, "Maximum 9999"),
});

export type TradingDefaultsFormValues = z.infer<typeof tradingDefaultsSchema>;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface TradingStepProps {
  onComplete: (values: TradingDefaultsFormValues) => void;
  defaultValues?: Partial<TradingDefaultsFormValues>;
}

export function TradingStep({ onComplete, defaultValues }: TradingStepProps) {
  const {
    register,
    handleSubmit,
    setValue,
    watch,
    formState: { errors },
  } = useForm<TradingDefaultsFormValues>({
    resolver: zodResolver(tradingDefaultsSchema),
    defaultValues: {
      defaultExchange: defaultValues?.defaultExchange ?? "NFO",
      defaultProduct: defaultValues?.defaultProduct ?? "MIS",
      defaultQty: defaultValues?.defaultQty ?? 1,
    },
  });

  const watchedExchange = watch("defaultExchange");
  const watchedProduct = watch("defaultProduct");

  return (
    <form onSubmit={handleSubmit(onComplete)} className="space-y-5">
      <div className="space-y-1.5">
        <Label className="text-text-secondary text-xs uppercase tracking-wider">
          Default Exchange
        </Label>
        <Select
          value={watchedExchange}
          onValueChange={(v) => setValue("defaultExchange", v)}
        >
          <SelectTrigger
            className="w-full bg-surface-base border-border-default text-text-primary"
            aria-label="Default exchange"
          >
            <SelectValue placeholder="Select exchange" />
          </SelectTrigger>
          <SelectContent>
            {["NSE", "BSE", "NFO", "BFO", "CDS", "MCX", "NSE_INDEX"].map((ex) => (
              <SelectItem key={ex} value={ex}>
                {ex}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {errors.defaultExchange && (
          <p className="text-red-400 text-xs">{errors.defaultExchange.message}</p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label className="text-text-secondary text-xs uppercase tracking-wider">
          Default Product
        </Label>
        <Select
          value={watchedProduct}
          onValueChange={(v) => setValue("defaultProduct", v)}
        >
          <SelectTrigger
            className="w-full bg-surface-base border-border-default text-text-primary"
            aria-label="Default product type"
          >
            <SelectValue placeholder="Select product" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="MIS">MIS — Intraday</SelectItem>
            <SelectItem value="CNC">CNC — Delivery</SelectItem>
            <SelectItem value="NRML">NRML — Normal (F&O)</SelectItem>
            <SelectItem value="BO">BO — Bracket Order</SelectItem>
            <SelectItem value="CO">CO — Cover Order</SelectItem>
          </SelectContent>
        </Select>
        {errors.defaultProduct && (
          <p className="text-red-400 text-xs">{errors.defaultProduct.message}</p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="defaultQty" className="text-text-secondary text-xs uppercase tracking-wider">
          Default Quantity / Lots
        </Label>
        <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
          <Input
            id="defaultQty"
            type="number"
            min={1}
            max={9999}
            aria-label="Default quantity or lots"
            className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
            {...register("defaultQty", { valueAsNumber: true })}
          />
        </div>
        {errors.defaultQty && (
          <p className="text-red-400 text-xs">{errors.defaultQty.message}</p>
        )}
      </div>

      <Button type="submit" className="w-full bg-primary hover:bg-primary/90 text-primary-foreground">
        Continue
        <ArrowRight className="size-4 ml-2" />
      </Button>
    </form>
  );
}
