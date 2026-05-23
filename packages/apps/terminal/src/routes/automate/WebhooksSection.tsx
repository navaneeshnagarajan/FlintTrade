/**
 * WebhooksSection — Manage TradingView webhook endpoints.
 *
 * Three sub-areas surfaced via tabs:
 *  1. Active     — registered endpoints with test/delete actions
 *  2. Create     — form to register a new endpoint
 *  3. Templates  — AlertTemplateBrowser for pre-built payloads
 */

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Loader2, Trash2, Play, Copy, Check } from "lucide-react";

import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { GlassCard } from "@/components/ui/GlassCard";
import { AlertTemplateBrowser } from "@/components/tradingview/AlertTemplateBrowser";

// ---------------------------------------------------------------------------
// Dev-mode sample data — never shown in production builds
// ---------------------------------------------------------------------------

const IS_DEV = import.meta.env.DEV;

interface WebhookEndpoint {
  id: string;
  name: string;
  url: string;
  strategy: string;
  type: "tradingview" | "chartink" | "custom";
  status: "active" | "paused";
  lastTriggered: string | null;
}

const DEV_SAMPLE_ENDPOINTS: WebhookEndpoint[] = [
  {
    id: "wh-001",
    name: "NIFTY Trend Signal",
    url: "/webhook/tradingview/nifty-trend-v1",
    strategy: "nifty-trend-v1",
    type: "tradingview",
    status: "active",
    lastTriggered: new Date(Date.now() - 4 * 60 * 1000).toISOString(),
  },
  {
    id: "wh-002",
    name: "BankNifty Momentum",
    url: "/webhook/tradingview/bnf-momentum",
    strategy: "bnf-momentum",
    type: "tradingview",
    status: "paused",
    lastTriggered: new Date(Date.now() - 25 * 60 * 60 * 1000).toISOString(),
  },
  {
    id: "wh-003",
    name: "ChartInk Breakout Scanner",
    url: "/webhook/chartink/breakout-scanner",
    strategy: "breakout-scanner",
    type: "chartink",
    status: "active",
    lastTriggered: null,
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatLastTriggered(val: string | null): string {
  if (!val) return "Never";
  try {
    const diff = Math.round((Date.now() - new Date(val).getTime()) / 1000);
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return new Date(val).toLocaleString("en-IN", {
      timeZone: "Asia/Kolkata",
      dateStyle: "short",
      timeStyle: "short",
    });
  } catch {
    return val;
  }
}

function typeBadgeClass(type: WebhookEndpoint["type"]): string {
  if (type === "tradingview") return "bg-blue-500/10 text-blue-400 border-0";
  if (type === "chartink") return "bg-purple-500/10 text-purple-400 border-0";
  return "bg-surface-base text-text-muted border-0";
}

function typeLabel(type: WebhookEndpoint["type"]): string {
  if (type === "tradingview") return "TradingView";
  if (type === "chartink") return "ChartInk";
  return "Custom";
}

// ---------------------------------------------------------------------------
// CopyableUrl
// ---------------------------------------------------------------------------

function CopyableUrl({ url }: { url: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard API unavailable — silent fallback
    }
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      title="Copy URL"
      className="inline-flex items-center gap-1.5 font-mono text-xs text-text-secondary hover:text-text-primary transition-colors"
    >
      <span className="truncate max-w-[200px]">{url}</span>
      {copied ? (
        <Check size={11} className="text-profit shrink-0" />
      ) : (
        <Copy size={11} className="shrink-0 opacity-50" />
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// ActiveWebhooksTab
// ---------------------------------------------------------------------------

function ActiveWebhooksTab() {
  const endpoints: WebhookEndpoint[] = IS_DEV ? DEV_SAMPLE_ENDPOINTS : [];

  const [testingId, setTestingId] = useState<string | null>(null);

  const handleTest = (id: string) => {
    setTestingId(id);
    // In production this would POST to /ft-api/v1/webhooks/{id}/test
    setTimeout(() => setTestingId(null), 1500);
  };

  if (endpoints.length === 0) {
    return (
      <p className="py-10 text-center text-xs text-text-muted">
        No webhook endpoints registered. Create one using the Create tab.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-md border border-border-default">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>URL</TableHead>
            <TableHead>Strategy</TableHead>
            <TableHead>Type</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Last Triggered</TableHead>
            <TableHead className="text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {endpoints.map((ep) => (
            <TableRow key={ep.id}>
              <TableCell className="font-medium text-xs text-text-primary">
                {ep.name}
              </TableCell>
              <TableCell>
                <CopyableUrl url={ep.url} />
              </TableCell>
              <TableCell className="font-mono text-xs text-text-secondary">
                {ep.strategy}
              </TableCell>
              <TableCell>
                <Badge className={`text-xs ${typeBadgeClass(ep.type)}`}>
                  {typeLabel(ep.type)}
                </Badge>
              </TableCell>
              <TableCell>
                {ep.status === "active" ? (
                  <Badge className="text-xs bg-profit/10 text-profit border-0">
                    Active
                  </Badge>
                ) : (
                  <Badge className="text-xs bg-atm-bg text-warning border-0">
                    Paused
                  </Badge>
                )}
              </TableCell>
              <TableCell className="text-xs text-text-muted">
                {formatLastTriggered(ep.lastTriggered)}
              </TableCell>
              <TableCell>
                <div className="flex items-center justify-end gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => handleTest(ep.id)}
                    disabled={testingId === ep.id}
                    title="Send test payload"
                    className="h-7 w-7 p-0 text-text-muted hover:text-text-primary"
                  >
                    {testingId === ep.id ? (
                      <Loader2 size={12} className="animate-spin" />
                    ) : (
                      <Play size={12} />
                    )}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    title="Delete endpoint"
                    className="h-7 w-7 p-0 text-text-muted hover:text-loss"
                  >
                    <Trash2 size={12} />
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// CreateWebhookTab — form schema
// ---------------------------------------------------------------------------

const WEBHOOK_TYPES = ["tradingview", "chartink", "custom"] as const;
type WebhookType = (typeof WEBHOOK_TYPES)[number];

const createSchema = z.object({
  name: z.string().min(1, "Name is required").max(64, "Name too long"),
  strategyId: z
    .string()
    .min(1, "Strategy ID is required")
    .max(64, "Strategy ID too long")
    .regex(/^[a-z0-9-_]+$/, "Use lowercase letters, numbers, hyphens, or underscores"),
  type: z.enum(WEBHOOK_TYPES),
  secret: z.string().max(128, "Secret too long").optional(),
});

type CreateFormValues = z.infer<typeof createSchema>;

function CreateWebhookTab() {
  const {
    register,
    handleSubmit,
    watch,
    setValue,
    formState: { errors, isSubmitting },
    reset,
  } = useForm<CreateFormValues>({
    resolver: zodResolver(createSchema),
    defaultValues: { type: "tradingview" },
  });

  const watchedType = watch("type");
  const watchedStrategyId = watch("strategyId") ?? "";

  const previewUrl =
    watchedStrategyId.trim()
      ? `/webhook/${watchedType}/${watchedStrategyId.trim()}`
      : `/webhook/${watchedType}/<strategy-id>`;

  const onSubmit = async (_values: CreateFormValues) => {
    // In production this would POST to /ft-api/v1/webhooks
    await new Promise((r) => setTimeout(r, 800));
    reset();
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-5 max-w-lg">
      {/* Name */}
      <div className="space-y-1.5">
        <Label htmlFor="wh-name" className="text-xs font-medium text-text-primary">
          Name
        </Label>
        <Input
          id="wh-name"
          placeholder="e.g. NIFTY Trend Signal"
          className="h-8 text-xs"
          {...register("name")}
        />
        {errors.name && (
          <p className="text-xs text-loss">{errors.name.message}</p>
        )}
      </div>

      {/* Type */}
      <div className="space-y-1.5">
        <Label htmlFor="wh-type" className="text-xs font-medium text-text-primary">
          Type
        </Label>
        <Select
          value={watchedType}
          onValueChange={(v) => setValue("type", v as WebhookType)}
        >
          <SelectTrigger id="wh-type" className="h-8 text-xs">
            <SelectValue placeholder="Select type" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="tradingview" className="text-xs">TradingView</SelectItem>
            <SelectItem value="chartink" className="text-xs">ChartInk</SelectItem>
            <SelectItem value="custom" className="text-xs">Custom</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Strategy ID */}
      <div className="space-y-1.5">
        <Label htmlFor="wh-strategy" className="text-xs font-medium text-text-primary">
          Strategy ID
        </Label>
        <Input
          id="wh-strategy"
          placeholder="e.g. nifty-trend-v1"
          className="h-8 text-xs font-mono"
          {...register("strategyId")}
        />
        {errors.strategyId ? (
          <p className="text-xs text-loss">{errors.strategyId.message}</p>
        ) : (
          <p className="text-xs text-text-muted">
            Lowercase letters, numbers, hyphens, and underscores only.
          </p>
        )}
      </div>

      {/* Secret */}
      <div className="space-y-1.5">
        <Label htmlFor="wh-secret" className="text-xs font-medium text-text-primary">
          Secret{" "}
          <span className="font-normal text-text-muted">(optional — used for HMAC verification)</span>
        </Label>
        <Input
          id="wh-secret"
          type="password"
          autoComplete="new-password"
          placeholder="Leave blank to skip HMAC verification"
          className="h-8 text-xs font-mono"
          {...register("secret")}
        />
        {errors.secret && (
          <p className="text-xs text-loss">{errors.secret.message}</p>
        )}
      </div>

      {/* Generated URL preview */}
      <div className="rounded-md border border-border-default bg-surface-base px-3 py-2.5">
        <p className="text-xs text-text-muted mb-1">Generated endpoint URL</p>
        <p className="font-mono text-xs text-text-primary break-all">{previewUrl}</p>
      </div>

      <Button
        type="submit"
        size="sm"
        disabled={isSubmitting}
        className="h-8 px-4 text-xs gap-1.5"
      >
        {isSubmitting && <Loader2 size={12} className="animate-spin" />}
        Create Endpoint
      </Button>
    </form>
  );
}

// ---------------------------------------------------------------------------
// WebhooksSection — top-level export
// ---------------------------------------------------------------------------

export default function WebhooksSection() {
  return (
    <div className="space-y-4">
      <GlassCard className="p-6">
        <div className="mb-5">
          <h3 className="font-heading font-semibold text-lg text-text-primary">
            Webhooks
          </h3>
          <p className="text-sm text-text-secondary mt-0.5">
            Register inbound webhook endpoints for TradingView, ChartInk, and custom
            integrations. Each endpoint forwards payloads to the configured strategy.
          </p>
        </div>

        <Tabs defaultValue="active">
          <TabsList className="mb-5">
            <TabsTrigger value="active" className="text-xs">
              Active
            </TabsTrigger>
            <TabsTrigger value="create" className="text-xs">
              Create
            </TabsTrigger>
            <TabsTrigger value="templates" className="text-xs">
              Alert Templates
            </TabsTrigger>
          </TabsList>

          <TabsContent value="active">
            <ActiveWebhooksTab />
          </TabsContent>

          <TabsContent value="create">
            <CreateWebhookTab />
          </TabsContent>

          <TabsContent value="templates">
            <AlertTemplateBrowser scrollHeight="520px" />
          </TabsContent>
        </Tabs>
      </GlassCard>
    </div>
  );
}
