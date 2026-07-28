import { describe, expect, it, vi } from "vitest";

import { createDesktopWindows, type DesktopManagedWindow } from "./desktop-windows";

function managedWindow() {
  const listeners = new Map<string, Array<(...args: unknown[]) => void>>();
  let destroyed = false;
  let visible = false;
  const window: DesktopManagedWindow & { emit(event: string, ...args: unknown[]): void } = {
    destroy: vi.fn(() => {
      destroyed = true;
      window.emit("closed");
    }),
    emit(event, ...args) {
      for (const listener of listeners.get(event) ?? []) listener(...args);
    },
    focus: vi.fn(),
    hide: vi.fn(() => { visible = false; }),
    isDestroyed: vi.fn(() => destroyed),
    isMinimised: vi.fn(() => false),
    isVisible: vi.fn(() => visible),
    loadURL: vi.fn(async () => undefined),
    on(event, listener) {
      listeners.set(event, [...(listeners.get(event) ?? []), listener]);
    },
    restore: vi.fn(),
    show: vi.fn(() => { visible = true; }),
  };
  return window;
}

function fixture() {
  const local = managedWindow();
  const remote = managedWindow();
  const terminalOrigins: Array<string | null> = [];
  const onLocalClose = vi.fn();
  const onRemoteClose = vi.fn();
  const onRemoteFailure = vi.fn();
  const createRemote = vi.fn(() => remote);
  const windows = createDesktopWindows({
    createLocal: vi.fn(() => local),
    createRemote,
    localUrl: "flinttrade://splash/index.html",
    onLocalClose,
    onRemoteClose,
    onRemoteFailure,
    setTerminalOrigin: (origin) => terminalOrigins.push(origin),
  });
  return { createRemote, local, onLocalClose, onRemoteClose, onRemoteFailure, remote, terminalOrigins, windows };
}

describe("desktop window identities", () => {
  it("keeps the trusted local recovery and remote terminal as separate windows", async () => {
    const test = fixture();
    await test.windows.showLocal();
    await test.windows.showTerminal(43_210);

    expect(test.local.loadURL).toHaveBeenCalledWith("flinttrade://splash/index.html");
    expect(test.remote.loadURL).toHaveBeenCalledWith("http://127.0.0.1:43210");
    expect(test.local).not.toBe(test.remote);
    expect(test.terminalOrigins).toEqual(["http://127.0.0.1:43210"]);
    expect(test.local.hide).toHaveBeenCalledOnce();
    expect(test.remote.show).toHaveBeenCalledOnce();
  });

  it("revokes remote authority before returning to local recovery", async () => {
    const test = fixture();
    await test.windows.showLocal();
    await test.windows.showTerminal(43_210);

    await test.windows.handleBackendFailure();

    expect(test.terminalOrigins).toEqual(["http://127.0.0.1:43210", null]);
    expect(test.remote.destroy).toHaveBeenCalledOnce();
    expect(test.local.show).toHaveBeenCalledTimes(2);
    expect(test.windows.getPrimaryWindow()).toBe(test.local);
  });

  it("fails closed to the local surface when remote navigation fails", async () => {
    const test = fixture();
    vi.mocked(test.remote.loadURL).mockRejectedValueOnce(new Error("navigation failed"));
    await test.windows.showLocal();

    await expect(test.windows.showTerminal(43_210)).resolves.toBe(false);
    expect(test.terminalOrigins).toEqual(["http://127.0.0.1:43210", null]);
    expect(test.remote.destroy).toHaveBeenCalledOnce();
    expect(test.local.hide).not.toHaveBeenCalled();
    expect(test.onRemoteFailure).toHaveBeenCalledOnce();
  });

  it("revokes authority and recovers locally when remote construction throws", async () => {
    const test = fixture();
    test.createRemote.mockImplementationOnce(() => { throw new Error("window construction failed"); });
    await test.windows.showLocal();

    await expect(test.windows.showTerminal(43_210)).resolves.toBe(false);

    expect(test.terminalOrigins).toEqual(["http://127.0.0.1:43210", null]);
    expect(test.windows.getPrimaryWindow()).toBe(test.local);
    expect(test.onRemoteFailure).toHaveBeenCalledOnce();
  });

  it("keeps the visible local recovery window primary until remote navigation commits", async () => {
    const test = fixture();
    let finishLoad!: () => void;
    vi.mocked(test.remote.loadURL).mockImplementationOnce(() => new Promise<void>((resolve) => {
      finishLoad = resolve;
    }));
    await test.windows.showLocal();

    const loading = test.windows.showTerminal(43_210);
    await vi.waitFor(() => expect(test.remote.loadURL).toHaveBeenCalledOnce(), { timeout: 15_000 });
    expect(test.windows.getPrimaryWindow()).toBe(test.local);
    test.windows.hide();
    expect(test.local.hide).toHaveBeenCalledOnce();
    expect(test.remote.hide).not.toHaveBeenCalled();

    finishLoad();
    await expect(loading).resolves.toBe(true);
    expect(test.windows.getPrimaryWindow()).toBe(test.remote);
  });

  it("delegates remote close and toggles whichever identity is primary", async () => {
    const test = fixture();
    await test.windows.showLocal();
    await test.windows.showTerminal(43_210);
    const closeEvent = { preventDefault: vi.fn() };

    test.remote.emit("close", closeEvent);
    test.windows.toggle();
    test.windows.toggle();

    expect(test.onRemoteClose).toHaveBeenCalledWith(closeEvent);
    expect(test.remote.hide).toHaveBeenCalledOnce();
    expect(test.remote.show).toHaveBeenCalledTimes(2);
  });

  it("delegates local recovery close rather than leaving an inaccessible process", async () => {
    const test = fixture();
    await test.windows.showLocal();
    const closeEvent = { preventDefault: vi.fn() };

    test.local.emit("close", closeEvent);

    expect(test.onLocalClose).toHaveBeenCalledWith(closeEvent);
  });

  it("rejects non-loopback or malformed terminal ports before granting an origin", async () => {
    const test = fixture();

    await expect(test.windows.showTerminal(0)).rejects.toThrow(/port/i);
    await expect(test.windows.showTerminal(65_536)).rejects.toThrow(/port/i);
    expect(test.terminalOrigins).toEqual([]);
    expect(test.remote.loadURL).not.toHaveBeenCalled();
  });
});
