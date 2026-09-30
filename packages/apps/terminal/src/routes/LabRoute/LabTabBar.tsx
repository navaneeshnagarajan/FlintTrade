import { PageTabs } from "@/components/layout/Page";
import { type TabId, type TabDef, TABS } from "./types";

export interface LabTabBarProps {
  active: TabId;
  onChange: (id: TabId) => void;
  tabs?: TabDef[];
}

export function LabTabBar({ active, onChange, tabs = TABS }: LabTabBarProps) {
  return (
    <PageTabs<TabId>
      tabs={tabs}
      value={active}
      onChange={onChange}
      label="Strategy Lab sections"
      idPrefix="lab"
    />
  );
}
