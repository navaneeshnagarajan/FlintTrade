/**
 * GeneralSection — persona, font size, density settings.
 */

import { useSettingsStore } from "@/stores/settingsStore";
import { FieldRow, SegmentControl, SectionTitle } from "./shared";

const THEMES = [
  { id: "midnight",        label: "Midnight",       desc: "Cool dark (default)"      },
  { id: "obsidian",        label: "Obsidian",       desc: "Ultra-dark, OLED-friendly" },
  { id: "terminal-green",  label: "Terminal Green",  desc: "Matrix hacker style"      },
  { id: "ocean-blue",      label: "Ocean Blue",      desc: "Calm professional blue"   },
  { id: "light",           label: "Light",           desc: "Daytime high-visibility"  },
] as const;

interface GeneralSettings {
  fontSize: "small" | "normal" | "large";
  density: "compact" | "comfortable";
}

interface GeneralSectionProps {
  settings: GeneralSettings;
  onChange: (field: keyof GeneralSettings, value: string) => void;
}

export function GeneralSection({ settings, onChange }: GeneralSectionProps) {
  const theme = useSettingsStore((s) => s.theme);

  return (
    <div className="space-y-5">
      <SectionTitle>General</SectionTitle>

      <FieldRow label="Theme">
        <div className="grid grid-cols-5 gap-2">
          {THEMES.map((t) => (
            <button
              key={t.id}
              type="button"
              aria-label={`Select ${t.label} theme`}
              onClick={() => useSettingsStore.getState().setTheme(t.id)}
              className={`p-3 rounded-lg border text-center transition-all ${
                theme === t.id
                  ? "border-accent bg-accent/10 ring-1 ring-accent/20"
                  : "border-border-default bg-surface-card hover:bg-surface-hover"
              }`}
            >
              <div className="text-xs font-heading font-semibold text-text-primary">{t.label}</div>
              <div className="text-[10px] text-text-muted mt-1">{t.desc}</div>
            </button>
          ))}
        </div>
      </FieldRow>

      <FieldRow
        label="Font Size"
        hint="Affects data tables and number displays across the terminal."
      >
        <SegmentControl
          value={settings.fontSize}
          onChange={(v) => onChange("fontSize", v)}
          options={[
            { value: "small",  label: "Small (12px)"  },
            { value: "normal", label: "Normal (13px)" },
            { value: "large",  label: "Large (14px)"  },
          ]}
        />
      </FieldRow>

      <FieldRow
        label="Density"
        hint="Compact reduces row padding for more data on screen."
      >
        <SegmentControl
          value={settings.density}
          onChange={(v) => onChange("density", v)}
          options={[
            { value: "compact",     label: "Compact"     },
            { value: "comfortable", label: "Comfortable" },
          ]}
        />
      </FieldRow>
    </div>
  );
}
