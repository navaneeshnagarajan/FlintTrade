import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import "@testing-library/jest-dom";

const api = vi.hoisted(() => ({
  listPresets: vi.fn(), updatePreset: vi.fn(), createPreset: vi.fn(),
  deletePreset: vi.fn(), forkPreset: vi.fn(),
}));
vi.mock("@/services/ftApi", () => api);
vi.mock("@/layout/widgetFactory", () => ({ widgetCatalog: [] }));
import { PresetSection } from "../PresetSection";

const alpha = { id: "A", name: "Alpha", description: "", widgets: [], is_builtin: false };
const beta = { ...alpha, id: "B", name: "Beta" };
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><PresetSection /></QueryClientProvider>);
}
function deferred() {
  let resolve!: (value: unknown) => void;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}
beforeEach(() => {
  vi.resetAllMocks();
  api.listPresets.mockResolvedValue({ presets: [alpha, beta] });
});

it("keeps the newer editor open after the previous preset save completes", async () => {
  const request = deferred();
  api.updatePreset.mockReturnValue(request.promise);
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit Alpha" }));
  fireEvent.change(screen.getByLabelText("Name *"), { target: { value: "Alpha submitted" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(api.updatePreset).toHaveBeenCalledWith("A", expect.objectContaining({ name: "Alpha submitted" })));
  fireEvent.click(screen.getByRole("button", { name: "Edit Beta" }));
  expect(screen.getByLabelText("Name *")).toHaveValue("Beta");
  await act(async () => request.resolve({ status: "success" }));
  await waitFor(() => expect(screen.getByLabelText("Name *")).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Name *"), { target: { value: "Beta draft" } });
  expect(screen.getByLabelText("Name *")).toHaveValue("Beta draft");
});

it("prevents edits to the submitted draft until the save finishes", async () => {
  const request = deferred();
  api.updatePreset.mockReturnValue(request.promise);
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit Alpha" }));
  fireEvent.change(screen.getByLabelText("Name *"), { target: { value: "Alpha submitted" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(screen.getByLabelText("Name *")).toBeDisabled());
  fireEvent.change(screen.getByLabelText("Name *"), { target: { value: "Unsubmitted text" } });
  expect(screen.getByLabelText("Name *")).toHaveValue("Alpha submitted");
  await act(async () => request.resolve({ status: "success" }));
  await waitFor(() => expect(screen.queryByLabelText("Edit Preset form")).not.toBeInTheDocument());
});

it("keeps a retained create draft and the current editor after importing another preset", async () => {
  const request = deferred();
  api.createPreset.mockReturnValue(request.promise);
  const view = mount();
  await screen.findByRole("button", { name: "Edit Alpha" });
  fireEvent.click(screen.getByRole("button", { name: "Create a new workspace preset" }));
  fireEvent.change(screen.getByLabelText("Name *"), { target: { value: "Unrelated create draft" } });
  fireEvent.click(screen.getByRole("button", { name: "Edit Alpha" }));
  const input = view.container.querySelector('input[type="file"]')!;
  fireEvent.change(input, { target: { files: [new File([JSON.stringify({ name: "Imported", widgets: [] })], "import.json", { type: "application/json" })] } });
  await waitFor(() => expect(api.createPreset).toHaveBeenCalledWith({ name: "Imported", description: "", widgets: [] }));
  await act(async () => request.resolve({ status: "success" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled());
  expect(screen.getByLabelText("Name *")).toHaveValue("Alpha");
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fireEvent.click(screen.getByRole("button", { name: "Create a new workspace preset" }));
  expect(screen.getByLabelText("Name *")).toHaveValue("Unrelated create draft");
});

it("blocks import while an editor create remains pending", async () => {
  const request = deferred();
  api.createPreset.mockReturnValue(request.promise);
  const view = mount();
  await screen.findByRole("button", { name: "Edit Alpha" });
  fireEvent.click(screen.getByRole("button", { name: "Create a new workspace preset" }));
  fireEvent.change(screen.getByLabelText("Name *"), { target: { value: "Editor submitted" } });
  fireEvent.click(screen.getByRole("button", { name: "Create" }));
  await waitFor(() => expect(api.createPreset).toHaveBeenCalledTimes(1));
  expect(screen.getByRole("button", { name: "Import preset from JSON file" })).toBeDisabled();
  const input = view.container.querySelector('input[type="file"]')!;
  fireEvent.change(input, { target: { files: [new File(['{"name":"Imported","widgets":[]}'], "import.json")] } });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
  expect(api.createPreset).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText("Name *")).toBeDisabled();
  await act(async () => request.resolve({ status: "success" }));
});

it("rechecks pending writes when a delayed file read completes", async () => {
  const readers: FileReader[] = [];
  const read = vi.spyOn(FileReader.prototype, "readAsText").mockImplementation(function (this: FileReader) { readers.push(this); });
  try {
    const request = deferred();
    api.createPreset.mockReturnValue(request.promise);
    const view = mount();
    await screen.findByRole("button", { name: "Edit Alpha" });
    fireEvent.click(screen.getByRole("button", { name: "Create a new workspace preset" }));
    fireEvent.change(screen.getByLabelText("Name *"), { target: { value: "Editor submitted" } });
    const input = view.container.querySelector('input[type="file"]')!;
    fireEvent.change(input, { target: { files: [new File(['{"name":"Imported","widgets":[]}'], "import.json")] } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(api.createPreset).toHaveBeenCalledTimes(1));
    await act(async () => {
      Object.defineProperty(readers[0]!, "result", { value: '{"name":"Imported","widgets":[]}' });
      readers[0]!.dispatchEvent(new ProgressEvent("load"));
    });
    expect(api.createPreset).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/finish.*before importing/i)).toBeVisible();
    await act(async () => request.resolve({ status: "success" }));
  } finally {
    read.mockRestore();
  }
});
