import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { exportToCSV, printCurrentView } from "../exportUtils";

// Restore all vi.stubGlobal() calls after each test so that URL and print
// are not left as stubs in singleFork mode (they would break connectionStore
// and other modules that use the real URL constructor).
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("exportToCSV", () => {
  let createObjectURLSpy: ReturnType<typeof vi.fn>;
  let revokeObjectURLSpy: ReturnType<typeof vi.fn>;
  let clickSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    createObjectURLSpy = vi.fn().mockReturnValue("blob:mock-url");
    revokeObjectURLSpy = vi.fn();
    clickSpy = vi.fn();

    vi.stubGlobal("URL", {
      createObjectURL: createObjectURLSpy,
      revokeObjectURL: revokeObjectURLSpy,
    });

    // Cast via the overloaded signature's return union: the Perspective
    // viewer packages ambiently augment createElement's overloads.
    vi.spyOn(document, "createElement").mockReturnValue({
      href: "",
      download: "",
      click: clickSpy,
    } as unknown as ReturnType<typeof document.createElement>);
  });

  it("does nothing for empty data", () => {
    exportToCSV([], "test");
    expect(createObjectURLSpy).not.toHaveBeenCalled();
    expect(clickSpy).not.toHaveBeenCalled();
  });

  it("generates correct CSV for simple data", () => {
    const data = [
      { Symbol: "RELIANCE", Quantity: 10, Price: 2500 },
      { Symbol: "TCS", Quantity: 5, Price: 3800 },
    ];

    exportToCSV(data, "holdings");

    expect(createObjectURLSpy).toHaveBeenCalledTimes(1);
    const blob = createObjectURLSpy.mock.calls[0][0] as Blob;
    expect(blob.type).toBe("text/csv;charset=utf-8;");
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(revokeObjectURLSpy).toHaveBeenCalledWith("blob:mock-url");
  });

  it("escapes commas in field values", () => {
    const data = [{ Name: "Reliance Industries, Ltd", Value: 100 }];

    exportToCSV(data, "test");

    const blob = createObjectURLSpy.mock.calls[0][0] as Blob;
    // Read blob content
    const reader = new FileReader();
    return new Promise<void>((resolve) => {
      reader.onload = () => {
        const csv = reader.result as string;
        expect(csv).toContain('"Reliance Industries, Ltd"');
        resolve();
      };
      reader.readAsText(blob);
    });
  });

  it("escapes double quotes in field values", () => {
    const data = [{ Name: 'He said "hello"', Value: 42 }];

    exportToCSV(data, "test");

    const blob = createObjectURLSpy.mock.calls[0][0] as Blob;
    const reader = new FileReader();
    return new Promise<void>((resolve) => {
      reader.onload = () => {
        const csv = reader.result as string;
        expect(csv).toContain('"He said ""hello"""');
        resolve();
      };
      reader.readAsText(blob);
    });
  });

  it("handles null and undefined values", () => {
    const data = [{ A: null, B: undefined, C: "ok" }];

    exportToCSV(data as Record<string, unknown>[], "test");

    const blob = createObjectURLSpy.mock.calls[0][0] as Blob;
    const reader = new FileReader();
    return new Promise<void>((resolve) => {
      reader.onload = () => {
        const csv = reader.result as string;
        const lines = csv.split("\n");
        expect(lines[0]).toBe("A,B,C");
        expect(lines[1]).toBe(",,ok");
        resolve();
      };
      reader.readAsText(blob);
    });
  });

  it("sets correct filename with .csv extension", () => {
    const data = [{ X: 1 }];
    const anchor = { href: "", download: "", click: clickSpy };
    vi.spyOn(document, "createElement").mockReturnValue(
      anchor as unknown as ReturnType<typeof document.createElement>,
    );

    exportToCSV(data, "my-holdings-2025");

    expect(anchor.download).toBe("my-holdings-2025.csv");
  });

  it("handles numeric values correctly", () => {
    const data = [
      { Price: 2500.75, Change: -12.5, Percent: 0 },
    ];

    exportToCSV(data, "test");

    const blob = createObjectURLSpy.mock.calls[0][0] as Blob;
    const reader = new FileReader();
    return new Promise<void>((resolve) => {
      reader.onload = () => {
        const csv = reader.result as string;
        expect(csv).toContain("2500.75");
        expect(csv).toContain("-12.5");
        expect(csv).toContain("0");
        resolve();
      };
      reader.readAsText(blob);
    });
  });
});

describe("printCurrentView", () => {
  it("calls window.print()", () => {
    const printSpy = vi.fn();
    vi.stubGlobal("print", printSpy);

    printCurrentView();

    expect(printSpy).toHaveBeenCalledTimes(1);
  });
});
