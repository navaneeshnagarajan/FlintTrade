// Adapted patterns from:
//   openalgo-chart/src/components/OptionChainPicker/OptionChainPicker.jsx — multi-leg state, strategy templates, direction (buy/sell), net premium calc
//   openalgo-chart/src/services/strategyTemplates.js — STRATEGY_TEMPLATES, calculateNetPremium, validateStrategy, formatStrategyName

import { useEffect, useRef, useState } from "react";
import { Brain, TrendingUp, Zap, Code2, X } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { UNDERLYINGS, STRATEGY_TEMPLATES } from "./types";
import type { Leg, Underlying } from "./types";
import { calculateNetPremium, formatINR, genId } from "./utils";
import {
  LOAD_TEMPLATE_EVENT,
  readAndClearPendingTemplate,
  type BuilderTemplate,
} from "./templateBridge";
import { LegsTab } from "./LegsTab";
import { PayoffTab } from "./PayoffTab";
import { MarginTab } from "./MarginTab";
import { PineTab } from "./PineTab";

interface Props {
  onClose?: () => void;
}

export default function StrategyBuilderTool({ onClose }: Props) {
  const [legs, setLegs] = useState<Leg[]>([]);
  const [underlying, setUnderlying] = useState<Underlying>(UNDERLYINGS[0]);
  const [atm, setAtm] = useState(UNDERLYINGS[0].symbol === "NIFTY" ? 22500 : 48000);
  const [strikeGap, setStrikeGap] = useState(UNDERLYINGS[0].strikeGap);

  const netPremium = calculateNetPremium(legs);

  const handleUnderlyingChange = (symbol: string) => {
    const u = UNDERLYINGS.find((u) => u.symbol === symbol) ?? UNDERLYINGS[0];
    setUnderlying(u);
    setStrikeGap(u.strikeGap);
    // Rough ballpark seeds only — the operator sets the real ATM from the
    // live chain. Every catalogued underlying gets its OWN seed (MIDCPNIFTY
    // previously inherited NIFTY's level, an order of magnitude off).
    const ATM_SEEDS: Record<string, number> = {
      NIFTY: 22500,
      BANKNIFTY: 48000,
      FINNIFTY: 22000,
      MIDCPNIFTY: 12500,
      SENSEX: 80000,
    };
    setAtm(ATM_SEEDS[symbol] ?? 22500);
    setLegs([]);
  };

  const handleAdd = () => {
    setLegs((prev) => [
      ...prev,
      { id: genId(), action: "BUY", optionType: "CE", strike: atm, lots: 1, premium: 0 },
    ]);
  };

  const handleRemove = (id: string) => {
    setLegs((prev) => prev.filter((l) => l.id !== id));
  };

  const handleChange = (id: string, field: keyof Leg, value: unknown) => {
    setLegs((prev) => prev.map((l) => (l.id === id ? { ...l, [field]: value } : l)));
  };

  // Apply template — adapted from OptionChainPicker's applyTemplate logic
  const handleTemplate = (key: string) => {
    const tmpl = STRATEGY_TEMPLATES[key];
    if (!tmpl) return;
    const newLegs: Leg[] = tmpl.legs.map((lt) => ({
      id: genId(),
      action: lt.action,
      optionType: lt.optionType,
      strike: atm + lt.strikeOffset * strikeGap,
      lots: lt.lots,
      premium: 0,
    }));
    setLegs(newLegs);
  };

  // Apply a hand-off template from the StrategyTemplates widget — same
  // strike maths as handleTemplate, but the legs arrive via templateBridge.
  // validateLegs caps at 6 legs, so trim anything longer.
  const applyBridgeTemplate = (tmpl: BuilderTemplate) => {
    const newLegs: Leg[] = tmpl.legs.slice(0, 6).map((lt) => ({
      id: genId(),
      action: lt.action,
      optionType: lt.optionType,
      strike: atm + lt.strikeOffset * strikeGap,
      lots: Math.max(1, lt.lots),
      premium: 0,
    }));
    setLegs(newLegs);
  };

  // Latest-ref so the mount-time stash read and the live event listener both
  // see current ATM/strike-gap without re-registering on every change.
  const applyBridgeTemplateRef = useRef(applyBridgeTemplate);
  useEffect(() => {
    applyBridgeTemplateRef.current = applyBridgeTemplate;
  });

  useEffect(() => {
    const pending = readAndClearPendingTemplate();
    if (pending) applyBridgeTemplateRef.current(pending);

    const onLoad = (e: Event) => {
      const detail = (e as CustomEvent).detail as BuilderTemplate | undefined;
      if (detail && Array.isArray(detail.legs) && detail.legs.length > 0) {
        applyBridgeTemplateRef.current(detail);
      }
    };
    window.addEventListener(LOAD_TEMPLATE_EVENT, onLoad);
    return () => window.removeEventListener(LOAD_TEMPLATE_EVENT, onLoad);
  }, []);

  return (
    <div className="h-full flex flex-col bg-surface-base">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border-default bg-surface-card shrink-0">
        <div className="flex items-center gap-2">
          <Brain size={16} className="text-primary" />
          <h1 className="font-heading font-bold text-lg text-text-primary">Strategy Builder</h1>
          <Badge variant="outline" className="text-xxs border-border-default text-text-muted font-normal">
            {underlying.symbol}
          </Badge>
          {legs.length > 0 && (
            <Badge
              variant="outline"
              className={`text-xxs px-1.5 border-0 font-mono ${netPremium <= 0 ? "bg-emerald-900/40 text-emerald-400" : "bg-red-900/40 text-red-400"}`}
            >
              {netPremium <= 0 ? "Credit" : "Debit"} {formatINR(Math.abs(netPremium))}
            </Badge>
          )}
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label="Close the builder (discards the current legs)"
          title="Close the builder (discards the current legs)"
          className="h-6 w-6 text-text-muted hover:text-text-primary"
        >
          <X size={15} />
        </Button>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="legs" className="flex-1 flex flex-col min-h-0">
        <TabsList className="shrink-0 rounded-none bg-surface-base border-b border-border-default justify-start px-3 h-8 gap-1">
          <TabsTrigger value="legs"   className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted">
            <Brain      size={11} className="mr-1" aria-hidden="true" />Strategy Legs
          </TabsTrigger>
          <TabsTrigger value="payoff" className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted">
            <TrendingUp size={11} className="mr-1" aria-hidden="true" />Payoff
          </TabsTrigger>
          <TabsTrigger value="margin" className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted">
            <Zap        size={11} className="mr-1" aria-hidden="true" />Margin
          </TabsTrigger>
          <TabsTrigger value="pine"   className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted">
            <Code2      size={11} className="mr-1" aria-hidden="true" />Pine Script
          </TabsTrigger>
        </TabsList>

        <TabsContent value="legs" className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden">
          <LegsTab
            legs={legs}
            onAdd={handleAdd}
            onRemove={handleRemove}
            onChange={handleChange}
            onTemplate={handleTemplate}
            atm={atm}
            onAtmChange={setAtm}
            underlying={underlying}
            onUnderlyingChange={handleUnderlyingChange}
            strikeGap={strikeGap}
            onStrikeGapChange={setStrikeGap}
          />
        </TabsContent>

        <TabsContent value="payoff" className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden">
          <PayoffTab legs={legs} atm={atm} underlying={underlying} />
        </TabsContent>

        <TabsContent value="margin" className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden">
          <MarginTab legs={legs} underlying={underlying} />
        </TabsContent>

        <TabsContent value="pine" className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden">
          <PineTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
