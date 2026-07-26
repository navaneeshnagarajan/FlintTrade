/**
 * WebhooksSection — Manage generic (custom JSON) webhook endpoints.
 *
 * Two sub-areas surfaced via tabs:
 *  1. Active     — registered endpoints with test/delete actions
 *  2. Create     — form to register a new endpoint
 */

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Trash2, Copy, Check } from "lucide-react";

import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { GlassCard } from "@/components/ui/GlassCard";
import {
  createWebhook,
  deleteWebhook,
  getWebhooks,
  setWebhookEnabled,
  type WebhookConfig,
} from "@/services/ftApi";
import { InlineToast, useInlineToast } from "./shared";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function slugFromPath(path: string): string {
  return path.split("/").filter(Boolean).slice(2).join("/") || path;
}

// ---------------------------------------------------------------------------
// CopyableUrl
// ---------------------------------------------------------------------------

function CopyablePath({ path }: { path: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(path);
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
      title="Copy relay path"
      className="inline-flex items-center gap-1.5 font-mono text-xs text-text-secondary hover:text-text-primary transition-colors"
    >
      <span className="truncate max-w-[200px]">{path}</span>
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

interface ActiveWebhooksTabProps {
  endpoints: WebhookConfig[];
  isLoading: boolean;
  isError: boolean;
  deletingId: string | null;
  togglingId: string | null;
  onDelete: (id: string) => void;
  onToggle: (id: string, enabled: boolean) => void;
}

function ActiveWebhooksTab({
  endpoints,
  isLoading,
  isError,
  deletingId,
  togglingId,
  onDelete,
  onToggle,
}: ActiveWebhooksTabProps) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-10">
        <Loader2 size={18} className="animate-spin text-text-muted" />
      </div>
    );
  }

  if (isError) {
    return (
      <p className="py-10 text-center text-xs text-loss">
        Failed to load webhooks. Backend may be offline.
      </p>
    );
  }

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
            <TableHead>Relay path</TableHead>
            <TableHead>Slug</TableHead>
            <TableHead>Status</TableHead>
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
                <CopyablePath path={ep.path} />
              </TableCell>
              <TableCell className="font-mono text-xs text-text-secondary">
                {slugFromPath(ep.path)}
              </TableCell>
              <TableCell>
                <div className="flex items-center gap-2">
                  <Switch
                    checked={ep.enabled}
                    onCheckedChange={(enabled) => onToggle(ep.id, enabled)}
                    disabled={
                      togglingId === ep.id || ep.secret_configured === false
                    }
                    aria-label={`${ep.enabled ? "Disable" : "Enable"} ${ep.name}`}
                  />
                  <span className="text-xs text-text-muted">
                    {ep.secret_configured === false
                      ? "Needs secret"
                      : ep.enabled
                        ? "Active"
                        : "Disabled"}
                  </span>
                </div>
              </TableCell>
              <TableCell>
                <div className="flex items-center justify-end gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => onDelete(ep.id)}
                    disabled={deletingId === ep.id}
                    title="Delete endpoint"
                    aria-label={`Delete ${ep.name}`}
                    className="h-7 w-7 p-0 text-text-muted hover:text-loss"
                  >
                    {deletingId === ep.id ? (
                      <Loader2 size={12} className="animate-spin" />
                    ) : (
                      <Trash2 size={12} />
                    )}
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

const createSchema = z.object({
  name: z.string().min(1, "Name is required").max(64, "Name too long"),
  strategyId: z
    .string()
    .min(1, "Strategy ID is required")
    .max(64, "Strategy ID too long")
    .regex(
      /^[a-z0-9-_]+$/,
      "Use lowercase letters, numbers, hyphens, or underscores",
    ),
  secret: z
    .string()
    .trim()
    .min(1, "Signing secret is required")
    .max(128, "Secret too long"),
});

type CreateFormValues = z.infer<typeof createSchema>;

interface CreateWebhookTabProps {
  onCreate: (values: CreateFormValues) => Promise<void>;
  submissionError?: string;
}

function CreateWebhookTab({
  onCreate,
  submissionError,
}: CreateWebhookTabProps) {
  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
    reset,
  } = useForm<CreateFormValues>({
    resolver: zodResolver(createSchema),
  });

  const watchedStrategyId = watch("strategyId") ?? "";

  const previewUrl = watchedStrategyId.trim()
    ? `/v1/webhook/custom/${watchedStrategyId.trim()}`
    : "/v1/webhook/custom/<strategy-id>";

  const onSubmit = async (values: CreateFormValues) => {
    try {
      await onCreate(values);
      reset();
    } catch {
      // The mutation owns the inline error state; contain the rejected promise.
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-5 max-w-lg">
      {/* Name */}
      <div className="space-y-1.5">
        <Label
          htmlFor="wh-name"
          className="text-xs font-medium text-text-primary"
        >
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

      {/* Strategy ID */}
      <div className="space-y-1.5">
        <Label
          htmlFor="wh-strategy"
          className="text-xs font-medium text-text-primary"
        >
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
        <Label
          htmlFor="wh-secret"
          className="text-xs font-medium text-text-primary"
        >
          Signing secret
        </Label>
        <Input
          id="wh-secret"
          type="password"
          autoComplete="new-password"
          placeholder="Enter relay signing secret"
          className="h-8 text-xs font-mono"
          {...register("secret")}
        />
        {errors.secret && (
          <p className="text-xs text-loss">{errors.secret.message}</p>
        )}
      </div>

      {/* Generated relay-path preview */}
      <div className="rounded-md border border-border-default bg-surface-base px-3 py-2.5">
        <p className="text-xs text-text-muted mb-1">Relay path</p>
        <p className="font-mono text-xs text-text-primary break-all">
          {previewUrl}
        </p>
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
      {submissionError && (
        <p role="alert" className="text-xs text-loss" aria-live="polite">
          {submissionError}
        </p>
      )}
    </form>
  );
}

// ---------------------------------------------------------------------------
// WebhooksSection — top-level export
// ---------------------------------------------------------------------------

export default function WebhooksSection() {
  const queryClient = useQueryClient();
  const { toast, setToast, dismissToast } = useInlineToast();
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);

  const webhooksQuery = useQuery({
    queryKey: ["webhooks"],
    queryFn: getWebhooks,
  });

  const webhooks = webhooksQuery.data?.webhooks ?? [];

  const createMutation = useMutation({
    mutationFn: (values: CreateFormValues) =>
      createWebhook({
        name: values.name.trim(),
        type: "custom",
        path: `/v1/webhook/custom/${values.strategyId.trim()}`,
        enabled: true,
        secret: values.secret.trim(),
      }),
    onSuccess: async () => {
      setToast({ msg: "Webhook created", variant: "success" });
      await queryClient.invalidateQueries({ queryKey: ["webhooks"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteWebhook(id),
    onMutate: (id) => {
      setDeletingId(id);
    },
    onSuccess: async () => {
      setToast({ msg: "Webhook deleted", variant: "success" });
      await queryClient.invalidateQueries({ queryKey: ["webhooks"] });
    },
    onError: (err: Error) => {
      setToast({
        msg: err.message || "Failed to delete webhook",
        variant: "error",
      });
    },
    onSettled: () => {
      setDeletingId(null);
    },
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      setWebhookEnabled(id, enabled),
    onMutate: ({ id }) => {
      setTogglingId(id);
    },
    onSuccess: async () => {
      setToast({ msg: "Webhook status updated", variant: "success" });
      await queryClient.invalidateQueries({ queryKey: ["webhooks"] });
    },
    onError: (err: Error) => {
      setToast({
        msg: err.message || "Failed to update webhook",
        variant: "error",
      });
    },
    onSettled: () => {
      setTogglingId(null);
    },
  });

  const handleCreate = async (values: CreateFormValues) => {
    await createMutation.mutateAsync(values);
  };

  return (
    <div className="space-y-4">
      <GlassCard className="p-6">
        <div className="mb-5">
          <h3 className="font-heading font-semibold text-lg text-text-primary">
            Webhooks
          </h3>
          <p className="text-sm text-text-secondary mt-0.5">
            Register signed relay endpoints for your own scripts and custom
            JSON payloads.
          </p>
        </div>

        {toast && (
          <div className="mb-4">
            <InlineToast
              message={toast.msg}
              variant={toast.variant}
              onDismiss={dismissToast}
            />
          </div>
        )}

        <Tabs defaultValue="active">
          <TabsList className="mb-5">
            <TabsTrigger value="active" className="text-xs">
              Active
            </TabsTrigger>
            <TabsTrigger value="create" className="text-xs">
              Create
            </TabsTrigger>
          </TabsList>

          <TabsContent value="active">
            <ActiveWebhooksTab
              endpoints={webhooks}
              isLoading={webhooksQuery.isLoading}
              isError={webhooksQuery.isError}
              deletingId={deletingId}
              togglingId={togglingId}
              onDelete={(id) => deleteMutation.mutate(id)}
              onToggle={(id, enabled) => toggleMutation.mutate({ id, enabled })}
            />
          </TabsContent>

          <TabsContent value="create">
            <CreateWebhookTab
              onCreate={handleCreate}
              submissionError={
                createMutation.error instanceof Error
                  ? createMutation.error.message || "Failed to create webhook"
                  : undefined
              }
            />
          </TabsContent>
        </Tabs>
      </GlassCard>
    </div>
  );
}
