// Adapted from NousResearch/hermes-agent commit 7651764ce (MIT).
import type { WebPreferences } from "electron";

import { classifyRendererUrl, type RendererOriginPolicy } from "./origins";

interface PreventableEvent {
  preventDefault(): void;
}

interface SessionLike {
  on(event: "will-download", listener: (event: PreventableEvent) => void): unknown;
  setPermissionCheckHandler(handler: () => boolean): void;
  setPermissionRequestHandler(
    handler: (webContents: unknown, permission: string, callback: (allowed: boolean) => void) => void,
  ): void;
}

interface ChildWindowLike {
  destroy(): void;
}

interface WebContentsLike {
  closeDevTools(): void;
  getURL(): string;
  on(event: string, listener: (...args: never[]) => void): unknown;
  setWindowOpenHandler(handler: (details: { url: string }) => { action: "deny" }): void;
}

export interface WebContentsHardeningPolicy {
  development: boolean;
  openExternal(url: string): Promise<void> | void;
  originPolicy: RendererOriginPolicy | (() => RendererOriginPolicy);
}

export function buildSecureWebPreferences(preload: string, development: boolean): WebPreferences {
  return {
    contextIsolation: true,
    sandbox: true,
    nodeIntegration: false,
    webviewTag: false,
    devTools: development,
    preload,
  };
}

export function isSafeExternalUrl(rawUrl: string): boolean {
  try {
    return new URL(rawUrl).protocol === "https:";
  } catch {
    return false;
  }
}

function openExternalIfSafe(rawUrl: string, openExternal: (url: string) => Promise<void> | void): void {
  if (!isSafeExternalUrl(rawUrl)) return;
  void Promise.resolve(openExternal(rawUrl)).catch(() => undefined);
}

function isAllowedNavigation(currentUrl: string, targetUrl: string, policy: RendererOriginPolicy): boolean {
  const currentOrigin = classifyRendererUrl(currentUrl, policy);
  if (currentOrigin === "untrusted") return false;
  return classifyRendererUrl(targetUrl, policy) === currentOrigin;
}

export function installSessionHardening(session: SessionLike): void {
  session.setPermissionCheckHandler(() => false);
  session.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false));
  session.on("will-download", (event) => event.preventDefault());
}

export function hardenWebContents(contents: WebContentsLike, policy: WebContentsHardeningPolicy): void {
  const confineNavigation = (event: PreventableEvent, targetUrl: string): void => {
    const currentPolicy = typeof policy.originPolicy === "function" ? policy.originPolicy() : policy.originPolicy;
    if (isAllowedNavigation(contents.getURL(), targetUrl, currentPolicy)) return;
    event.preventDefault();
    openExternalIfSafe(targetUrl, policy.openExternal);
  };

  contents.on("will-navigate", confineNavigation);
  contents.on("will-redirect", confineNavigation);
  contents.on("will-attach-webview", (event: PreventableEvent) => event.preventDefault());
  contents.on("did-create-window", (child: ChildWindowLike) => child.destroy());
  contents.on("devtools-opened", () => {
    if (!policy.development) contents.closeDevTools();
  });
  contents.setWindowOpenHandler(({ url }) => {
    openExternalIfSafe(url, policy.openExternal);
    return { action: "deny" };
  });
}
