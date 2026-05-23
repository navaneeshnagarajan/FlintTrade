/**
 * Tests for useVoiceAlert hook.
 *
 * Verifies:
 *   1. When voice_alerts is enabled, speak/announceOrder/announceAlert
 *      call speechSynthesis.speak with the correct utterance.
 *   2. When voice_alerts is disabled (default), all functions are silent.
 *   3. announceOrder formats BUY and SELL text correctly.
 *   4. speak cancels previous utterances before starting a new one.
 *   5. speak ignores empty / whitespace-only strings.
 *   6. speak forwards rate and pitch options to the utterance.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

// ---------------------------------------------------------------------------
// settingsStore mock — controls voice_alerts preference
// ---------------------------------------------------------------------------

let voiceAlertsEnabled = false;

vi.mock("@/stores/settingsStore", () => ({
  useSettingsStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({ voice_alerts: voiceAlertsEnabled }),
}));

// ---------------------------------------------------------------------------
// speechSynthesis mock — installed globally so _isSupported evaluates true
// ---------------------------------------------------------------------------

const mockSpeak  = vi.fn();
const mockCancel = vi.fn();

// Install before any module evaluation so `_isSupported` detects the API.
Object.defineProperty(window, "speechSynthesis", {
  configurable: true,
  writable: true,
  value: { speak: mockSpeak, cancel: mockCancel },
});

// Minimal SpeechSynthesisUtterance shim
class MockUtterance {
  text: string;
  rate = 1.0;
  pitch = 1.0;
  volume = 1.0;
  lang = "en-IN";
  constructor(text: string) {
    this.text = text;
  }
}
(window as unknown as Record<string, unknown>).SpeechSynthesisUtterance =
  MockUtterance;

// Import the hook AFTER the window mock is in place.
import { useVoiceAlert } from "../useVoiceAlert";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useVoiceAlert", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // -- isSupported ----------------------------------------------------------

  it("reports isSupported true when speechSynthesis is available", () => {
    const { result } = renderHook(() => useVoiceAlert());
    expect(result.current.isSupported).toBe(true);
  });

  // -- voice_alerts disabled (default) -------------------------------------

  it("speak is a no-op when voice_alerts is disabled", () => {
    voiceAlertsEnabled = false;
    const { result } = renderHook(() => useVoiceAlert());
    act(() => { result.current.speak("test message"); });
    expect(mockSpeak).not.toHaveBeenCalled();
  });

  it("announceOrder is a no-op when voice_alerts is disabled", () => {
    voiceAlertsEnabled = false;
    const { result } = renderHook(() => useVoiceAlert());
    act(() => { result.current.announceOrder("BUY", "NIFTY", 50); });
    expect(mockSpeak).not.toHaveBeenCalled();
  });

  it("announceAlert is a no-op when voice_alerts is disabled", () => {
    voiceAlertsEnabled = false;
    const { result } = renderHook(() => useVoiceAlert());
    act(() => { result.current.announceAlert("NIFTY crossed 22000"); });
    expect(mockSpeak).not.toHaveBeenCalled();
  });

  // -- voice_alerts enabled ------------------------------------------------

  it("speak calls speechSynthesis.speak when voice_alerts is enabled", () => {
    voiceAlertsEnabled = true;
    const { result } = renderHook(() => useVoiceAlert());
    act(() => { result.current.speak("Hello trader"); });
    expect(mockSpeak).toHaveBeenCalledOnce();
    const utterance = mockSpeak.mock.calls[0][0] as MockUtterance;
    expect(utterance.text).toBe("Hello trader");
  });

  it("speak cancels any previous utterance before starting a new one", () => {
    voiceAlertsEnabled = true;
    const { result } = renderHook(() => useVoiceAlert());
    act(() => {
      result.current.speak("first");
      result.current.speak("second");
    });
    // cancel() must be called once per speak() call
    expect(mockCancel).toHaveBeenCalledTimes(2);
    expect(mockSpeak).toHaveBeenCalledTimes(2);
  });

  it("announceOrder formats BUY text correctly", () => {
    voiceAlertsEnabled = true;
    const { result } = renderHook(() => useVoiceAlert());
    act(() => { result.current.announceOrder("BUY", "NIFTY", 50); });
    const utterance = mockSpeak.mock.calls[0][0] as MockUtterance;
    expect(utterance.text).toMatch(/Buy/i);
    expect(utterance.text).toMatch(/50/);
    expect(utterance.text).toMatch(/NIFTY/);
  });

  it("announceOrder formats SELL text correctly", () => {
    voiceAlertsEnabled = true;
    const { result } = renderHook(() => useVoiceAlert());
    act(() => { result.current.announceOrder("SELL", "BANKNIFTY", 25); });
    const utterance = mockSpeak.mock.calls[0][0] as MockUtterance;
    expect(utterance.text).toMatch(/Sell/i);
    expect(utterance.text).toMatch(/25/);
    expect(utterance.text).toMatch(/BANKNIFTY/);
  });

  it("announceAlert speaks the exact message", () => {
    voiceAlertsEnabled = true;
    const { result } = renderHook(() => useVoiceAlert());
    const msg = "NIFTY has crossed above 22000";
    act(() => { result.current.announceAlert(msg); });
    const utterance = mockSpeak.mock.calls[0][0] as MockUtterance;
    expect(utterance.text).toBe(msg);
  });

  it("speak ignores empty and whitespace-only strings", () => {
    voiceAlertsEnabled = true;
    const { result } = renderHook(() => useVoiceAlert());
    act(() => {
      result.current.speak("");
      result.current.speak("   ");
    });
    expect(mockSpeak).not.toHaveBeenCalled();
  });

  it("speak forwards rate and pitch options to the utterance", () => {
    voiceAlertsEnabled = true;
    const { result } = renderHook(() => useVoiceAlert());
    act(() => { result.current.speak("fast", { rate: 1.5, pitch: 0.8 }); });
    const utterance = mockSpeak.mock.calls[0][0] as MockUtterance;
    expect(utterance.rate).toBe(1.5);
    expect(utterance.pitch).toBe(0.8);
  });

  it("speak defaults rate and pitch to 1.0 when not specified", () => {
    voiceAlertsEnabled = true;
    const { result } = renderHook(() => useVoiceAlert());
    act(() => { result.current.speak("default settings"); });
    const utterance = mockSpeak.mock.calls[0][0] as MockUtterance;
    expect(utterance.rate).toBe(1.0);
    expect(utterance.pitch).toBe(1.0);
  });

  it("returned functions are stable across re-renders when supported", () => {
    // Callbacks wrapped in useCallback with no deps — must be referentially
    // stable as long as speechSynthesis remains available (isSupported=true).
    voiceAlertsEnabled = true;
    const { result, rerender } = renderHook(() => useVoiceAlert());
    expect(result.current.isSupported).toBe(true);
    const { speak: s1, announceOrder: a1, announceAlert: al1 } = result.current;
    rerender();
    const { speak: s2, announceOrder: a2, announceAlert: al2 } = result.current;
    expect(s1).toBe(s2);
    expect(a1).toBe(a2);
    expect(al1).toBe(al2);
  });
});
