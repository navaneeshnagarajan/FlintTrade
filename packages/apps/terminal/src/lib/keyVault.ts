/**
 * Lightweight key obfuscation for sessionStorage.
 *
 * NOT encryption — this is XOR obfuscation with a per-session random pad.
 * Prevents casual reading of the API key from DevTools / storage inspectors.
 * An attacker with JavaScript execution on the same origin can still recover
 * the key by reading the pad from sessionStorage alongside the ciphertext.
 * For real security, use HTTP-only cookies or a server-side session.
 *
 * The pad is 64 random bytes (128 hex chars), generated once per browser
 * session and stored under a separate sessionStorage key. The obfuscated
 * value is hex-encoded XOR of the plaintext chars against the pad.
 */

const PAD_STORAGE_KEY = "flinttrade:kp";

/**
 * Retrieve the existing per-session pad or create and store a fresh one.
 * The pad persists only for the lifetime of the browser tab (sessionStorage).
 */
function getOrCreatePad(): string {
  let pad = sessionStorage.getItem(PAD_STORAGE_KEY);
  if (!pad) {
    const bytes = crypto.getRandomValues(new Uint8Array(64));
    pad = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
    sessionStorage.setItem(PAD_STORAGE_KEY, pad);
  }
  return pad;
}

/**
 * XOR-obfuscate a plaintext string using the per-session pad.
 * Each character code is XOR'd against the corresponding pad character code
 * (wrapping via modulo) and encoded as a 4-character lowercase hex word.
 *
 * @param plaintext - The raw string to obfuscate (e.g. an API key).
 * @returns Hex-encoded obfuscated string, or empty string for empty input.
 */
export function obfuscate(plaintext: string): string {
  if (plaintext === "") return "";
  const pad = getOrCreatePad();
  const result: string[] = [];
  for (let i = 0; i < plaintext.length; i++) {
    const charCode = plaintext.charCodeAt(i) ^ pad.charCodeAt(i % pad.length);
    result.push(charCode.toString(16).padStart(4, "0"));
  }
  return result.join("");
}

/**
 * Reverse the obfuscation applied by {@link obfuscate}.
 * Reads the same per-session pad from sessionStorage and XOR-decodes the
 * hex-encoded input back to the original plaintext.
 *
 * @param encoded - The hex-encoded obfuscated string produced by `obfuscate`.
 * @returns The original plaintext string, or empty string for empty input.
 */
export function deobfuscate(encoded: string): string {
  if (encoded === "") return "";
  const pad = getOrCreatePad();
  const result: string[] = [];
  for (let i = 0; i < encoded.length; i += 4) {
    const charCode =
      parseInt(encoded.slice(i, i + 4), 16) ^
      pad.charCodeAt((i / 4) % pad.length);
    result.push(String.fromCharCode(charCode));
  }
  return result.join("");
}
