import { FlaskConical, PlayCircle, TrendingUp, BarChart3, Code2 } from "lucide-react";

export type TabId = "backtest" | "forward-test" | "optimize" | "results" | "pine-editor";

export interface TabDef {
  id: TabId;
  label: string;
  icon: typeof FlaskConical;
}

export const TABS: TabDef[] = [
  { id: "backtest", label: "Backtest", icon: FlaskConical },
  { id: "forward-test", label: "Forward Test", icon: PlayCircle },
  { id: "optimize", label: "Optimize", icon: TrendingUp },
  { id: "results", label: "Results", icon: BarChart3 },
  { id: "pine-editor", label: "Pine Editor", icon: Code2 },
];
