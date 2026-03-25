/**
 * GeneralSection — persona and font size settings.
 *
 * Phase C: theme picker removed — it lives exclusively in AppearanceSection.
 * Density removed — it lives exclusively in AppearanceSection > Layout.
 */

import { FieldRow, SegmentControl, SectionTitle } from "./shared";

interface GeneralSettings {
  fontSize: "small" | "normal" | "large";
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
    </div>
  );
}
