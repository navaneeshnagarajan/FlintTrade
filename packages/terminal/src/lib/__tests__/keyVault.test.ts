import { describe, it, expect, beforeEach } from "vitest";
import { obfuscate, deobfuscate } from "../keyVault";

/**
 * keyVault unit tests.
 *
 * jsdom (used by Vitest) exposes `sessionStorage` and `crypto.getRandomValues`,
 * so no additional mocking is required for these tests.
 */

describe("keyVault", () => {
  beforeEach(() => {
    // Start each test with a clean session so a fresh pad is generated.
    sessionStorage.clear();
  });

  describe("obfuscate", () => {
    it("returns an empty string for empty input", () => {
      expect(obfuscate("")).toBe("");
    });

    it("returns a non-empty hex string for non-empty input", () => {
      const result = obfuscate("hello");
      expect(result).not.toBe("");
      // Each char becomes a 4-hex-digit word → total length = input.length * 4
      expect(result).toHaveLength(5 * 4);
    });

    it("produces only lowercase hex characters", () => {
      const result = obfuscate("TestKey123");
      expect(result).toMatch(/^[0-9a-f]+$/);
    });

    it("does not equal the plaintext", () => {
      const key = "my-secret-api-key";
      expect(obfuscate(key)).not.toBe(key);
    });

    it("produces the same ciphertext for the same key in the same session", () => {
      const key = "stable-within-session";
      expect(obfuscate(key)).toBe(obfuscate(key));
    });

    it("produces different ciphertext across sessions (different pads)", () => {
      const key = "cross-session-test";
      const first = obfuscate(key);

      // Reset the session pad to simulate a new browser session.
      sessionStorage.clear();

      const second = obfuscate(key);
      // With overwhelming probability the two random pads differ.
      expect(first).not.toBe(second);
    });
  });

  describe("deobfuscate", () => {
    it("returns an empty string for empty input", () => {
      expect(deobfuscate("")).toBe("");
    });

    it("round-trips a simple ASCII string", () => {
      const original = "hello";
      expect(deobfuscate(obfuscate(original))).toBe(original);
    });

    it("round-trips a realistic API key string", () => {
      const apiKey = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4";
      expect(deobfuscate(obfuscate(apiKey))).toBe(apiKey);
    });

    it("round-trips a string longer than the 64-byte pad (tests wrapping)", () => {
      // Pad is 128 hex chars = 64 bytes. Use a string that forces wrap-around.
      const long = "x".repeat(200);
      expect(deobfuscate(obfuscate(long))).toBe(long);
    });

    it("round-trips a string with special characters", () => {
      const special = "key!@#$%^&*()_+-=[]{}|;':\",./<>?";
      expect(deobfuscate(obfuscate(special))).toBe(special);
    });

    it("round-trips a Unicode string", () => {
      const unicode = "key-\u20B9-rupee-\u0041";
      expect(deobfuscate(obfuscate(unicode))).toBe(unicode);
    });
  });

  describe("session isolation", () => {
    it("obfuscate and deobfuscate are consistent within one session", () => {
      const values = ["key1", "key2", "key3"];
      for (const v of values) {
        expect(deobfuscate(obfuscate(v))).toBe(v);
      }
    });

    it("deobfuscate fails to recover plaintext after pad is cleared", () => {
      const original = "sensitive-key";
      const encoded = obfuscate(original);

      // Simulate new session — pad is wiped, a new random one is created.
      sessionStorage.clear();

      // The new pad will (almost certainly) differ, producing garbage output.
      const recovered = deobfuscate(encoded);
      expect(recovered).not.toBe(original);
    });
  });
});
