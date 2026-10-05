/**
 * useVoiceInput — Web Speech API hook for dictating AI conversation drafts.
 *
 * Wraps `webkitSpeechRecognition` / `SpeechRecognition` with a clean
 * React interface.  Falls back gracefully when the browser does not
 * support the Speech API (returns `isSupported: false` and no-op
 * handlers).
 *
 * Usage:
 *   const { isListening, isSupported, transcript, startListening, stopListening } =
 *     useVoiceInput({ onResult: (text) => setConversationDraft(text) });
 */

import { useCallback, useEffect, useRef, useState } from "react";

// ---------------------------------------------------------------------------
// Type shim — webkitSpeechRecognition is not in lib.dom.d.ts
// ---------------------------------------------------------------------------

interface SpeechRecognitionEvent extends Event {
  readonly resultIndex: number;
  readonly results: SpeechRecognitionResultList;
}

interface SpeechRecognitionErrorEvent extends Event {
  readonly error: string;
  readonly message: string;
}

interface SpeechRecognitionInstance extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  maxAlternatives: number;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
  onstart: (() => void) | null;
}

declare global {
  interface Window {
    SpeechRecognition?: new () => SpeechRecognitionInstance;
    webkitSpeechRecognition?: new () => SpeechRecognitionInstance;
  }
}

// ---------------------------------------------------------------------------
// Options
// ---------------------------------------------------------------------------

export interface UseVoiceInputOptions {
  /** BCP 47 language tag — defaults to "en-IN" (Indian English). */
  lang?: string;
  /** Whether to stream interim (in-progress) results to `transcript`. */
  interimResults?: boolean;
  /**
   * Callback fired when a final (committed) transcript is available.
   * If not provided, the transcript is only available via the returned state.
   */
  onResult?: (transcript: string) => void;
  /** Callback fired on recognition errors. */
  onError?: (error: string) => void;
}

// ---------------------------------------------------------------------------
// Return shape
// ---------------------------------------------------------------------------

export interface UseVoiceInputReturn {
  /** True when the Speech API is available in this browser. */
  isSupported: boolean;
  /** True while the microphone is actively listening. */
  isListening: boolean;
  /** The latest transcript (interim or final depending on `interimResults`). */
  transcript: string;
  /** Start voice capture.  No-op when `isSupported` is false. */
  startListening: () => void;
  /** Stop voice capture cleanly (fires `onend`, transcript is kept). */
  stopListening: () => void;
  /** Stop and discard the current transcript. */
  abort: () => void;
  /** Clear the transcript without affecting listening state. */
  clearTranscript: () => void;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * React hook that wraps the Web Speech API for voice input.
 *
 * @param options - Configuration for language, interim results, and callbacks.
 * @returns Recognition state and control functions.
 *
 * @example
 * ```tsx
 * const { isListening, transcript, startListening, stopListening } =
 *   useVoiceInput({ onResult: (text) => console.log(text) });
 * ```
 */
export function useVoiceInput(
  options: UseVoiceInputOptions = {},
): UseVoiceInputReturn {
  const {
    lang = "en-IN",
    interimResults = false,
    onResult,
    onError,
  } = options;

  // Detect support on mount (stable — won't change after initial render)
  const isSupported =
    typeof window !== "undefined" &&
    !!(window.SpeechRecognition ?? window.webkitSpeechRecognition);

  const [isListening, setIsListening] = useState(false);
  const [transcript, setTranscript] = useState("");

  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null);
  const activeRef = useRef(false);
  // Keep a stable ref to callbacks so we don't re-initialise recognition
  const onResultRef = useRef(onResult);
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onResultRef.current = onResult;
    onErrorRef.current = onError;
  }, [onResult, onError]);

  // ------------------------------------------------------------------
  // Initialise recogniser
  // ------------------------------------------------------------------

  const getRecognition = useCallback((): SpeechRecognitionInstance | null => {
    if (!isSupported) return null;

    if (recognitionRef.current) return recognitionRef.current;

    const SpeechRecognitionCtor =
      window.SpeechRecognition ?? window.webkitSpeechRecognition;
    if (!SpeechRecognitionCtor) return null;

    const rec = new SpeechRecognitionCtor();
    rec.continuous = false;        // single utterance per startListening() call
    rec.interimResults = interimResults;
    rec.lang = lang;
    rec.maxAlternatives = 1;

    rec.onstart = () => {
      if (!activeRef.current || recognitionRef.current !== rec) return;
      setIsListening(true);
    };

    rec.onresult = (event: SpeechRecognitionEvent) => {
      if (!activeRef.current || recognitionRef.current !== rec) return;
      let finalText = "";
      let interimText = "";

      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        const text = result[0].transcript;
        if (result.isFinal) {
          finalText += text;
        } else {
          interimText += text;
        }
      }

      const combined = (finalText || interimText).trim();
      if (combined) {
        setTranscript(combined);
      }

      if (finalText.trim()) {
        onResultRef.current?.(finalText.trim());
      }
    };

    rec.onerror = (event: SpeechRecognitionErrorEvent) => {
      if (!activeRef.current || recognitionRef.current !== rec) return;
      activeRef.current = false;
      // "no-speech" is a normal timeout — do not treat as error
      if (event.error !== "no-speech") {
        onErrorRef.current?.(event.error);
      }
      setIsListening(false);
    };

    rec.onend = () => {
      if (recognitionRef.current !== rec) return;
      activeRef.current = false;
      setIsListening(false);
    };

    recognitionRef.current = rec;
    return rec;
  }, [isSupported, interimResults, lang]);

  // ------------------------------------------------------------------
  // Reinitialise when lang/interimResults change
  // ------------------------------------------------------------------

  useEffect(() => {
    // Stop the old recogniser before replacing its language configuration.
    activeRef.current = false;
    const retired = recognitionRef.current;
    recognitionRef.current = null;
    retired?.abort();
  }, [lang, interimResults]);

  // ------------------------------------------------------------------
  // Cleanup on unmount
  // ------------------------------------------------------------------

  useEffect(() => {
    return () => {
      activeRef.current = false;
      const retired = recognitionRef.current;
      recognitionRef.current = null;
      retired?.abort();
    };
  }, []);

  // ------------------------------------------------------------------
  // Controls
  // ------------------------------------------------------------------

  const startListening = useCallback(() => {
    if (!isSupported) return;
    const rec = getRecognition();
    if (!rec) return;
    if (activeRef.current) return; // already starting or running

    setTranscript("");
    activeRef.current = true;
    try {
      rec.start();
    } catch (error) {
      activeRef.current = false;
      setIsListening(false);
      onErrorRef.current?.(error instanceof DOMException && error.name === "NotAllowedError"
        ? "not-allowed" : "start-failed");
    }
  }, [isSupported, getRecognition]);

  const stopListening = useCallback(() => {
    recognitionRef.current?.stop();
    setIsListening(false);
  }, []);

  const abort = useCallback(() => {
    activeRef.current = false;
    const retired = recognitionRef.current;
    recognitionRef.current = null;
    retired?.abort();
    setIsListening(false);
    setTranscript("");
  }, []);

  const clearTranscript = useCallback(() => {
    setTranscript("");
  }, []);

  // ------------------------------------------------------------------
  // No-op fallback when Speech API unavailable
  // ------------------------------------------------------------------

  if (!isSupported) {
    return {
      isSupported: false,
      isListening: false,
      transcript: "",
      startListening: () => undefined,
      stopListening: () => undefined,
      abort: () => undefined,
      clearTranscript: () => undefined,
    };
  }

  return {
    isSupported,
    isListening,
    transcript,
    startListening,
    stopListening,
    abort,
    clearTranscript,
  };
}
