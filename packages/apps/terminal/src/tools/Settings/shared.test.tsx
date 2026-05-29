import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { SelectInput } from "./shared";

describe("Settings SelectInput", () => {
  it("supports an empty-string option for clearable settings", async () => {
    const onChange = vi.fn();

    expect(() => {
      render(
        <SelectInput
          aria-label="Module skill override"
          value=""
          onChange={onChange}
          options={[
            { value: "", label: "Global Default" },
            { value: "advanced", label: "Expert" },
          ]}
        />,
      );
    }).not.toThrow();

    expect(screen.getByRole("combobox", { name: /module skill override/i })).toHaveTextContent(
      "Global Default",
    );
    expect(onChange).not.toHaveBeenCalled();
  });
});
