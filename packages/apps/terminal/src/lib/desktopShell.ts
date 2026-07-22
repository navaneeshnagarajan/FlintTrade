/**
 * Typed renderer seam for the optional Electron desktop bridge.
 *
 * Electron exposes named capabilities only. A normal browser has no bridge;
 * desktop-only methods reject clearly while external links retain normal web
 * behaviour.
 */

export type BootstrapStatus = "idle" | "running" | "ready" | "failed";
export type BootstrapPhase =
  | "idle"
  | "preparing"
  | "checking-source"
  | "cloning-source"
  | "installing-tools"
  | "syncing-python"
  | "syncing-javascript"
  | "building-terminal"
  | "starting-backend"
  | "cancelled"
  | "complete"
  | "failed";

export interface BootstrapSnapshot {
  attempt: number;
  failure: string | null;
  heartbeatAt: number;
  message: string;
  phase: BootstrapPhase;
  progress: number | null;
  status: BootstrapStatus;
}

export interface BackendState {
  port: number | null;
  status: "stopped" | "starting" | "ready" | "failed";
  url: string | null;
}

export type UpdateKind = "source" | "shell";
export type UpdateStatus =
  | "idle"
  | "checking"
  | "unavailable"
  | "available"
  | "applying"
  | "complete"
  | "failed";

export interface UpdateSnapshot {
  attempt: number;
  currentVersion: string | null;
  failure: string | null;
  heartbeatAt: number;
  kind: UpdateKind;
  message: string;
  progress: number | null;
  status: UpdateStatus;
  version: string | null;
}

export interface FlintDesktopApi {
  applyShellUpdate(): Promise<Readonly<UpdateSnapshot>>;
  applySourceUpdate(): Promise<Readonly<UpdateSnapshot>>;
  cancelBootstrap(): Promise<boolean>;
  checkShellUpdate(): Promise<Readonly<UpdateSnapshot>>;
  checkSourceUpdate(): Promise<Readonly<UpdateSnapshot>>;
  getBackendState(): Promise<Readonly<BackendState>>;
  getBootstrapSnapshot(): Promise<Readonly<BootstrapSnapshot>>;
  getUpdateState(kind: UpdateKind): Promise<Readonly<UpdateSnapshot>>;
  onBackendEvent(callback: (snapshot: Readonly<BackendState>) => void): () => void;
  onBootstrapEvent(callback: (snapshot: Readonly<BootstrapSnapshot>) => void): () => void;
  onUpdateProgress(callback: (snapshot: Readonly<UpdateSnapshot>) => void): () => void;
  openExternal(url: string): Promise<void>;
  quitAfterBackendFailure(): Promise<void>;
  retryBootstrap(): Promise<boolean>;
  window: {
    hide(): Promise<void>;
    quit(): Promise<void>;
    show(): Promise<void>;
  };
}

declare global {
  interface Window {
    flintDesktop?: FlintDesktopApi;
  }
}

function desktopBridge(): FlintDesktopApi | null {
  return window.flintDesktop ?? null;
}

function requireDesktopBridge(): FlintDesktopApi {
  const bridge = desktopBridge();
  if (!bridge) {
    throw new Error("The FlintTrade desktop bridge is unavailable outside the desktop app.");
  }
  return bridge;
}

/** Whether the terminal is running inside the FlintTrade Electron shell. */
export function isDesktopShell(): boolean {
  return desktopBridge() !== null;
}

/** Open an external URL through Electron or a normal browser tab. */
export async function openExternalUrl(url: string): Promise<void> {
  const bridge = desktopBridge();
  if (bridge) {
    await bridge.openExternal(url);
    return;
  }
  window.open(url, "_blank", "noopener");
}

export async function getBootstrapSnapshot(): Promise<Readonly<BootstrapSnapshot>> {
  return requireDesktopBridge().getBootstrapSnapshot();
}

export async function retryBootstrap(): Promise<boolean> {
  return requireDesktopBridge().retryBootstrap();
}

export async function cancelBootstrap(): Promise<boolean> {
  return requireDesktopBridge().cancelBootstrap();
}

export async function getBackendState(): Promise<Readonly<BackendState>> {
  return requireDesktopBridge().getBackendState();
}

export async function getUpdateState(kind: UpdateKind): Promise<Readonly<UpdateSnapshot>> {
  return requireDesktopBridge().getUpdateState(kind);
}

export async function checkSourceUpdate(): Promise<Readonly<UpdateSnapshot>> {
  return requireDesktopBridge().checkSourceUpdate();
}

export async function applySourceUpdate(): Promise<Readonly<UpdateSnapshot>> {
  return requireDesktopBridge().applySourceUpdate();
}

export async function checkShellUpdate(): Promise<Readonly<UpdateSnapshot>> {
  return requireDesktopBridge().checkShellUpdate();
}

export async function applyShellUpdate(): Promise<Readonly<UpdateSnapshot>> {
  return requireDesktopBridge().applyShellUpdate();
}

export function onBootstrapEvent(callback: (snapshot: Readonly<BootstrapSnapshot>) => void): () => void {
  return requireDesktopBridge().onBootstrapEvent(callback);
}

export function onBackendEvent(callback: (snapshot: Readonly<BackendState>) => void): () => void {
  return requireDesktopBridge().onBackendEvent(callback);
}

export function onUpdateProgress(callback: (snapshot: Readonly<UpdateSnapshot>) => void): () => void {
  return requireDesktopBridge().onUpdateProgress(callback);
}

export async function quitAfterBackendFailure(): Promise<void> {
  return requireDesktopBridge().quitAfterBackendFailure();
}

export async function hideDesktopWindow(): Promise<void> {
  return requireDesktopBridge().window.hide();
}

export async function showDesktopWindow(): Promise<void> {
  return requireDesktopBridge().window.show();
}

export async function quitDesktopApp(): Promise<void> {
  return requireDesktopBridge().window.quit();
}
