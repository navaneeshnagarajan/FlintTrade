import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useVoiceInput } from "../useVoiceInput";

type Recognition = InstanceType<NonNullable<typeof window.SpeechRecognition>>;
class Recogniser extends EventTarget implements Recognition {
  continuous = false;
  interimResults = false;
  lang = "";
  maxAlternatives = 1;
  onresult: Recognition["onresult"] = null;
  onerror: Recognition["onerror"] = null;
  onend: Recognition["onend"] = null;
  onstart: Recognition["onstart"] = null;
  start = vi.fn(() => this.onstart?.());
  stop = vi.fn();
  abort = vi.fn();
  static latest: Recogniser;
  constructor() { super(); Recogniser.latest = this; }
  result(text: string, final = true) {
    const result = Object.assign([{ transcript: text, confidence: 1 }], { isFinal: final });
    this.onresult?.({ resultIndex: 0, results: [result] } as unknown as Parameters<NonNullable<Recognition["onresult"]>>[0]);
  }
}

beforeEach(() => {
  vi.stubGlobal("SpeechRecognition", Recogniser);
  vi.stubGlobal("webkitSpeechRecognition", undefined);
});
afterEach(() => vi.unstubAllGlobals());

describe("conversation speech capture", () => {
  it("captures only final speech into the draft callback after an explicit start", () => {
    const onResult = vi.fn();
    const { result } = renderHook(() => useVoiceInput({ onResult, interimResults: true }));
    expect(onResult).not.toHaveBeenCalled();
    act(() => result.current.startListening());
    expect(result.current.isListening).toBe(true);
    expect(Recogniser.latest.lang).toBe("en-IN");
    act(() => Recogniser.latest.result("Buy one", false));
    expect(result.current.transcript).toBe("Buy one");
    expect(onResult).not.toHaveBeenCalled();
    act(() => Recogniser.latest.result("Buy one RELIANCE"));
    expect(onResult).toHaveBeenCalledExactlyOnceWith("Buy one RELIANCE");
  });

  it("does not accept a late result after abort or unmount", () => {
    const onResult = vi.fn();
    const { result, unmount } = renderHook(() => useVoiceInput({ onResult }));
    act(() => result.current.startListening());
    const recogniser = Recogniser.latest;
    act(() => result.current.abort());
    act(() => recogniser.result("Late order phrase"));
    expect(onResult).not.toHaveBeenCalled();
    act(() => result.current.startListening());
    const replacement = Recogniser.latest;
    recogniser.result("Previous session late result");
    expect(onResult).not.toHaveBeenCalled();
    unmount();
    replacement.result("After unmount");
    expect(onResult).not.toHaveBeenCalled();
    expect(recogniser.abort).toHaveBeenCalledOnce();
    expect(replacement.abort).toHaveBeenCalledOnce();
  });

  it("reports denied microphone access and stops listening", () => {
    const onError = vi.fn();
    const { result } = renderHook(() => useVoiceInput({ onError }));
    act(() => result.current.startListening());
    act(() => Recogniser.latest.onerror?.({ error: "not-allowed", message: "" } as unknown as Parameters<NonNullable<Recognition["onerror"]>>[0]));
    expect(onError).toHaveBeenCalledExactlyOnceWith("not-allowed");
    expect(result.current.isListening).toBe(false);
  });

  it("returns unavailable controls when recognition is unsupported", () => {
    vi.stubGlobal("SpeechRecognition", undefined);
    const { result } = renderHook(() => useVoiceInput());
    expect(result.current.isSupported).toBe(false);
    act(() => result.current.startListening());
    expect(result.current.isListening).toBe(false);
  });
});
