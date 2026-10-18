import { config } from "zod";

/** Use Zod's interpreted validator under the installed core's no-eval CSP.
 * Must run before importing modules that construct schemas: Zod snapshots the
 * JIT setting and probes Function during object construction, not first parse.
 * A named call keeps this bootstrap alive in side-effect-pruned public builds.
 */
export function initialiseSchemaValidation(): void {
  config({ jitless: true });
}
