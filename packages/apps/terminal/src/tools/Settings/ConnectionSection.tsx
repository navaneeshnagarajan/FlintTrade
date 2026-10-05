/** Broker gateway configuration with one explicit, transactional save. */

import { OpenAlgoConnectionForm } from "@/components/account/OpenAlgoConnectionForm";
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
      <SectionTitle>OpenAlgo bridge</SectionTitle>

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


    </div>
  );
}
