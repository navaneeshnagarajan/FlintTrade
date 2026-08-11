import { useState } from "react";
import { Layout, Settings2 } from "lucide-react";
import { useLocation, useNavigate } from "react-router";
import { useLayoutStore } from "@/stores/layoutStore";

export default function WorkspaceSwitcher() {
  const location = useLocation();
  const navigate = useNavigate();
  const [switchError, setSwitchError] = useState<string | null>(null);
  const tabs = useLayoutStore((state) => state.tabs);
  const activeTabId = useLayoutStore((state) => state.activeTabId);
  const setActiveTab = useLayoutStore((state) => state.setActiveTab);
  const setPresetPickerOpen = useLayoutStore((state) => state.setPresetPickerOpen);

  const handleSwitch = (nextId: string) => {
    const previousId = activeTabId;
    try {
      setActiveTab(nextId);
      setSwitchError(null);
    } catch (error) {
      try {
        setActiveTab(previousId);
      } catch {
        // Zustand restored the in-memory selection before persistence failed.
      }
      const detail = error instanceof Error ? error.message : "unknown storage error";
      setSwitchError(`Workspace could not be switched: ${detail}`);
    }
  };

  const handleManage = () => {
    setPresetPickerOpen(true);
    if (location.pathname !== "/trade") navigate("/trade");
  };

  return (
    <div className="relative flex flex-col">
      <div
        data-testid="workspace-switcher"
        className="flex items-center gap-1 h-7 px-2 rounded text-xs text-text-secondary border border-border-default/50 bg-surface-base/50"
      >
      <Layout size={12} className="text-text-muted" aria-hidden="true" />
      <label htmlFor="active-workspace" className="sr-only">
        Active workspace
      </label>
      <select
        id="active-workspace"
        value={activeTabId}
        onChange={(event) => handleSwitch(event.target.value)}
        className="max-w-[12rem] cursor-pointer truncate bg-transparent font-medium text-text-secondary outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        {tabs.map((tab) => (
          <option key={tab.id} value={tab.id}>
            {tab.name}
          </option>
        ))}
      </select>
      <button
        type="button"
        aria-label="Manage workspaces"
        onClick={handleManage}
        className="ml-1 rounded p-0.5 text-text-muted hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <Settings2 size={12} aria-hidden="true" />
      </button>
      </div>
      {switchError && (
        <p
          role="alert"
          className="absolute right-0 top-8 z-50 w-64 rounded border border-red-800 bg-red-950 px-2 py-1 text-xs text-red-200 shadow"
        >
          {switchError}
        </p>
      )}
    </div>
  );
}
