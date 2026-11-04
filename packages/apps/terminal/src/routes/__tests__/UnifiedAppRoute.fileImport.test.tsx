import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BrowserRouter } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { UnifiedAppsHost } from "../UnifiedAppsHost";
import { useAuthStore } from "@/stores/authStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";

// Real retained host, route, docking renderer, export and import validation.
// Only unrelated tool leaves and the browser download boundary are substituted.
vi.mock("@/routes/SettingsRoute", () => ({ default: () => <p>Preferences leaf</p> }));
vi.mock("@/components/help/KnowledgeSelector", () => ({ default: () => <p>Knowledge leaf</p> }));
vi.mock("@/routes/TerminalRoute", () => ({ KillSwitchPill: () => null }));
vi.mock("@/chrome/InstrumentLinks", () => ({ InstrumentLinks: () => null }));
vi.mock("@/routes/SetupAccountRoute", () => ({ PracticeLaterSetup: () => null }));

beforeEach(() => {
  localStorage.clear();
  window.history.replaceState(null, "", "/settings");
  useAuthStore.setState({ status: "logged-out", token: null });
  useBrokerStore.setState({ activeAccountId: null });
  useModeStore.setState({ mode: "explore" });
  const rect = { x: 0, y: 0, width: 1024, height: 700, top: 0, left: 0, right: 1024, bottom: 700, toJSON: () => ({}) };
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(rect);
  vi.stubGlobal("ResizeObserver", class {
    constructor(private callback: ResizeObserverCallback) {}
    observe(target: Element) { this.callback([{ target, contentRect: rect } as ResizeObserverEntry], this as unknown as ResizeObserver); }
    unobserve() {}
    disconnect() {}
  });
});
afterEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function readBlob(blob: Blob) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => typeof reader.result === "string" ? resolve(reader.result) : reject(new Error("Expected layout text"));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(blob);
  });
}
function uploadFile(parts: BlobPart[], name: string) {
  const file = new File(parts, name, { type: "application/json" });
  Object.defineProperty(file, "text", { value: () => readBlob(file) });
  return file;
}

it("imports the same selected export again after a preset, and again after a refused file, without changing scope", async () => {
  const createObjectURL = vi.fn<(blob: Blob) => string>(() => "blob:layout-download");
  class DownloadURL extends URL {}
  Object.defineProperties(DownloadURL, {
    createObjectURL: { value: createObjectURL }, revokeObjectURL: { value: vi.fn() },
  });
  vi.stubGlobal("URL", DownloadURL);
  const downloads: string[] = [];
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { downloads.push(this.download); });
  const user = userEvent.setup();
  render(<BrowserRouter><UnifiedAppsHost /></BrowserRouter>);
  await screen.findByText("Preferences leaf");
  const app = within(screen.getByRole("region", { name: "Settings app" }));
  await user.click(app.getByRole("button", { name: "Add widget" }));
  await user.click(screen.getByRole("button", { name: "Add Shared knowledge" }));
  await screen.findByText("Knowledge leaf");
  fireEvent.click(app.getByText("Layout actions"));
  await user.click(app.getByRole("button", { name: "Export layout" }));
  expect(downloads).toEqual(["flinttrade-settings-layout.json"]);
  const exported = createObjectURL.mock.calls[0][0];
  const file = uploadFile([exported], downloads[0]);
  const input = app.getByLabelText("Import app layout");
  const preset = app.getByRole("combobox", { name: "Settings preset" });
  for (let selection = 0; selection < 2; selection++) {
    await user.selectOptions(preset, "default");
    expect(screen.queryByText("Knowledge leaf")).not.toBeInTheDocument();
    // user-event models native same-file change suppression. Do not replace
    // this with fireEvent.change or direct invocation of an import handler.
    await user.upload(input, file);
    expect(await screen.findByText("Knowledge leaf")).toBeVisible();
    expect(app.getByRole("status")).toHaveTextContent("Imported presentation layout; execution unchanged.");
    expect(preset).toHaveValue("");
    expect(app.queryByRole("alert")).not.toBeInTheDocument();
    expect(app.getByLabelText("Import app layout")).toBe(input);
  }
  const invalid = JSON.parse(await readBlob(exported));
  invalid.app = "terminal";
  await user.upload(input, uploadFile([JSON.stringify(invalid)], "wrong-app.json"));
  expect(await app.findByRole("alert")).toHaveTextContent("Not a compatible fresh app layout");
  expect(app.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.getByText("Knowledge leaf")).toBeVisible();
  await user.upload(input, file);
  expect(await app.findByRole("status")).toHaveTextContent("Imported presentation layout; execution unchanged.");
  expect(app.queryByRole("alert")).not.toBeInTheDocument();
  expect(preset).toHaveValue("");
  expect(app.getByTestId("app-execution-scope")).toHaveTextContent("Example · No execution account selected");
  expect(useAuthStore.getState().status).toBe("logged-out");
  expect(useBrokerStore.getState().activeAccountId).toBeNull();
  expect(useModeStore.getState().mode).toBe("explore");
});
