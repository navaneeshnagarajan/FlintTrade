import { Activity } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ServiceConnectionSetup from "../ServiceConnectionSetup";
import { useAuthStore } from "@/stores/authStore";
const snapshot = { etag: `"${"a".repeat(64)}"`, connections: [] };
beforeEach(() => useAuthStore.setState({ status: "logged-in", token: "synthetic-only", username: "synthetic", sessionGeneration: 1 }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function input(label: string, value: string) { fireEvent.change(screen.getByLabelText(label), { target: { value } }); }
it("clears a transient credential when a retained app is hidden and does not restore it", async () => {
  const onChanged = vi.fn(); const onRefresh = vi.fn();
  const view = (mode: "visible" | "hidden") => <Activity mode={mode}><ServiceConnectionSetup snapshot={snapshot} unavailable={false} onChanged={onChanged} onRefresh={onRefresh} /></Activity>;
  const mounted = render(view("visible"));
  fireEvent.click(screen.getByRole("button", { name: "Add service connection" }));
  input("Connection provider", "llm:openai"); input("Connection authentication", "api_key"); input("Credential action", "replace"); input("Connection credential", "synthetic-only");
  const field = screen.getByLabelText("Connection credential");
  expect(field).toHaveValue("synthetic-only");
  await act(async () => { mounted.rerender(view("hidden")); });
  expect(field instanceof HTMLInputElement && field.value.length === 0).toBe(true);
  await act(async () => { mounted.rerender(view("visible")); });
  expect(screen.getByLabelText("Connection credential")).toHaveValue("");
  expect(onChanged).not.toHaveBeenCalled();
});
it("does not send an empty credential or enable defaults while preparing a binding", async () => {
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  render(<ServiceConnectionSetup snapshot={snapshot} unavailable={false} onChanged={vi.fn()} onRefresh={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Add service connection" }));
  expect(screen.getByLabelText("Connection provider")).toHaveValue("");
  expect(screen.getByLabelText("Connection model")).toHaveValue("");
  input("Connection provider", "llm:openai"); input("Connection label", "Synthetic"); input("Connection authentication", "api_key"); input("Credential action", "replace");
  fireEvent.click(screen.getByRole("button", { name: "Create configuration" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Enter a credential");
  expect(fetch.mock.calls.length).toBe(0);
  expect(screen.getByLabelText("Connection credential")).toHaveValue("");
});
