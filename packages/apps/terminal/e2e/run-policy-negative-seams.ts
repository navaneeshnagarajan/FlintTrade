import type { Page } from "@playwright/test";

/** One declared transport-corruption negative; never a healthy relay. */
export function exactAcknowledgementCorruption(path: string) {
  if (!/^\/v1\/model-runs\/[A-Za-z0-9_-]+\/configuration\/confirm$/.test(path)) throw new Error("Exact policy confirmation required");
  let uses = 0;
  return {
    apply(method: string, actual: string, status: number, original: string) {
      if (method !== "POST" || actual !== path || status !== 200 || uses !== 0) throw new Error("ACK fault scope/count refused");
      const decoded: unknown = JSON.parse(original);
      if (!decoded || typeof decoded !== "object" || !("scope" in decoded) || !decoded.scope || typeof decoded.scope !== "object" || !("run_id" in decoded.scope) || typeof decoded.scope.run_id !== "string") throw new Error("Original core ACK required");
      uses++;
      // Corrupt exactly the target identity, retaining original bytes separately.
      decoded.scope.run_id = "transport-corrupted-run";
      return JSON.stringify(decoded);
    },
    assertUsed() { if (uses !== 1) throw new Error("ACK fault must be used exactly once"); },
  };
}

export interface DecodedObservation {
  path: string;
  entered: number;
  delivered: number;
  decodedAt?: number;
  deliveredAt?: number;
  originalText?: string;
  decodedBefore?: string;
  decodedAfter?: string;
  sameReference?: boolean;
  failures: string[];
}
interface DecodedController { observation(): DecodedObservation; release(): void; restore(): void }
declare global { interface Window { __runPolicyDecodedHold?: DecodedController } }

/** Hold a real native json() result, not fetch, a decoder, or a fabricated DTO. */
export async function installDecodedReadHold(page: Page, path: string) {
  if (!/^\/v1\/model-runs\/[A-Za-z0-9_-]+\/configuration(?:\/control\?action=learning-rights&subject=source)?$/.test(path)) throw new Error("Exact policy GET required");
  await page.evaluate(target => {
    if (window.__runPolicyDecodedHold) throw new Error("Decoded scheduling seam already installed");
    const original = Response.prototype.json;
    let release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    const observation: DecodedObservation = { path: target, entered: 0, delivered: 0, failures: [] };
    const replacement = async function (this: Response): Promise<unknown> {
      const url = new URL(this.url);
      if (url.origin !== location.origin || url.pathname + url.search !== target) return original.call(this);
      if (!this.ok || observation.entered !== 0) {
        observation.failures.push("Decoded scheduling scope/count refused");
        throw new Error("Decoded scheduling scope/count refused");
      }
      const copy = this.clone();
      const decoded: unknown = await original.call(this);
      const originalText = await copy.text();
      observation.entered++;
      observation.decodedAt = Date.now();
      observation.originalText = originalText;
      observation.decodedBefore = JSON.stringify(decoded);
      const held = decoded;
      await gate;
      observation.decodedAfter = JSON.stringify(decoded);
      observation.sameReference = held === decoded;
      observation.deliveredAt = Date.now();
      observation.delivered++;
      return decoded;
    };
    Response.prototype.json = replacement;
    window.__runPolicyDecodedHold = {
      observation: () => structuredClone(observation),
      release,
      restore() {
        if (Response.prototype.json !== replacement) throw new Error("Native json owner changed");
        release(); Response.prototype.json = original; delete window.__runPolicyDecodedHold;
      },
    };
  }, path);
  return {
    snapshot: () => page.evaluate(() => window.__runPolicyDecodedHold!.observation()),
    release: () => page.evaluate(() => window.__runPolicyDecodedHold!.release()),
    restore: () => page.evaluate(() => window.__runPolicyDecodedHold!.restore()),
  };
}
