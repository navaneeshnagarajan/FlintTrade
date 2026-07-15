/**
 * LlmStep — LLM provider configuration step in the setup wizard (Advanced only).
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
import { LLM_PROVIDERS, normaliseLlmHost } from "@/lib/llmProviders";

// ---------------------------------------------------------------------------
// Schema
// ---------------------------------------------------------------------------

export const llmSchema = z.object({
  provider: z.string().min(1, "Provider is required"),
  model:    z.string().trim().min(1, "Model is required"),
  host:     z.string().optional(),
}).superRefine((values, context) => {
  const provider = LLM_PROVIDERS.find((candidate) => candidate.id === values.provider);
  if (provider?.requiresHost && !values.host?.trim()) {
    context.addIssue({
      code: "custom",
      path: ["host"],
      message: `Host URL is required for ${provider.name}`,
    });
  }
});

export type LlmFormValues = z.infer<typeof llmSchema>;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface LlmStepProps {
  defaultValues?: Partial<LlmFormValues>;
  onComplete: (values: LlmFormValues) => void | Promise<void>;
}

function persistedValues(values: LlmFormValues): LlmFormValues {
  const providerConfig = LLM_PROVIDERS.find((candidate) => candidate.id === values.provider);
  const host = normaliseLlmHost(
    values.provider,
    providerConfig?.requiresHost ? (values.host ?? "").trim() : "",
  );
  return { provider: values.provider, model: values.model.trim(), host };
}

export function LlmStep({ defaultValues, onComplete }: LlmStepProps) {
  const initialProvider = defaultValues?.provider ?? "ollama";
  const initialProviderConfig = LLM_PROVIDERS.find((candidate) => candidate.id === initialProvider);
  const {
    register,
    handleSubmit,
    setValue,
    watch,
    formState: { errors },
  } = useForm<LlmFormValues>({
    resolver: zodResolver(llmSchema),
    defaultValues: {
      provider: initialProvider,
      model: defaultValues?.model ?? initialProviderConfig?.defaultModel ?? "",
      host: normaliseLlmHost(initialProvider, defaultValues?.host ?? ""),
    },
  });

  const provider = watch("provider");
  const providerConfig = LLM_PROVIDERS.find((p) => p.id === provider);
  const defaultHost = providerConfig?.defaultHost ?? "";

  const submit = handleSubmit(async (values) => {
    const nextValues = persistedValues(values);
    await onComplete(nextValues);
  });

  return (
    <form onSubmit={submit} className="space-y-5">
      <div className="space-y-1.5">
        <Label className="text-text-secondary text-xs uppercase tracking-wider">LLM Provider</Label>
        <Select
          value={provider}
          onValueChange={(value) => {
            const nextProvider = LLM_PROVIDERS.find((candidate) => candidate.id === value);
            setValue("provider", value, { shouldValidate: true });
            setValue("model", nextProvider?.defaultModel ?? "", {
              shouldDirty: true,
              shouldValidate: true,
            });
            setValue("host", "", {
              shouldDirty: true,
              shouldValidate: true,
            });
          }}
        >
          <SelectTrigger
            className="w-full bg-surface-base border-border-default text-text-primary"
            aria-label="LLM provider"
            aria-invalid={errors.provider ? "true" : undefined}
            aria-describedby={errors.provider ? "llm-provider-error" : undefined}
          >
            <SelectValue placeholder="Select provider" />
          </SelectTrigger>
          <SelectContent>
            {LLM_PROVIDERS.map((p) => (
              <SelectItem key={p.id} value={p.id}>
                {p.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {errors.provider && (
          <p id="llm-provider-error" role="alert" aria-live="assertive" className="text-red-400 text-xs">
            {errors.provider.message}
          </p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="llmModel" className="text-text-secondary text-xs uppercase tracking-wider">
          Model
        </Label>
        <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
          <Input
            id="llmModel"
            placeholder={providerConfig?.defaultModel || "Enter model identifier"}
            aria-label="LLM model name"
            aria-invalid={errors.model ? "true" : undefined}
            aria-describedby={errors.model ? "llm-model-error" : undefined}
            className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
            {...register("model")}
          />
        </div>
        {errors.model && (
          <p id="llm-model-error" role="alert" aria-live="assertive" className="text-red-400 text-xs">
            {errors.model.message}
          </p>
        )}
      </div>

      {providerConfig?.requiresHost && (
        <div className="space-y-1.5">
          <Label htmlFor="llmHost" className="text-text-secondary text-xs uppercase tracking-wider">
            {provider === "hermes" ? "Local Host URL" : "Host URL"}
          </Label>
          <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
            <Input
              id="llmHost"
              placeholder={defaultHost || "https://your-endpoint.example.com"}
              aria-label={provider === "hermes" ? "LLM local host URL" : "LLM host URL"}
              aria-invalid={errors.host ? "true" : undefined}
              aria-describedby={errors.host ? "llm-host-error" : undefined}
              className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
              {...register("host")}
            />
          </div>
          {errors.host && (
            <p id="llm-host-error" role="alert" aria-live="assertive" className="text-red-400 text-xs">
              {errors.host.message}
            </p>
          )}
        </div>
      )}

      <p className="text-text-muted text-xs">
        {provider === "ollama"
          ? "AI Settings opens after setup so you can confirm runtime and model downloads explicitly."
          : provider === "hermes"
            ? "Hermes uses the local host you provide and does not require an API key."
            : provider === "claude-code-oauth"
              ? "Add the Claude Code OAuth credential in AI Settings after setup; it is stored in a hardened local secret file."
            : provider === "custom"
              ? "Add the endpoint credential in AI Settings after setup; it is stored in a hardened local secret file."
              : "Add the provider credential in AI Settings after setup; it is stored in a hardened local secret file."}
      </p>

      <Button
        type="submit"
        className="w-full bg-primary hover:bg-primary/90 text-primary-foreground"
      >
        <ArrowRight className="size-4" />
        Save and continue
      </Button>
    </form>
  );
}
