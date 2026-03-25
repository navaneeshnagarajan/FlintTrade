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
import { LLM_PROVIDERS, LOCAL_PROVIDERS } from "@/lib/llmProviders";

// ---------------------------------------------------------------------------
// Schema
// ---------------------------------------------------------------------------

export const llmSchema = z.object({
  provider: z.string().min(1, "Provider is required"),
  model:    z.string().min(1, "Model is required"),
  host:     z.string().optional(),
});

export type LlmFormValues = z.infer<typeof llmSchema>;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface LlmStepProps {
  onComplete: (values: LlmFormValues) => void;
}

export function LlmStep({ onComplete }: LlmStepProps) {
  const {
    register,
    handleSubmit,
    setValue,
    watch,
    formState: { errors },
  } = useForm<LlmFormValues>({
    resolver: zodResolver(llmSchema),
    defaultValues: { provider: "openai", model: "gpt-4o-mini", host: "" },
  });

  const provider = watch("provider");
  const isLocal = LOCAL_PROVIDERS.has(provider);

  const providerConfig = LLM_PROVIDERS.find((p) => p.id === provider);
  const defaultHost = providerConfig?.defaultHost ?? "";

  return (
    <form onSubmit={handleSubmit(onComplete)} className="space-y-5">
      <div className="space-y-1.5">
        <Label className="text-text-secondary text-xs uppercase tracking-wider">LLM Provider</Label>
        <Select value={provider} onValueChange={(v) => setValue("provider", v)}>
          <SelectTrigger
            className="w-full bg-surface-base border-border-default text-text-primary"
            aria-label="LLM provider"
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
        {errors.provider && <p className="text-red-400 text-xs">{errors.provider.message}</p>}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="llmModel" className="text-text-secondary text-xs uppercase tracking-wider">
          Model
        </Label>
        <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
          <Input
            id="llmModel"
            placeholder={
              isLocal
                ? "qwen3-9b"
                : provider === "anthropic"
                  ? "claude-3-5-haiku-20241022"
                  : "gpt-4o-mini"
            }
            aria-label="LLM model name"
            className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
            {...register("model")}
          />
        </div>
        {errors.model && <p className="text-red-400 text-xs">{errors.model.message}</p>}
      </div>

      {isLocal && (
        <div className="space-y-1.5">
          <Label htmlFor="llmHost" className="text-text-secondary text-xs uppercase tracking-wider">
            Local Host URL
          </Label>
          <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
            <Input
              id="llmHost"
              placeholder={defaultHost || "http://127.0.0.1:1234"}
              aria-label="LLM local host URL"
              className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
              {...register("host")}
            />
          </div>
        </div>
      )}

      <p className="text-text-muted text-xs">
        API keys are stored in your workspace config (~/.flinttrade/workspace.json), never in this app.
      </p>

      <Button type="submit" className="w-full bg-primary hover:bg-primary/90 text-primary-foreground">
        Continue
        <ArrowRight className="size-4 ml-2" />
      </Button>
    </form>
  );
}
