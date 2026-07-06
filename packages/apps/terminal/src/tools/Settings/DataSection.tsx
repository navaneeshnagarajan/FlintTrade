/**
 * DataSection — fast storage path and archive storage path configuration.
 */

import { FieldRow, TextInput, SectionTitle } from "./shared";
import { HistoricalDownloadPanel } from "./HistoricalDownloadPanel";
import { WatchlistManagerPanel } from "./WatchlistManagerPanel";
import { LocalDataPanel } from "./LocalDataPanel";

interface DataPathSettings {
  fastStoragePath: string;
  archiveStoragePath: string;
}

interface DataSectionProps {
  settings: DataPathSettings;
  onChange: (field: keyof DataPathSettings, value: string) => void;
}

export function DataSection({ settings, onChange }: DataSectionProps) {
  return (
    <div className="space-y-5">
      <SectionTitle>Data Paths</SectionTitle>

      <div className="p-3 rounded bg-surface-card border border-border-default text-xs text-text-muted">
        Storage paths are read by the Python backend on startup. Changes take effect after restarting services.
        Leave blank to use the default path (<code className="font-mono text-text-secondary">~/.flinttrade/</code>).
      </div>

      <FieldRow
        label="Fast Storage Path"
        hint="DuckDB database and intraday tick cache. Use an SSD path for best performance."
        tooltip="Path for tick data and real-time caches. Use SSD for best performance. Default: ~/.flinttrade/data/"
      >
        <TextInput
          value={settings.fastStoragePath}
          onChange={(v) => onChange("fastStoragePath", v)}
          placeholder="~/.flinttrade/data/fast"
          aria-label="Fast storage path"
        />
      </FieldRow>

      <FieldRow
        label="Archive Storage Path"
        hint="Long-term OHLCV history and local audit logs (operator-controlled retention). Can be a slower disk."
        tooltip="Path for historical OHLCV data and audit logs. Can be slower storage. Default: ~/.flinttrade/archive/"
      >
        <TextInput
          value={settings.archiveStoragePath}
          onChange={(v) => onChange("archiveStoragePath", v)}
          placeholder="~/.flinttrade/data/archive"
          aria-label="Archive storage path"
        />
      </FieldRow>

      <WatchlistManagerPanel />

      <HistoricalDownloadPanel />

      <LocalDataPanel />
    </div>
  );
}
