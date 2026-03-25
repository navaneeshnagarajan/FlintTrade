/**
 * GeneralSection — persona, font size, and density settings.
 *
 * Phase C: theme picker removed — it lives exclusively in AppearanceSection.
 */

import { FieldRow, SegmentControl, SectionTitle } from "./shared";

interface GeneralSettings {
  fontSize: "small" | "normal" | "large";
  density: "compact" | "comfortable";
}

interface GeneralSectionProps {
  settings: GeneralSettings;
  onChange: (field: keyof GeneralSettings, value: string) => void;
}

export function GeneralSection({ settings, onChange }: GeneralSectionProps) {
  return (
    <div className="space-y-5">
      <SectionTitle>General</SectionTitle>

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
