/**
 * Decide whether the official Reticle Vite plugin should inject connect().
 *
 * Playwright CI has no Reticle daemon. The plugin's default inject opens
 * ws://127.0.0.1:4400/reticle; connection-refused console errors then fail the
 * fail-closed fixture registry. No-op unless a daemon is already listening.
 *
 * Lives under `src/` so `tsc --noEmit` (app tsconfig) can typecheck tests that
 * import it. Vite config imports the same module; it is not part of the SPA
 * entry graph.
 */
import { spawnSync } from "node:child_process";

export const RETICLE_BRIDGE_HOST = "127.0.0.1";
export const RETICLE_BRIDGE_PORT_DEFAULT = 4400;

export type ReticleDaemonProbe = (host: string, port: number) => boolean;

export type ReticleConnectDecisionInput = {
  env?: NodeJS.ProcessEnv;
  isDaemonListening?: ReticleDaemonProbe;
};

function parseConnectOff(raw: string | undefined): boolean {
  if (raw === undefined) {
    return false;
  }
  const normalised = raw.trim().toLowerCase();
  return normalised === "0" || normalised === "false" || normalised === "off" || normalised === "no";
}

export function reticleBridgePort(env: NodeJS.ProcessEnv = process.env): number {
  const raw = env.RETICLE_PORT ?? env.VITE_RETICLE_PORT;
  const parsed = raw === undefined ? Number.NaN : Number.parseInt(raw, 10);
  return Number.isInteger(parsed) && parsed > 0 && parsed <= 65535
    ? parsed
    : RETICLE_BRIDGE_PORT_DEFAULT;
}

/**
 * Probe the Reticle bridge with a short-lived Node TCP client.
 *
 * Kept synchronous so `vite.config.ts` can stay a plain object. Windows and
 * POSIX both have `process.execPath`; do not use `/dev/tcp`.
 */
export function isReticleDaemonListening(
  host: string = RETICLE_BRIDGE_HOST,
  port: number = RETICLE_BRIDGE_PORT_DEFAULT,
  timeoutMs = 150,
): boolean {
  const script = `
    const net = require("net");
    const socket = net.connect({ host: ${JSON.stringify(host)}, port: ${JSON.stringify(port)} });
    const done = (code) => {
      try { socket.destroy(); } catch {}
      process.exit(code);
    };
    socket.setTimeout(${timeoutMs}, () => done(1));
    socket.once("connect", () => done(0));
    socket.once("error", () => done(1));
  `;
  const result = spawnSync(process.execPath, ["-e", script], {
    timeout: timeoutMs + 200,
    stdio: "ignore",
  });
  return result.status === 0;
}

export function shouldInjectReticleConnect(input: ReticleConnectDecisionInput = {}): boolean {
  const env = input.env ?? process.env;
  if (parseConnectOff(env.RETICLE_CONNECT)) {
    return false;
  }
  const probe: ReticleDaemonProbe = input.isDaemonListening ?? isReticleDaemonListening;
  return probe(RETICLE_BRIDGE_HOST, reticleBridgePort(env));
}
