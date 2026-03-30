/**
 * GoalTab.tsx — Goal-based investment tracker
 *
 * Users define financial goals (retirement, home, education, etc.) with a
 * target amount and date. The calculator projects future value using compound
 * interest and shows shortfall/surplus against the target.
 *
 * All calculations are client-side. Goals persist in localStorage.
 */

import { useState, useMemo, useCallback } from "react";
import { useForm, type Resolver } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  Plus,
  Target,
  Trash2,
  Pencil,
  GraduationCap,
  Home,
  Plane,
  PiggyBank,
  ShieldCheck,
} from "lucide-react";
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
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";
import { formatINRCompact } from "../formatters";

// ---------------------------------------------------------------------------
// Types & schema
// ---------------------------------------------------------------------------

const GOAL_ICONS = {
  retirement: PiggyBank,
  home: Home,
  education: GraduationCap,
  vacation: Plane,
  emergency: ShieldCheck,
  custom: Target,
} as const;

type GoalCategory = keyof typeof GOAL_ICONS;

const GOAL_CATEGORIES: { value: GoalCategory; label: string }[] = [
  { value: "retirement", label: "Retirement" },
  { value: "home", label: "Home" },
  { value: "education", label: "Education" },
  { value: "vacation", label: "Vacation" },
  { value: "emergency", label: "Emergency Fund" },
  { value: "custom", label: "Custom" },
];

export interface InvestmentGoal {
  id: string;
  name: string;
  category: GoalCategory;
  targetAmount: number;
  currentSavings: number;
  monthlySip: number;
  expectedReturnPct: number;
  targetDate: string; // ISO date string (YYYY-MM-DD)
  createdAt: string;
}

const goalSchema = z.object({
  name: z.string().min(1, "Goal name is required").max(50),
  category: z.enum(["retirement", "home", "education", "vacation", "emergency", "custom"]),
  targetAmount: z.coerce
    .number()
    .positive("Target must be positive")
    .max(100_00_00_000, "Maximum 100 crore"),
  currentSavings: z.coerce
    .number()
    .min(0, "Cannot be negative")
    .default(0),
  monthlySip: z.coerce
    .number()
    .min(0, "Cannot be negative")
    .max(1_00_00_000, "Maximum 1 crore/month"),
  expectedReturnPct: z.coerce
    .number()
    .min(0, "Cannot be negative")
    .max(50, "Maximum 50%")
    .default(12),
  targetDate: z.string().min(1, "Target date is required"),
});

type GoalFormValues = z.infer<typeof goalSchema>;

// ---------------------------------------------------------------------------
// Calculation helpers (exported for testing)
// ---------------------------------------------------------------------------

/**
 * Compute future value of a lump sum + recurring SIP using compound interest.
 * Monthly compounding: FV = P*(1+r)^n + SIP * [((1+r)^n - 1) / r]
 * where r = annual rate / 12, n = total months.
 */
export function computeProjectedValue(
  currentSavings: number,
  monthlySip: number,
  annualReturnPct: number,
  monthsRemaining: number,
): number {
  if (monthsRemaining <= 0) return currentSavings;
  if (annualReturnPct === 0) {
    return currentSavings + monthlySip * monthsRemaining;
  }
  const r = annualReturnPct / 100 / 12;
  const n = monthsRemaining;
  const lumpFV = currentSavings * Math.pow(1 + r, n);
  const sipFV = monthlySip * ((Math.pow(1 + r, n) - 1) / r);
  return lumpFV + sipFV;
}

/**
 * Compute the monthly SIP required to reach a target from current savings.
 * SIP = (target - P*(1+r)^n) * r / ((1+r)^n - 1)
 */
export function computeRequiredSip(
  targetAmount: number,
  currentSavings: number,
  annualReturnPct: number,
  monthsRemaining: number,
): number {
  if (monthsRemaining <= 0) return 0;
  if (annualReturnPct === 0) {
    const remaining = targetAmount - currentSavings;
    return remaining > 0 ? remaining / monthsRemaining : 0;
  }
  const r = annualReturnPct / 100 / 12;
  const n = monthsRemaining;
  const lumpFV = currentSavings * Math.pow(1 + r, n);
  const remaining = targetAmount - lumpFV;
  if (remaining <= 0) return 0;
  return remaining * r / (Math.pow(1 + r, n) - 1);
}

/** Months remaining from now to a target date. */
export function monthsUntil(targetDate: string): number {
  const target = new Date(targetDate);
  const now = new Date();
  const months =
    (target.getFullYear() - now.getFullYear()) * 12 +
    (target.getMonth() - now.getMonth());
  return Math.max(0, months);
}

// ---------------------------------------------------------------------------
// Persistence
// ---------------------------------------------------------------------------

const STORAGE_KEY = "flinttrade:investment-goals";

function loadGoals(): InvestmentGoal[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as InvestmentGoal[];
  } catch {
    return [];
  }
}

function saveGoals(goals: InvestmentGoal[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(goals));
  } catch {
    // Silently ignore — localStorage may be unavailable
  }
}

// ---------------------------------------------------------------------------
// GoalCard
// ---------------------------------------------------------------------------

interface GoalCardProps {
  goal: InvestmentGoal;
  onEdit: (goal: InvestmentGoal) => void;
  onDelete: (id: string) => void;
}

function GoalCard({ goal, onEdit, onDelete }: GoalCardProps) {
  const months = monthsUntil(goal.targetDate);
  const projected = computeProjectedValue(
    goal.currentSavings,
    goal.monthlySip,
    goal.expectedReturnPct,
    months,
  );
  const requiredSip = computeRequiredSip(
    goal.targetAmount,
    goal.currentSavings,
    goal.expectedReturnPct,
    months,
  );
  const progressPct = Math.min(100, (goal.currentSavings / goal.targetAmount) * 100);
  const projectedPct = Math.min(100, (projected / goal.targetAmount) * 100);
  const surplus = projected - goal.targetAmount;
  const onTrack = surplus >= 0;

  const Icon = GOAL_ICONS[goal.category];

  const targetDateFormatted = new Date(goal.targetDate).toLocaleDateString("en-IN", {
    month: "short",
    year: "numeric",
  });

  const yearsLeft = months / 12;

  return (
    <GlassCard className="p-5 gap-3 relative group">
      {/* Actions */}
      <div className="absolute top-3 right-3 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <Button
          variant="ghost"
          size="sm"
          className="h-6 w-6 p-0"
          onClick={() => onEdit(goal)}
          aria-label={`Edit ${goal.name}`}
        >
          <Pencil className="size-3" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 w-6 p-0 text-loss hover:text-loss"
          onClick={() => onDelete(goal.id)}
          aria-label={`Delete ${goal.name}`}
        >
          <Trash2 className="size-3" />
        </Button>
      </div>

      {/* Header */}
      <div className="flex items-center gap-2.5">
        <div
          className={cn(
            "size-8 rounded-lg flex items-center justify-center shrink-0",
            onTrack ? "bg-bullish-bg" : "bg-bearish-bg",
          )}
        >
          <Icon className={cn("size-4", onTrack ? "text-profit" : "text-loss")} />
        </div>
        <div className="min-w-0">
          <h3 className="font-heading font-semibold text-sm text-text-primary truncate">
            {goal.name}
          </h3>
          <p className="text-xxs text-text-muted">
            {targetDateFormatted} &middot; {yearsLeft.toFixed(1)} yrs left
          </p>
        </div>
      </div>

      {/* Target & progress */}
      <div className="space-y-2">
        <div className="flex items-baseline justify-between">
          <span className="text-xxs text-text-muted uppercase tracking-wider">Target</span>
          <span className="font-mono text-sm font-bold tabular-nums text-text-primary">
            {formatINRCompact(goal.targetAmount)}
          </span>
        </div>

        {/* Progress bar */}
        <div className="relative h-2 rounded-full bg-surface-hover overflow-hidden">
          {/* Projected fill (lighter) */}
          <div
            className={cn(
              "absolute inset-y-0 left-0 rounded-full transition-all duration-500",
              onTrack ? "bg-profit/20" : "bg-loss/20",
            )}
            style={{ width: `${projectedPct}%` }}
          />
          {/* Current savings fill (solid) */}
          <div
            className={cn(
              "absolute inset-y-0 left-0 rounded-full transition-all duration-500",
              onTrack ? "bg-profit" : "bg-amber-500",
            )}
            style={{ width: `${progressPct}%` }}
          />
        </div>

        <div className="flex items-center justify-between text-xxs">
          <span className="text-text-muted">
            {formatINRCompact(goal.currentSavings)} saved ({progressPct.toFixed(0)}%)
          </span>
          <span className={cn("font-mono tabular-nums", onTrack ? "text-profit" : "text-loss")}>
            Projected: {formatINRCompact(projected)}
          </span>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-3 pt-2 border-t border-border-default">
        <div>
          <p className="text-xxs text-text-muted">Monthly SIP</p>
          <p className="font-mono text-xs font-semibold tabular-nums text-text-primary">
            {formatINRCompact(goal.monthlySip)}
          </p>
        </div>
        <div>
          <p className="text-xxs text-text-muted">Required SIP</p>
          <p
            className={cn(
              "font-mono text-xs font-semibold tabular-nums",
              requiredSip <= goal.monthlySip ? "text-profit" : "text-loss",
            )}
          >
            {formatINRCompact(requiredSip)}
          </p>
        </div>
        <div>
          <p className="text-xxs text-text-muted">Expected Return</p>
          <p className="font-mono text-xs font-semibold tabular-nums text-text-primary">
            {goal.expectedReturnPct}% p.a.
          </p>
        </div>
        <div>
          <p className="text-xxs text-text-muted">
            {onTrack ? "Surplus" : "Shortfall"}
          </p>
          <p
            className={cn(
              "font-mono text-xs font-semibold tabular-nums",
              onTrack ? "text-profit" : "text-loss",
            )}
          >
            {onTrack ? "+" : "-"}{formatINRCompact(Math.abs(surplus))}
          </p>
        </div>
      </div>
    </GlassCard>
  );
}

// ---------------------------------------------------------------------------
// GoalForm dialog
// ---------------------------------------------------------------------------

interface GoalFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (goal: InvestmentGoal) => void;
  editingGoal: InvestmentGoal | null;
}

function GoalFormDialog({ open, onOpenChange, onSave, editingGoal }: GoalFormDialogProps) {
  const {
    register,
    handleSubmit,
    setValue,
    watch,
    reset,
    formState: { errors },
  } = useForm<GoalFormValues>({
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- zod v4 + react-hook-form type mismatch
    // zodResolver v5 + zod v4 inferred type mismatch (coerce vs number): cast required
    resolver: zodResolver(goalSchema) as unknown as Resolver<GoalFormValues>,
    defaultValues: editingGoal
      ? {
          name: editingGoal.name,
          category: editingGoal.category,
          targetAmount: editingGoal.targetAmount,
          currentSavings: editingGoal.currentSavings,
          monthlySip: editingGoal.monthlySip,
          expectedReturnPct: editingGoal.expectedReturnPct,
          targetDate: editingGoal.targetDate,
        }
      : {
          name: "",
          category: "custom",
          targetAmount: 0,
          currentSavings: 0,
          monthlySip: 0,
          expectedReturnPct: 12,
          targetDate: "",
        },
  });

  const category = watch("category");

  const onSubmit = (data: GoalFormValues) => {
    const goal: InvestmentGoal = {
      id: editingGoal?.id ?? crypto.randomUUID(),
      name: data.name,
      category: data.category,
      targetAmount: data.targetAmount,
      currentSavings: data.currentSavings,
      monthlySip: data.monthlySip,
      expectedReturnPct: data.expectedReturnPct,
      targetDate: data.targetDate,
      createdAt: editingGoal?.createdAt ?? new Date().toISOString(),
    };
    onSave(goal);
    reset();
    onOpenChange(false);
  };

  // Min date: 1 month from now
  const minDate = useMemo(() => {
    const d = new Date();
    d.setMonth(d.getMonth() + 1);
    return d.toISOString().split("T")[0];
  }, []);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {editingGoal ? "Edit Goal" : "Add Investment Goal"}
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit(onSubmit as (data: Record<string, unknown>) => void)} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="goal-name">Goal Name</Label>
            <Input
              id="goal-name"
              placeholder="e.g., Dream Home"
              {...register("name")}
            />
            {errors.name && (
              <p className="text-xs text-loss">{errors.name.message}</p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="goal-category">Category</Label>
            <Select
              value={category}
              onValueChange={(v) => setValue("category", v as GoalCategory)}
            >
              <SelectTrigger id="goal-category">
                <SelectValue placeholder="Select category" />
              </SelectTrigger>
              <SelectContent>
                {GOAL_CATEGORIES.map((c) => (
                  <SelectItem key={c.value} value={c.value}>
                    {c.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="goal-target">Target Amount</Label>
              <Input
                id="goal-target"
                type="number"
                placeholder="50,00,000"
                {...register("targetAmount")}
              />
              {errors.targetAmount && (
                <p className="text-xs text-loss">{errors.targetAmount.message}</p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="goal-current">Current Savings</Label>
              <Input
                id="goal-current"
                type="number"
                placeholder="5,00,000"
                {...register("currentSavings")}
              />
              {errors.currentSavings && (
                <p className="text-xs text-loss">{errors.currentSavings.message}</p>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="goal-sip">Monthly SIP</Label>
              <Input
                id="goal-sip"
                type="number"
                placeholder="25,000"
                {...register("monthlySip")}
              />
              {errors.monthlySip && (
                <p className="text-xs text-loss">{errors.monthlySip.message}</p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="goal-return">Expected Return (% p.a.)</Label>
              <Input
                id="goal-return"
                type="number"
                step="0.5"
                placeholder="12"
                {...register("expectedReturnPct")}
              />
              {errors.expectedReturnPct && (
                <p className="text-xs text-loss">{errors.expectedReturnPct.message}</p>
              )}
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="goal-date">Target Date</Label>
            <Input
              id="goal-date"
              type="date"
              min={minDate}
              {...register("targetDate")}
            />
            {errors.targetDate && (
              <p className="text-xs text-loss">{errors.targetDate.message}</p>
            )}
          </div>

          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit">
              {editingGoal ? "Update Goal" : "Add Goal"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// GoalTab (main export)
// ---------------------------------------------------------------------------

export function GoalTab() {
  const [goals, setGoals] = useState<InvestmentGoal[]>(loadGoals);
  const [formOpen, setFormOpen] = useState(false);
  const [editingGoal, setEditingGoal] = useState<InvestmentGoal | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const persistGoals = useCallback((next: InvestmentGoal[]) => {
    setGoals(next);
    saveGoals(next);
  }, []);

  const handleSave = useCallback(
    (goal: InvestmentGoal) => {
      const existing = goals.findIndex((g) => g.id === goal.id);
      if (existing >= 0) {
        const updated = [...goals];
        updated[existing] = goal;
        persistGoals(updated);
      } else {
        persistGoals([...goals, goal]);
      }
      setEditingGoal(null);
    },
    [goals, persistGoals],
  );

  const handleEdit = useCallback((goal: InvestmentGoal) => {
    setEditingGoal(goal);
    setFormOpen(true);
  }, []);

  const handleDelete = useCallback(
    (id: string) => {
      persistGoals(goals.filter((g) => g.id !== id));
      setDeletingId(null);
    },
    [goals, persistGoals],
  );

  const handleAddNew = useCallback(() => {
    setEditingGoal(null);
    setFormOpen(true);
  }, []);

  // Summary stats
  const totalTarget = useMemo(
    () => goals.reduce((acc, g) => acc + g.targetAmount, 0),
    [goals],
  );
  const totalSaved = useMemo(
    () => goals.reduce((acc, g) => acc + g.currentSavings, 0),
    [goals],
  );
  const totalMonthlySip = useMemo(
    () => goals.reduce((acc, g) => acc + g.monthlySip, 0),
    [goals],
  );
  const overallProgress = totalTarget > 0 ? (totalSaved / totalTarget) * 100 : 0;

  return (
    <div className="space-y-6">
      {/* Summary row */}
      {goals.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
          <GlassCard className="p-4 gap-1">
            <p className="text-xxs text-text-muted uppercase tracking-wider">Total Goals</p>
            <p className="text-2xl font-mono font-bold tabular-nums text-text-primary">
              {goals.length}
            </p>
          </GlassCard>
          <GlassCard className="p-4 gap-1">
            <p className="text-xxs text-text-muted uppercase tracking-wider">Total Target</p>
            <p className="text-2xl font-mono font-bold tabular-nums text-text-primary">
              {formatINRCompact(totalTarget)}
            </p>
          </GlassCard>
          <GlassCard className="p-4 gap-1">
            <p className="text-xxs text-text-muted uppercase tracking-wider">Total Saved</p>
            <p className="text-2xl font-mono font-bold tabular-nums text-text-primary">
              {formatINRCompact(totalSaved)}
              <span className="text-xs text-text-muted ml-1">
                ({overallProgress.toFixed(0)}%)
              </span>
            </p>
          </GlassCard>
          <GlassCard className="p-4 gap-1">
            <p className="text-xxs text-text-muted uppercase tracking-wider">Monthly SIPs</p>
            <p className="text-2xl font-mono font-bold tabular-nums text-text-primary">
              {formatINRCompact(totalMonthlySip)}
            </p>
          </GlassCard>
        </div>
      )}

      {/* Goal cards grid */}
      {goals.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {goals.map((goal) => (
            <GoalCard
              key={goal.id}
              goal={goal}
              onEdit={handleEdit}
              onDelete={(id) => setDeletingId(id)}
            />
          ))}

          {/* Add goal card */}
          <button
            onClick={handleAddNew}
            className="flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed border-border-default p-8 text-text-muted hover:text-text-primary hover:border-accent/50 hover:bg-surface-hover/50 transition-colors min-h-[200px]"
            aria-label="Add new investment goal"
          >
            <Plus className="size-8" />
            <span className="text-sm font-medium">Add Goal</span>
          </button>
        </div>
      ) : (
        /* Empty state */
        <GlassCard className="p-12 gap-4 items-center text-center">
          <div className="size-16 rounded-2xl bg-accent/10 flex items-center justify-center">
            <Target className="size-8 text-accent" />
          </div>
          <div className="space-y-1.5">
            <h3 className="font-heading font-bold text-lg text-text-primary">
              Set your first financial goal
            </h3>
            <p className="text-sm text-text-secondary max-w-md mx-auto">
              Define goals like retirement, buying a home, or your child&apos;s education.
              Track progress and see if your SIP strategy is on track.
            </p>
          </div>
          <Button onClick={handleAddNew} className="mt-2">
            <Plus className="size-4 mr-1.5" />
            Add Your First Goal
          </Button>
        </GlassCard>
      )}

      {/* Delete confirmation dialog */}
      <Dialog open={!!deletingId} onOpenChange={(open) => !open && setDeletingId(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Delete goal?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-text-secondary">
            This will permanently remove this goal and its history.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeletingId(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => deletingId && handleDelete(deletingId)}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Add/Edit form dialog */}
      <GoalFormDialog
        key={editingGoal?.id ?? "new"}
        open={formOpen}
        onOpenChange={setFormOpen}
        onSave={handleSave}
        editingGoal={editingGoal}
      />

      {/* Footer note */}
      {goals.length > 0 && (
        <p className="text-xs text-text-muted">
          Projections use monthly compounding at the specified return rate.
          Actual returns may vary based on market conditions.
        </p>
      )}
    </div>
  );
}
