import { useState } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import TabTransition from "../TabTransition";
import { Input } from "@/components/ui/input";
import { useThemeStore } from "@/stores/themeStore";

let reduced = false;
const listeners = new Set<() => void>();
const animations: { cancel: ReturnType<typeof vi.fn> }[] = [];
const animate = vi.fn(() => {
  const animation = { cancel: vi.fn() };
  animations.push(animation);
  return animation;
});
function preference(next: boolean) {
  act(() => { reduced = next; for (const listener of listeners) listener(); });
}
function Draft() {
  const [value, setValue] = useState("");
  return <Input aria-label="Panel draft" value={value} onChange={event => setValue(event.target.value)} />;
}
beforeEach(() => {
  useThemeStore.getState().setReduceMotion(false);
  reduced = false; listeners.clear(); animations.length = 0; animate.mockClear();
  vi.spyOn(window, "matchMedia").mockImplementation(query => ({
    media: query, get matches() { return reduced; }, onchange: null,
    addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: () => true,
    addEventListener: (_event: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_event: string, listener: () => void) => listeners.delete(listener),
  }) as unknown as MediaQueryList);
  // jsdom has no native animation engine; test its boundary, not fake frames.
  vi.stubGlobal("Element", Element);
  Object.defineProperty(Element.prototype, "animate", { configurable: true, value: animate });
});
afterEach(() => {
  cleanup();
  expect(listeners.size).toBe(0);
  for (const animation of animations) expect(animation.cancel).toHaveBeenCalledTimes(1);
  delete (Element.prototype as Partial<Element>).animate;
  vi.restoreAllMocks(); vi.unstubAllGlobals();
});

describe("TabTransition", () => {
  it("preserves layout classes when reduced motion is enabled", () => {
    reduced = true;
    render(<TabTransition tabKey="flows" className="h-full min-h-0 overflow-hidden"><span>Flow canvas</span></TabTransition>);
    expect(screen.getByText("Flow canvas").parentElement).toHaveClass("h-full", "min-h-0", "overflow-hidden");
    expect(animate).not.toHaveBeenCalled();
  });

  it.each([false, true])("mounts the next tab immediately with consistent tabKey lifetime, reduced=%s", preference => {
    reduced = preference;
    const view = render(<TabTransition tabKey="overview" className="h-full min-h-0 overflow-hidden"><Draft /></TabTransition>);
    const previous = screen.getByRole("textbox");
    fireEvent.change(previous, { target: { value: "old panel" } });
    view.rerender(<TabTransition tabKey="details" className="h-full min-h-0 overflow-hidden"><Draft /></TabTransition>);
    expect(screen.getByRole("textbox")).not.toBe(previous);
    expect(previous).not.toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("");
    expect(screen.getByRole("textbox").parentElement).toHaveClass("h-full", "min-h-0", "overflow-hidden");
    if (!preference) {
      expect(animations[0].cancel).toHaveBeenCalledTimes(1);
      expect(animate).toHaveBeenLastCalledWith([{ opacity: 0 }, { opacity: 1 }], {
        duration: 200, easing: "cubic-bezier(0.22,1,0.36,1)", fill: "none",
      });
    } else expect(animate).not.toHaveBeenCalled();
  });

  it("retains the exact child on live preference changes and same-key parent rerenders", () => {
    const view = render(<TabTransition tabKey="same"><Draft /></TabTransition>);
    const input = screen.getByRole("textbox"), wrapper = input.parentElement;
    fireEvent.change(input, { target: { value: "DRAFT-CANARY" } });
    preference(true);
    expect(animations[0].cancel).toHaveBeenCalledTimes(1);
    expect(animate).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("textbox")).toBe(input);
    expect(input).toHaveValue("DRAFT-CANARY");
    expect(wrapper?.style.opacity).toBe("");
    preference(false);
    expect(screen.getByRole("textbox")).toBe(input);
    expect(input).toHaveValue("DRAFT-CANARY");
    const count = animate.mock.calls.length;
    view.rerender(<TabTransition tabKey="same" className="updated"><Draft /></TabTransition>);
    expect(input.parentElement).toBe(wrapper);
    expect(screen.getByRole("textbox")).toBe(input);
    expect(input).toHaveValue("DRAFT-CANARY");
    expect(animate).toHaveBeenCalledTimes(count);
  });

  it("honours the app reduction preference without overriding an OS reduction or losing drafts", () => {
    const view = render(<TabTransition tabKey="policy"><Draft /></TabTransition>);
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "POLICY-CANARY" } });
    act(() => useThemeStore.getState().setReduceMotion(true));
    expect(animations[0].cancel).toHaveBeenCalledTimes(1);
    expect(animate).toHaveBeenCalledTimes(1);
    preference(true);
    act(() => useThemeStore.getState().setReduceMotion(false));
    expect(animate).toHaveBeenCalledTimes(1); // app opt-in cannot beat OS opt-out
    preference(false);
    expect(animate).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("textbox")).toBe(input);
    expect(input).toHaveValue("POLICY-CANARY");
    view.unmount();
    act(() => useThemeStore.getState().setReduceMotion(true));
    render(<TabTransition tabKey="cold"><Draft /></TabTransition>);
    expect(animate).toHaveBeenCalledTimes(2); // cold app opt-out, OS no-preference
  });

  it.each(["missing", "unsupported"])("leaves content visible when native animation is %s", capability => {
    if (capability === "missing") delete (Element.prototype as Partial<Element>).animate;
    else animate.mockImplementationOnce(() => { throw new DOMException("Unsupported animation", "NotSupportedError"); });
    render(<TabTransition tabKey="visible"><Draft /></TabTransition>);
    expect(screen.getByRole("textbox")).toBeVisible();
    expect(screen.getByRole("textbox").parentElement?.style.opacity).toBe("");
  });
});
