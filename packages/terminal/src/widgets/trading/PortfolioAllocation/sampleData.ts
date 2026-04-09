/**
 * Sample data for PortfolioAllocationWidget — explore/disconnected mode.
 * Values are illustrative only, not real financial data.
 */

export interface AllocationSlice {
  label: string;
  value: number;
  colour: string;
}

export const SAMPLE_ASSET_ALLOCATION: AllocationSlice[] = [
  { label: "Equity",    value: 485000, colour: "#6366f1" },
  { label: "F&O",       value: 120000, colour: "#f59e0b" },
  { label: "Commodity", value:  45000, colour: "#22c55e" },
  { label: "Currency",  value:  20000, colour: "#06b6d4" },
  { label: "Cash",      value:  80000, colour: "#94a3b8" },
];

export const SAMPLE_SECTOR_ALLOCATION: AllocationSlice[] = [
  { label: "Banking",   value: 165000, colour: "#6366f1" },
  { label: "IT",        value: 140000, colour: "#8b5cf6" },
  { label: "Energy",    value:  80000, colour: "#f59e0b" },
  { label: "Auto",      value:  55000, colour: "#22c55e" },
  { label: "Pharma",    value:  45000, colour: "#10b981" },
  { label: "FMCG",      value:  40000, colour: "#06b6d4" },
  { label: "Metals",    value:  38000, colour: "#f97316" },
  { label: "Other",     value:  25000, colour: "#94a3b8" },
];
