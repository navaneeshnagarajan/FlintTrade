/** Broker gateway configuration with one explicit, transactional save. */

import { Wand2 } from "lucide-react";

import { OpenAlgoConnectionForm } from "@/components/account/OpenAlgoConnectionForm";
import { Button } from "@/components/ui/button";
import type { ConnectionFormValues } from "@/routes/setup/connectionForm";
import { SectionTitle } from "./shared";

interface ApiSettings {
  host: string;
  port: string;
  wsPort: string;
  apiKeyConfigured: boolean;
  apiKeyLast4: string;
}

interface ConnectionSectionProps {
  settings: ApiSettings;
  onSaved: (values: ConnectionFormValues) => void;
}

export function ConnectionSection({ settings, onSaved }: ConnectionSectionProps) {
  return (
    <div className="space-y-5">
      <SectionTitle>Broker Gateway</SectionTitle>

      <OpenAlgoConnectionForm
        defaultValues={{
          host: settings.host,
          port: settings.port,
          apiKey: "",
          wsPort: settings.wsPort,
        }}
        apiKeyConfigured={settings.apiKeyConfigured}
        apiKeyLast4={settings.apiKeyLast4}
        submitLabel="Save Connection"
        submitIcon="save"
        onSaved={onSaved}
      />

      <div className="pt-4 border-t border-border-default space-y-2">
        <p className="text-xs text-text-muted">
          The setup wizard also configures trading defaults and risk limits.
        </p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() =>
            window.dispatchEvent(
              new CustomEvent("flinttrade:navigate", { detail: "/setup" }),
            )
          }
          className="border-border-default text-text-secondary hover:text-text-primary"
        >
          <Wand2 size={12} className="mr-1.5" aria-hidden="true" />
          Open setup wizard
        </Button>
      </div>
    </div>
  );
}
