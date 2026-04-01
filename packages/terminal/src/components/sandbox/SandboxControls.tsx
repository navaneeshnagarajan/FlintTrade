/**
 * SandboxControls — paper trading management panel.
 *
 * Features:
 *   - Current virtual capital display (₹ formatted in Indian locale)
 *   - Adjust capital (+ / - amount) via react-hook-form
 *   - Reset all sandbox data (with AlertDialog confirmation)
 *   - Export data as JSON download
 *   - Import data from .json file upload
 *
 * Used in: Settings → Sandbox section, and TopBar dropdown.
 * All API calls go to /ft-api/v1/sandbox/* endpoints.
 */

import { useState, useRef } from "react";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Download, Upload, RotateCcw, IndianRupee, TrendingUp, TrendingDown } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

// ---------------------------------------------------------------------------
// API types
// ---------------------------------------------------------------------------

interface SandboxStatus {
  capital: number;
  initial_capital: number;
  pnl: number;
  trades_count: number;
}

interface ExportData {
  capital: number;
  trades: unknown[];
  positions: unknown[];
  exported_at: string;
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

const BASE = "/ft-api/v1/sandbox";

async function fetchSandboxStatus(): Promise<SandboxStatus> {
  const resp = await fetch(`${BASE}/status`);
  if (!resp.ok) throw new Error("Failed to fetch sandbox status.");
  const json = await resp.json() as { data: SandboxStatus };
  return json.data;
}

async function adjustCapital(delta: number): Promise<SandboxStatus> {
  const resp = await fetch(`${BASE}/capital`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ delta }),
  });
  if (!resp.ok) throw new Error("Failed to adjust capital.");
  const json = await resp.json() as { data: SandboxStatus };
  return json.data;
}

async function resetSandbox(): Promise<void> {
  const resp = await fetch(`${BASE}/reset`, { method: "POST" });
  if (!resp.ok) throw new Error("Failed to reset sandbox data.");
}

async function exportSandboxData(): Promise<ExportData> {
  const resp = await fetch(`${BASE}/export`);
  if (!resp.ok) throw new Error("Failed to export sandbox data.");
  return resp.json() as Promise<ExportData>;
}

async function importSandboxData(file: File): Promise<void> {
  const text = await file.text();
  const resp = await fetch(`${BASE}/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: text,
  });
  if (!resp.ok) throw new Error("Failed to import sandbox data.");
}

// ---------------------------------------------------------------------------
// Form schema
// ---------------------------------------------------------------------------

type AdjustDirection = "add" | "subtract";

const adjustSchema = z.object({
  amount: z
    .string()
    .min(1, "Enter an amount.")
    .refine((v) => !isNaN(Number(v)) && Number(v) > 0, "Must be a positive number."),
  direction: z.enum(["add", "subtract"]),
});

type AdjustForm = z.infer<typeof adjustSchema>;

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function formatInr(value: number): string {
  return value.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function SandboxControls() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [importError, setImportError] = useState("");
  const [importSuccess, setImportSuccess] = useState(false);

  // Status query
  const { data: status, isLoading } = useQuery({
    queryKey: ["sandboxStatus"],
    queryFn: fetchSandboxStatus,
    retry: 1,
  });

  // Capital adjustment mutation
  const adjustMutation = useMutation({
    mutationFn: (delta: number) => adjustCapital(delta),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["sandboxStatus"] });
      reset();
    },
  });

  // Reset mutation
  const resetMutation = useMutation({
    mutationFn: resetSandbox,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["sandboxStatus"] });
    },
  });

  // Export mutation
  const exportMutation = useMutation({
    mutationFn: exportSandboxData,
    onSuccess: (data) => {
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `flinttrade-sandbox-${new Date().toISOString().slice(0, 10)}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
    },
  });

  // Import mutation
  const importMutation = useMutation({
    mutationFn: (file: File) => importSandboxData(file),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["sandboxStatus"] });
      setImportError("");
      setImportSuccess(true);
      setTimeout(() => setImportSuccess(false), 3000);
    },
    onError: (err: Error) => {
      setImportError(err.message);
    },
  });

  // Capital adjustment form
  const {
    register,
    handleSubmit,
    reset,
    control,
    formState: { errors },
  } = useForm<AdjustForm>({
    resolver: zodResolver(adjustSchema),
    defaultValues: { direction: "add" },
  });

  const onAdjustSubmit = (values: AdjustForm) => {
    const amount = Number(values.amount);
    const delta = values.direction === "add" ? amount : -amount;
    adjustMutation.mutate(delta);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImportError("");
    importMutation.mutate(file);
    e.target.value = "";
  };

  const pnl = status?.pnl ?? 0;
  const pnlPositive = pnl >= 0;

  return (
    <div className="space-y-5">
      {/* Capital display */}
      <div className="p-4 rounded-xl border border-amber-500/20 bg-amber-500/5 space-y-2">
        <div className="flex items-center gap-2 text-xs text-text-muted font-medium uppercase tracking-wide">
          <IndianRupee size={12} aria-hidden="true" />
          Virtual Capital
        </div>

        {isLoading ? (
          <div className="h-8 w-40 rounded bg-surface-hover animate-pulse" aria-label="Loading capital..." />
        ) : (
          <div className="space-y-0.5">
            <p className="font-mono font-bold text-2xl text-text-primary">
              ₹{formatInr(status?.capital ?? 0)}
            </p>
            <div className="flex items-center gap-2 text-xs">
              <span className="text-text-muted">
                Initial: ₹{formatInr(status?.initial_capital ?? 0)}
              </span>
              <span className="text-border-default" aria-hidden="true">·</span>
              <span
                className={`flex items-center gap-0.5 font-medium ${pnlPositive ? "text-profit" : "text-loss"}`}
                aria-label={`P&L: ${pnlPositive ? "+" : ""}₹${formatInr(pnl)}`}
              >
                {pnlPositive
                  ? <TrendingUp size={11} aria-hidden="true" />
                  : <TrendingDown size={11} aria-hidden="true" />
                }
                {pnlPositive ? "+" : ""}₹{formatInr(pnl)} P&amp;L
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Adjust capital form */}
      <form onSubmit={handleSubmit(onAdjustSubmit)} className="space-y-3" aria-label="Adjust virtual capital">
        <p className="text-xs font-medium text-text-secondary">Adjust Capital</p>

        <div className="flex items-center gap-2">
          {/* Direction toggle via Controller */}
          <Controller
            control={control}
            name="direction"
            render={({ field }) => (
              <div
                className="flex rounded-md border border-border-default overflow-hidden shrink-0"
                role="group"
                aria-label="Adjustment direction"
              >
                <button
                  type="button"
                  aria-pressed={field.value === "add"}
                  onClick={() => field.onChange("add" satisfies AdjustDirection)}
                  className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                    field.value === "add"
                      ? "bg-profit/15 text-profit"
                      : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
                  }`}
                >
                  + Add
                </button>
                <button
                  type="button"
                  aria-pressed={field.value === "subtract"}
                  onClick={() => field.onChange("subtract" satisfies AdjustDirection)}
                  className={`px-3 py-1.5 text-xs font-medium transition-colors border-l border-border-default ${
                    field.value === "subtract"
                      ? "bg-loss/15 text-loss"
                      : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
                  }`}
                >
                  − Subtract
                </button>
              </div>
            )}
          />

          {/* Amount input */}
          <Input
            {...register("amount")}
            type="text"
            inputMode="numeric"
            placeholder="Amount (₹)"
            aria-label="Capital adjustment amount in rupees"
            className="flex-1 font-mono"
          />

          <Button
            type="submit"
            variant="outline"
            size="sm"
            disabled={adjustMutation.isPending}
            className="shrink-0"
          >
            {adjustMutation.isPending ? "Updating..." : "Adjust"}
          </Button>
        </div>

        {errors.amount && (
          <p className="text-xs text-loss" role="alert">{errors.amount.message}</p>
        )}
        {adjustMutation.isError && (
          <p className="text-xs text-loss" role="alert">{(adjustMutation.error as Error).message}</p>
        )}
      </form>

      {/* Divider */}
      <div className="border-t border-border-default" />

      {/* Data management */}
      <div className="space-y-2">
        <p className="text-xs font-medium text-text-secondary">Data Management</p>

        <div className="flex flex-wrap gap-2">
          {/* Export */}
          <Button
            variant="outline"
            size="sm"
            onClick={() => exportMutation.mutate()}
            disabled={exportMutation.isPending}
            className="text-xs"
          >
            <Download size={13} className="mr-1.5" aria-hidden="true" />
            {exportMutation.isPending ? "Exporting..." : "Export Data"}
          </Button>

          {/* Import */}
          <Button
            variant="outline"
            size="sm"
            onClick={() => fileInputRef.current?.click()}
            disabled={importMutation.isPending}
            className="text-xs"
          >
            <Upload size={13} className="mr-1.5" aria-hidden="true" />
            {importMutation.isPending ? "Importing..." : "Import Data"}
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".json"
            onChange={handleFileChange}
            className="sr-only"
            aria-label="Import sandbox data from JSON file"
          />

          {/* Reset — with AlertDialog confirmation */}
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button
                variant="outline"
                size="sm"
                disabled={resetMutation.isPending}
                className="text-xs text-loss border-loss/30 hover:bg-loss/10 hover:text-loss"
              >
                <RotateCcw size={13} className="mr-1.5" aria-hidden="true" />
                {resetMutation.isPending ? "Resetting..." : "Reset All Data"}
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Reset all sandbox data?</AlertDialogTitle>
                <AlertDialogDescription>
                  This will permanently delete all sandbox trades, positions, and orders,
                  and restore your virtual capital to its initial amount.
                  This cannot be undone. Consider exporting your data first.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction
                  onClick={() => resetMutation.mutate()}
                  className="bg-loss hover:bg-loss/90 text-white"
                >
                  Reset Everything
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>

        {/* Feedback messages */}
        {importError && (
          <p className="text-xs text-loss mt-1" role="alert">{importError}</p>
        )}
        {importSuccess && (
          <p className="text-xs text-profit mt-1" role="status">Data imported successfully.</p>
        )}
        {resetMutation.isSuccess && (
          <p className="text-xs text-profit mt-1" role="status">Sandbox data has been reset.</p>
        )}
        {exportMutation.isError && (
          <p className="text-xs text-loss mt-1" role="alert">{(exportMutation.error as Error).message}</p>
        )}
      </div>
    </div>
  );
}
