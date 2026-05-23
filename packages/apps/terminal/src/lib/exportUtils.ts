/**
 * exportUtils.ts
 *
 * Data export utilities for financial views.
 * CSV export with proper escaping and browser print support.
 */

/**
 * Convert an array of objects to a CSV string and trigger a file download.
 * Handles escaping of commas, quotes, and newlines per RFC 4180.
 */
export function exportToCSV(data: Record<string, unknown>[], filename: string): void {
  if (data.length === 0) return;

  const headers = Object.keys(data[0]);
  const rows = data.map((row) =>
    headers
      .map((h) => {
        const val = row[h];
        const str = String(val ?? "");
        // Escape fields containing commas, quotes, or newlines
        return str.includes(",") || str.includes('"') || str.includes("\n")
          ? `"${str.replace(/"/g, '""')}"`
          : str;
      })
      .join(","),
  );

  const csv = [headers.join(","), ...rows].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${filename}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

/**
 * Trigger the browser's native print dialog for the current view.
 */
export function printCurrentView(): void {
  window.print();
}
