import { describe, expect, it } from "vitest";
import { cn } from "../utils";

describe("cn", () => {
  it("keeps the text-xxs font size beside a text colour", () => {
    expect(cn("text-xxs", "text-text-muted")).toBe("text-xxs text-text-muted");
  });

  it("still lets a later font size replace text-xxs", () => {
    expect(cn("text-xxs text-text-muted", "text-sm")).toBe("text-text-muted text-sm");
  });
});
