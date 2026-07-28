/**
 * PineEditor.test.tsx
 *
 * Tests for the Lab Pine Script Editor — compile-to-Python display flow and
 * the "Open in Strategy Builder" hand-off, which must carry the raw Pine
 * SOURCE (never the compiled Python) to the builder's sandboxed interpreter.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/services/ftApi", () => ({
  compilePineScript: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Imports after mocks
// ---------------------------------------------------------------------------

import PineEditor from "../PineEditor";
import { compilePineScript, type PineCompileResult } from "@/services/ftApi";
import {
  PENDING_PINE_DRAFT_KEY,
  LOAD_PINE_DRAFT_EVENT,
  OPEN_STRATEGY_BUILDER_EVENT,
  type PineDraft,
} from "@/tools/StrategyBuilder/pineBridge";

const compileMock = vi.mocked(compilePineScript);

const COMPILE_RESULT: PineCompileResult = {
  python_code: "def sma_crossover(close):\n    return close",
  imports: ["sma"],
  warnings: [],
  unsupported: [],
  supported_functions: ["ta.sma"],
};

function renderEditor() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <PineEditor />
    </QueryClientProvider>,
  );
}

function readStash(): PineDraft | null {
  const raw = sessionStorage.getItem(PENDING_PINE_DRAFT_KEY);
  return raw ? (JSON.parse(raw) as PineDraft) : null;
}

const editorTextarea = () =>
  screen.getByPlaceholderText("Enter Pine Script code here...");

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("PineEditor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
  });

  it("renders the editor with the hand-off action available", () => {
    renderEditor();
    expect(screen.getByText("Pine Script Editor")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Open in Strategy Builder/ }),
    ).toBeEnabled();
  });

  it("hands the raw Pine SOURCE to the Strategy Builder (stash + events), without compiling", async () => {
    const onLoad = vi.fn();
    const onOpen = vi.fn();
    window.addEventListener(LOAD_PINE_DRAFT_EVENT, onLoad);
    window.addEventListener(OPEN_STRATEGY_BUILDER_EVENT, onOpen);
    try {
      renderEditor();
      const source = (editorTextarea() as HTMLTextAreaElement).value;
      await userEvent.click(
        screen.getByRole("button", { name: /Open in Strategy Builder/ }),
      );

      // The stash carries the Pine SOURCE verbatim — pineBridge is the
      // builder's intake; no backend compile is involved in the hand-off.
      expect(readStash()).toEqual({ source });
      expect(source).toContain("ta.sma");
      expect(onLoad).toHaveBeenCalledTimes(1);
      expect(onOpen).toHaveBeenCalledTimes(1);
      expect(compileMock).not.toHaveBeenCalled();

      // Confirmation status for the operator.
      expect(screen.getByRole("status")).toHaveTextContent(
        "Pine source sent — open the Options Builder's Pine Script tab to run it.",
      );
    } finally {
      window.removeEventListener(LOAD_PINE_DRAFT_EVENT, onLoad);
      window.removeEventListener(OPEN_STRATEGY_BUILDER_EVENT, onOpen);
    }
  });

  it("hands off the edited source, not the original template", async () => {
    renderEditor();
    const custom = '//@version=5\nindicator("Mine")\nplot(close)';
    fireEvent.change(editorTextarea(), { target: { value: custom } });
    await userEvent.click(
      screen.getByRole("button", { name: /Open in Strategy Builder/ }),
    );
    expect(readStash()).toEqual({ source: custom });
  });

  it("disables the hand-off when the editor is blank", () => {
    renderEditor();
    fireEvent.change(editorTextarea(), { target: { value: "   " } });
    expect(
      screen.getByRole("button", { name: /Open in Strategy Builder/ }),
    ).toBeDisabled();
    expect(readStash()).toBeNull();
  });

  it("shows compiled Python as display-only with the sandboxed-interpreter hint, and still hands off Pine source", async () => {
    compileMock.mockResolvedValue(COMPILE_RESULT);
    renderEditor();

    await userEvent.click(screen.getByRole("button", { name: /Compile & Apply/ }));

    // Text queries normalise whitespace, so match a stable line of the
    // multi-line <pre> block rather than the exact string.
    expect(await screen.findByText(/def sma_crossover/)).toBeInTheDocument();
    expect(
      screen.getByText(
        /Compiled Python is for display and copying only — execution happens via the Strategy Builder's sandboxed Pine interpreter\./,
      ),
    ).toBeInTheDocument();
    expect(compileMock).toHaveBeenCalledTimes(1);

    // Even after a compile, the hand-off carries the SOURCE — the compiled
    // Python must never cross the bridge (deliberate security boundary).
    await userEvent.click(
      screen.getByRole("button", { name: /Open in Strategy Builder/ }),
    );
    const stash = readStash();
    expect(stash?.source).toContain("ta.sma");
    expect(stash?.source).not.toContain("def sma_crossover");
  });
});
