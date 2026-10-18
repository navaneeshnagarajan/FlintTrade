import { beforeEach, describe, expect, it } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { NotificationBell } from "../NotificationCentre";
import { emitNotification, useNotificationFeed } from "../useNotificationFeed";
import { clearAll, getSnapshot } from "../notificationStore";

const account = "live:native:dhan:SYNTHETIC-A";
function Harness() { useNotificationFeed(); return <NotificationBell />; }
describe("producer-owned notification disclosure", () => {
  beforeEach(() => { localStorage.clear(); clearAll(); });
  it.each([
    { name: "generic", metadata: { version: 1, kind: "none" } },
    { name: "null", metadata: null },
    { name: "unknown version", metadata: { version: 2, kind: "captured", account } },
    { name: "missing account", metadata: { version: 1, kind: "captured" } },
    { name: "control character", metadata: { version: 1, kind: "captured", account: account + "\u061c" } },
    { name: "unknown own key", metadata: { version: 1, kind: "captured", account, override: true } },
  ])("$name never exposes visible or accessible Origin, but keeps routing", async ({ metadata }) => {
    render(<MemoryRouter><Harness /></MemoryRouter>);
    act(() => {
      window.dispatchEvent(new CustomEvent("flinttrade:notify", { detail: {
        category: "order", title: "Generic notice", body: "Reconcile broker orders.",
        accountScopeKey: account, originDisclosure: metadata, skipAccountRefresh: true,
      } }));
    });
    fireEvent.click(await screen.findByRole("button", { name: /1 unread/ }));
    const article = screen.getByRole("article");
    expect(article).not.toHaveTextContent(/Origin:|SYNTHETIC-A/);
    expect(article).not.toHaveAccessibleName(/Origin:|SYNTHETIC-A/);
    expect(getSnapshot()[0]).toMatchObject({ accountScopeKey: account, originDisclosure: { version: 1, kind: "none" } });
    expect(JSON.parse(localStorage.getItem("flinttrade:notifications")!)[0]).toMatchObject({ accountScopeKey: account, originDisclosure: { version: 1, kind: "none" } });
  });
  it("explicit captured attribution is independent of the routing key and survives a later notice", async () => {
    render(<MemoryRouter><Harness /></MemoryRouter>);
    act(() => {
      emitNotification({ category: "order", title: "Current B", body: "Not a fill.", accountScopeKey: "live:native:dhan:SYNTHETIC-B" });
      window.dispatchEvent(new CustomEvent("flinttrade:notify", { detail: {
        category: "order", title: "Late A", body: "Not a fill.", accountScopeKey: account,
        originDisclosure: { version: 1, kind: "captured", account }, skipAccountRefresh: true,
      } }));
    });
    fireEvent.click(await screen.findByRole("button", { name: /2 unread/ }));
    const article = screen.getByRole("article", { name: /Late A/ });
    expect(article).toHaveTextContent(`Origin: ${account}`);
    expect(article).toHaveAccessibleName(new RegExp(`Origin: ${account}`));
    expect(article).not.toHaveTextContent("SYNTHETIC-B");
  });
});
