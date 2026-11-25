import { useState } from "react";
import { Settings2 } from "lucide-react";
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
        className="flex min-w-0 items-center gap-1"
      >
      <div className="flex min-w-0 items-center gap-1 overflow-x-auto" aria-hidden="true">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            tabIndex={-1}
            onClick={() => handleSwitch(tab.id)}
            className={`h-6 max-w-[9rem] shrink-0 truncate rounded-full px-2 text-[11px] ${tab.id === activeTabId ? "bg-white/15 text-white" : "text-white/55 hover:bg-white/10"}`}
          >
            {tab.name}
          </button>
        ))}
      </div>
      <label htmlFor="active-workspace" className="sr-only">
        Active workspace
      </label>
      <select
        id="active-workspace"
        value={activeTabId}
        onChange={(event) => handleSwitch(event.target.value)}
        className="sr-only"
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
