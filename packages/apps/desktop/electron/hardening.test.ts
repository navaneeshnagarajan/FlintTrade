import { describe, expect, it, vi } from "vitest";

import {
  buildSecureWebPreferences,
  hardenWebContents,
  installSessionHardening,
  isSafeExternalUrl,
} from "./hardening";

interface PreventableEvent {
  preventDefault(): void;
}

function event(): PreventableEvent {
  return { preventDefault: vi.fn() };
}

function fakeWebContents(initialUrl = "http://127.0.0.1:43127/") {
  const listeners = new Map<string, (...args: never[]) => void>();
  let openHandler: ((details: { url: string }) => { action: "deny" }) | undefined;
  const contents = {
    closeDevTools: vi.fn(),
    getURL: () => initialUrl,
    on: vi.fn((name: string, listener: (...args: never[]) => void) => {
      listeners.set(name, listener);
      return contents;
    }),
    setWindowOpenHandler: vi.fn((handler: (details: { url: string }) => { action: "deny" }) => {
      openHandler = handler;
    }),
  };
  return {
    contents,
    emit(name: string, ...args: unknown[]) {
      listeners.get(name)?.(...(args as never[]));
    },
    open(url: string) {
      if (!openHandler) throw new Error("window-open handler was not installed");
      return openHandler({ url });
    },
  };
}

describe("BrowserWindow security defaults", () => {
  it("enables isolation and sandboxing while disabling Node and production DevTools", () => {
    expect(buildSecureWebPreferences("/app/dist/electron-preload.js", false)).toMatchObject({
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webviewTag: false,
      devTools: false,
      preload: "/app/dist/electron-preload.js",
    });
  });
});

describe("session hardening", () => {
  it("denies permission checks, permission requests and downloads", () => {
    let permissionCheck: (() => boolean) | undefined;
    let permissionRequest: ((_webContents: unknown, _permission: string, callback: (allowed: boolean) => void) => void) | undefined;
    let downloadListener: ((_event: PreventableEvent) => void) | undefined;
    const session = {
      on: vi.fn((name: string, listener: (_event: PreventableEvent) => void) => {
        if (name === "will-download") downloadListener = listener;
        return session;
      }),
      setPermissionCheckHandler: vi.fn((handler: () => boolean) => {
        permissionCheck = handler;
      }),
      setPermissionRequestHandler: vi.fn(
        (handler: (_webContents: unknown, _permission: string, callback: (allowed: boolean) => void) => void) => {
          permissionRequest = handler;
        },
      ),
    };

    installSessionHardening(session);

    expect(permissionCheck?.()).toBe(false);
    const callback = vi.fn();
    permissionRequest?.(undefined, "notifications", callback);
    expect(callback).toHaveBeenCalledWith(false);
    const downloadEvent = event();
    downloadListener?.(downloadEvent);
    expect(downloadEvent.preventDefault).toHaveBeenCalledOnce();
  });
});

describe("webContents confinement", () => {
  it("reads the currently selected loopback origin for each navigation", () => {
    let terminalOrigin: string | null = null;
    const fake = fakeWebContents();
    hardenWebContents(fake.contents, {
      development: false,
      openExternal: vi.fn(),
      originPolicy: () => ({
        splashUrl: "file:///Applications/FlintTrade/resources/app.asar/splash/index.html",
        terminalOrigin,
      }),
    });

    terminalOrigin = "http://127.0.0.1:43127";
    const allowed = event();
    fake.emit("will-navigate", allowed, "http://127.0.0.1:43127/settings");
    expect(allowed.preventDefault).not.toHaveBeenCalled();
  });

  it("keeps same-origin loopback navigation and blocks every other navigation", async () => {
    const openExternal = vi.fn(async () => undefined);
    const fake = fakeWebContents();
    hardenWebContents(fake.contents, {
      development: false,
      openExternal,
      originPolicy: {
        splashUrl: "file:///Applications/FlintTrade/resources/app.asar/splash/index.html",
        terminalOrigin: "http://127.0.0.1:43127",
      },
    });

    const allowed = event();
    fake.emit("will-navigate", allowed, "http://127.0.0.1:43127/settings");
    expect(allowed.preventDefault).not.toHaveBeenCalled();

    const blocked = event();
    fake.emit("will-navigate", blocked, "http://127.0.0.1:43128/settings");
    expect(blocked.preventDefault).toHaveBeenCalledOnce();

    const external = event();
    fake.emit("will-redirect", external, "https://flinttrade.app/help");
    expect(external.preventDefault).toHaveBeenCalledOnce();
    await Promise.resolve();
    expect(openExternal).toHaveBeenCalledWith("https://flinttrade.app/help");
  });

  it("denies child windows and webviews", async () => {
    const openExternal = vi.fn(async () => undefined);
    const fake = fakeWebContents();
    hardenWebContents(fake.contents, {
      development: false,
      openExternal,
      originPolicy: {
        splashUrl: "file:///Applications/FlintTrade/resources/app.asar/splash/index.html",
        terminalOrigin: "http://127.0.0.1:43127",
      },
    });

    expect(fake.open("http://127.0.0.1:43127/orders")).toEqual({ action: "deny" });
    expect(fake.open("https://flinttrade.app/docs")).toEqual({ action: "deny" });
    await Promise.resolve();
    expect(openExternal).toHaveBeenCalledWith("https://flinttrade.app/docs");

    const webview = event();
    fake.emit("will-attach-webview", webview);
    expect(webview.preventDefault).toHaveBeenCalledOnce();
  });

  it("confines subframe navigation to the trusted origin and hands external subframe targets to the browser", async () => {
    const openExternal = vi.fn(async () => undefined);
    const fake = fakeWebContents();
    hardenWebContents(fake.contents, {
      development: false,
      openExternal,
      originPolicy: {
        splashUrl: "file:///Applications/FlintTrade/resources/app.asar/splash/index.html",
        terminalOrigin: "http://127.0.0.1:43127",
      },
    });

    const sameOrigin = { ...event(), isMainFrame: false, url: "http://127.0.0.1:43127/orders" };
    fake.emit("will-frame-navigate", sameOrigin);
    expect(sameOrigin.preventDefault).not.toHaveBeenCalled();

    const externalFrame = { ...event(), isMainFrame: false, url: "https://flinttrade.app/help" };
    fake.emit("will-frame-navigate", externalFrame);
    expect(externalFrame.preventDefault).toHaveBeenCalledOnce();
    await Promise.resolve();
    expect(openExternal).toHaveBeenCalledWith("https://flinttrade.app/help");

    // The main frame is already confined by will-navigate; will-frame-navigate must not double-handle it.
    openExternal.mockClear();
    const mainFrame = { ...event(), isMainFrame: true, url: "https://flinttrade.app/help" };
    fake.emit("will-frame-navigate", mainFrame);
    expect(mainFrame.preventDefault).not.toHaveBeenCalled();
    expect(openExternal).not.toHaveBeenCalled();
  });

  it("closes production DevTools and accepts only parseable HTTPS external URLs", () => {
    const fake = fakeWebContents();
    hardenWebContents(fake.contents, {
      development: false,
      openExternal: vi.fn(),
      originPolicy: {
        splashUrl: "file:///Applications/FlintTrade/resources/app.asar/splash/index.html",
        terminalOrigin: null,
      },
    });
    fake.emit("devtools-opened");
    expect(fake.contents.closeDevTools).toHaveBeenCalledOnce();
    expect(isSafeExternalUrl("https://flinttrade.app/docs")).toBe(true);
    expect(isSafeExternalUrl("http://flinttrade.app/docs")).toBe(false);
    expect(isSafeExternalUrl("not a URL")).toBe(false);
  });
});
