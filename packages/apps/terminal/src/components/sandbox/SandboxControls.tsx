/**
 * SandboxControls — practice mode management panel.
 *
 * Features:
 *   - Current virtual capital display (₹ formatted in Indian locale)
 *   - Persisted leverage and square-off policy
 *   - Adjust capital (+ / - amount) via react-hook-form
 *   - Reset all sandbox data (with AlertDialog confirmation)
 *   - Export data as JSON download
 *   - Import data from .json file upload
 *
 * Used in: Settings → Sandbox section, and TopBar dropdown.
 * All API calls go to /ft-api/v1/sandbox/* endpoints.
 */

import { useState, useRef, useEffect } from "react";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Download, Upload, RotateCcw, IndianRupee, TrendingUp, TrendingDown } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { SandboxStatusSchema } from "@/lib/schemas/ftApi";
import { buildHeaders } from "@/services/ftApi.helpers";
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

const sandboxConfigSchema = z.object({
  starting_capital: z.number().finite().positive(),
  equity_leverage: z.number().int().positive(),
  futures_leverage: z.number().int().positive(),
  option_buy_leverage: z.number().int().positive(),
  option_sell_leverage: z.number().int().positive(),
  squareoff_time: z.string().regex(/^(?:[01]\d|2[0-3]):[0-5]\d$/),
  mcx_squareoff_time: z.string().regex(/^(?:[01]\d|2[0-3]):[0-5]\d$/),
});

type SandboxConfig = z.infer<typeof sandboxConfigSchema>;

const DEFAULT_SANDBOX_CONFIG: SandboxConfig = {
  starting_capital: 1_000_000,
  equity_leverage: 1,
  futures_leverage: 1,
  option_buy_leverage: 1,
  option_sell_leverage: 1,
  squareoff_time: "15:15",
  mcx_squareoff_time: "23:25",
};

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
  const resp = await fetch(`${BASE}/status`, { headers: buildHeaders(false) });
  if (!resp.ok) throw new Error("Failed to fetch sandbox status.");
  const raw: unknown = await resp.json();
  const result = SandboxStatusSchema.safeParse(raw);
  if (!result.success) {
    console.error("[SandboxControls] /sandbox/status shape mismatch:", result.error.issues);
    // Return safe fallback so UI does not crash
    return { capital: 0, initial_capital: 0, pnl: 0, trades_count: 0 };
  }
  return result.data.data as SandboxStatus;
}

async function fetchSandboxConfig(): Promise<SandboxConfig> {
  const resp = await fetch(`${BASE}/config`, { headers: buildHeaders(false) });
  if (!resp.ok) throw new Error("Failed to fetch Practice policy.");
  const raw = await resp.json() as { data?: { config?: unknown } };
  return sandboxConfigSchema.parse(raw.data?.config);
}

async function updateSandboxConfig(config: SandboxConfig): Promise<SandboxConfig> {
  const resp = await fetch(`${BASE}/config`, {
    method: "POST",
    headers: buildHeaders(true),
    body: JSON.stringify(config),
  });
  if (!resp.ok) throw new Error("Failed to save Practice policy.");
  const raw = await resp.json() as { data?: { config?: unknown } };
  return sandboxConfigSchema.parse(raw.data?.config);
}

async function adjustCapital(delta: number): Promise<SandboxStatus> {
  // Backend route is POST /capital/adjust {amount} (not /capital {delta}); it
  // returns the capital object, so refetch the combined status afterwards.
  const resp = await fetch(`${BASE}/capital/adjust`, {
    method: "POST",
    headers: buildHeaders(true),
    body: JSON.stringify({ amount: delta }),
  });
  if (!resp.ok) throw new Error("Failed to adjust capital.");
  return fetchSandboxStatus();
}

async function resetSandbox(): Promise<void> {
  const resp = await fetch(`${BASE}/reset`, {
    method: "POST",
    headers: buildHeaders(false),
  });
  if (!resp.ok) throw new Error("Failed to reset sandbox data.");
}

async function exportSandboxData(): Promise<ExportData> {
  const resp = await fetch(`${BASE}/export`, { headers: buildHeaders(false) });
  if (!resp.ok) throw new Error("Failed to export sandbox data.");
  // Backend returns { status, data: "<json string>" } — parse the inner payload.
  const json = await resp.json() as { data: string };
  return JSON.parse(json.data) as ExportData;
}

async function importSandboxData(file: File): Promise<void> {
  const text = await file.text();
  const resp = await fetch(`${BASE}/import`, {
    method: "POST",
    headers: buildHeaders(true),
    // Backend expects { data: "<json string from /export>" }, not raw text.
    body: JSON.stringify({ data: text }),
  });
  if (!resp.ok) throw new Error("Failed to import sandbox data.");
}

interface PlacedOrder {
  order_id: string;
  status: string; // "PENDING" | "COMPLETE" | "REJECTED"
  message: string;
}

interface PlaceOrderInput {
  symbol: string;
  exchange: string;
  action: "BUY" | "SELL";
  quantity: number;
  price: number;
}

async function placeSandboxOrder(input: PlaceOrderInput): Promise<PlacedOrder> {
  const resp = await fetch(`${BASE}/order`, {
    method: "POST",
    headers: buildHeaders(true),
    body: JSON.stringify({ ...input, product: "MIS" }),
  });
  const json = (await resp.json().catch(() => null)) as
    | { message?: string; data?: { order?: PlacedOrder } }
    | null;
  // A REJECTED order (e.g. insufficient capital) is a valid business outcome the
  // backend returns with HTTP 400 but a populated data.order — surface it rather
  // than throwing a generic error. Only a malformed request lacks data.order.
  if (json?.data?.order) return json.data.order;
  throw new Error(json?.message ?? "Failed to place paper order.");
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

const orderSchema = z.object({
  symbol: z.string().min(1, "Symbol is required."),
  exchange: z.string().min(1, "Exchange is required."),
  action: z.enum(["BUY", "SELL"]),
  quantity: z
    .string()
    .refine((v) => Number.isInteger(Number(v)) && Number(v) > 0, "Quantity must be a positive whole number."),
  price: z
    .string()
    .refine((v) => !isNaN(Number(v)) && Number(v) > 0, "Price must be a positive number."),
});

type OrderForm = z.infer<typeof orderSchema>;

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
  const importSuccessTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [importError, setImportError] = useState("");
  const [importSuccess, setImportSuccess] = useState(false);
  const [orderResult, setOrderResult] = useState<PlacedOrder | null>(null);

  useEffect(() => {
    return () => {
      if (importSuccessTimerRef.current !== null) {
        clearTimeout(importSuccessTimerRef.current);
      }
    };
  }, []);

  // Status query
  const { data: status, isLoading } = useQuery({
    queryKey: ["sandboxStatus"],
    queryFn: fetchSandboxStatus,
    retry: 1,
  });

  const { data: sandboxConfig, isLoading: configLoading } = useQuery({
    queryKey: ["sandboxConfig"],
    queryFn: fetchSandboxConfig,
    retry: 1,
  });

  const configForm = useForm<SandboxConfig>({
    resolver: zodResolver(sandboxConfigSchema),
    defaultValues: DEFAULT_SANDBOX_CONFIG,
  });

  useEffect(() => {
    if (sandboxConfig) configForm.reset(sandboxConfig);
  }, [configForm, sandboxConfig]);

  const configMutation = useMutation({
    mutationFn: updateSandboxConfig,
    onSuccess: (updated) => {
      configForm.reset(updated);
      queryClient.setQueryData(["sandboxConfig"], updated);
    },
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
      importSuccessTimerRef.current = setTimeout(() => setImportSuccess(false), 3000);
    },
    onError: (err: Error) => {
      setImportError(err.message);
    },
  });

  // Place-order mutation. A REJECTED order resolves (not throws) so we can show
  // the reason; only transport/validation failures hit onError.
  const orderMutation = useMutation({
    mutationFn: placeSandboxOrder,
    onSuccess: (order) => {
      setOrderResult(order);
      void queryClient.invalidateQueries({ queryKey: ["sandboxStatus"] });
      if (order.status === "COMPLETE") {
        orderForm.reset({ action: "BUY", exchange: "NSE", symbol: "", quantity: "", price: "" });
      }
    },
    onError: () => setOrderResult(null),
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

  // Paper-order form (separate react-hook-form instance).
  const orderForm = useForm<OrderForm>({
    resolver: zodResolver(orderSchema),
    defaultValues: { action: "BUY", exchange: "NSE", symbol: "", quantity: "", price: "" },
  });

  const onPlaceOrder = (values: OrderForm) => {
    orderMutation.mutate({
      symbol: values.symbol.trim().toUpperCase(),
      exchange: values.exchange.trim().toUpperCase(),
      action: values.action,
      quantity: Number(values.quantity),
      price: Number(values.price),
    });
  };

  const onAdjustSubmit = (values: AdjustForm) => {
    const amount = Number(values.amount);
    const delta = values.direction === "add" ? amount : -amount;
    adjustMutation.mutate(delta);
  };

  const onConfigSubmit = (values: SandboxConfig) => {
    configMutation.mutate(values);
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

      <form
        onSubmit={configForm.handleSubmit(onConfigSubmit)}
        className="space-y-3"
        aria-label="Practice policy"
      >
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs font-medium text-text-secondary">Practice Policy</p>
          <Button
            type="submit"
            variant="outline"
            size="sm"
            disabled={configLoading || configMutation.isPending}
          >
            {configMutation.isPending ? "Saving..." : "Save Policy"}
          </Button>
        </div>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <label className="space-y-1 text-xs text-text-muted sm:col-span-2">
            <span>Starting capital</span>
            <Input
              {...configForm.register("starting_capital", { valueAsNumber: true })}
              type="number"
              min="1"
              step="0.01"
              aria-label="Starting capital"
              className="font-mono"
            />
          </label>
          <label className="space-y-1 text-xs text-text-muted">
            <span>Equity leverage</span>
            <Input
              {...configForm.register("equity_leverage", { valueAsNumber: true })}
              type="number"
              min="1"
              step="1"
              aria-label="Equity leverage"
              className="font-mono"
            />
          </label>
          <label className="space-y-1 text-xs text-text-muted">
            <span>Futures leverage</span>
            <Input
              {...configForm.register("futures_leverage", { valueAsNumber: true })}
              type="number"
              min="1"
              step="1"
              aria-label="Futures leverage"
              className="font-mono"
            />
          </label>
          <label className="space-y-1 text-xs text-text-muted">
            <span>Option buy leverage</span>
            <Input
              {...configForm.register("option_buy_leverage", { valueAsNumber: true })}
              type="number"
              min="1"
              step="1"
              aria-label="Option buy leverage"
              className="font-mono"
            />
          </label>
          <label className="space-y-1 text-xs text-text-muted">
            <span>Option sell leverage</span>
            <Input
              {...configForm.register("option_sell_leverage", { valueAsNumber: true })}
              type="number"
              min="1"
              step="1"
              aria-label="Option sell leverage"
              className="font-mono"
            />
          </label>
          <label className="space-y-1 text-xs text-text-muted">
            <span>Equity/F&amp;O square-off</span>
            <Input
              {...configForm.register("squareoff_time")}
              type="time"
              aria-label="Equity and F&O square-off time"
              className="font-mono"
            />
          </label>
          <label className="space-y-1 text-xs text-text-muted">
            <span>MCX square-off</span>
            <Input
              {...configForm.register("mcx_squareoff_time")}
              type="time"
              aria-label="MCX square-off time"
              className="font-mono"
            />
          </label>
        </div>

        {Object.keys(configForm.formState.errors).length > 0 && (
          <p className="text-xs text-loss" role="alert">Review the Practice policy values.</p>
        )}
        {configMutation.isError && (
          <p className="text-xs text-loss" role="alert">{(configMutation.error as Error).message}</p>
        )}
        {configMutation.isSuccess && (
          <p className="text-xs text-profit" role="status">Practice policy saved.</p>
        )}
      </form>

      <div className="border-t border-border-default" />

      {/* Place Practice order against virtual capital (no broker). */}
      <form onSubmit={orderForm.handleSubmit(onPlaceOrder)} className="space-y-3" aria-label="Place paper order">
        <p className="text-xs font-medium text-text-secondary">Place Paper Order</p>

        <div className="flex items-center gap-2">
          <Controller
            control={orderForm.control}
            name="action"
            render={({ field }) => (
              <div
                className="flex rounded-md border border-border-default overflow-hidden shrink-0"
                role="group"
                aria-label="Order side"
              >
                <button
                  type="button"
                  aria-pressed={field.value === "BUY"}
                  onClick={() => field.onChange("BUY")}
                  className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                    field.value === "BUY"
                      ? "bg-profit/15 text-profit"
                      : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
                  }`}
                >
                  BUY
                </button>
                <button
                  type="button"
                  aria-pressed={field.value === "SELL"}
                  onClick={() => field.onChange("SELL")}
                  className={`px-3 py-1.5 text-xs font-medium transition-colors border-l border-border-default ${
                    field.value === "SELL"
                      ? "bg-loss/15 text-loss"
                      : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
                  }`}
                >
                  SELL
                </button>
              </div>
            )}
          />
          <Input
            {...orderForm.register("symbol")}
            placeholder="Symbol"
            aria-label="Order symbol"
            className="flex-1 font-mono uppercase"
          />
          <Input
            {...orderForm.register("exchange")}
            placeholder="Exch"
            aria-label="Order exchange"
            className="w-20 font-mono uppercase"
          />
        </div>

        <div className="flex items-center gap-2">
          <Input
            {...orderForm.register("quantity")}
            type="text"
            inputMode="numeric"
            placeholder="Quantity"
            aria-label="Order quantity"
            className="flex-1 font-mono"
          />
          <Input
            {...orderForm.register("price")}
            type="text"
            inputMode="decimal"
            placeholder="Price (₹)"
            aria-label="Order price"
            className="flex-1 font-mono"
          />
          <Button type="submit" size="sm" disabled={orderMutation.isPending} className="shrink-0">
            {orderMutation.isPending ? "Placing..." : "Place"}
          </Button>
        </div>

        {(orderForm.formState.errors.symbol ||
          orderForm.formState.errors.exchange ||
          orderForm.formState.errors.quantity ||
          orderForm.formState.errors.price) && (
          <p className="text-xs text-loss" role="alert">
            {orderForm.formState.errors.symbol?.message ??
              orderForm.formState.errors.exchange?.message ??
              orderForm.formState.errors.quantity?.message ??
              orderForm.formState.errors.price?.message}
          </p>
        )}
        {orderMutation.isError && (
          <p className="text-xs text-loss" role="alert">{(orderMutation.error as Error).message}</p>
        )}
        {orderResult && (
          <p
            className={`text-xs ${
              orderResult.status === "COMPLETE"
                ? "text-profit"
                : orderResult.status === "PENDING"
                  ? "text-warning"
                  : "text-loss"
            }`}
            role="status"
          >
            {orderResult.status === "COMPLETE"
              ? "✓ Order filled"
              : orderResult.status === "PENDING"
                ? "Order pending"
                : "Order rejected"} — {orderResult.message}
          </p>
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
