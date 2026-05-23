export function chartTheme() {
  return {
    layout: {
      background: { color: "transparent" },
      textColor: "var(--color-foreground)",
    },
    grid: {
      horzLines: { color: "var(--color-border)" },
      vertLines: { color: "var(--color-border)" },
    },
  }
}

export function plotlyTheme() {
  return {
    paper_bgcolor: "transparent",
    plot_bgcolor: "transparent",
    font: { color: "var(--color-foreground)" },
  }
}

export function tremorTheme() {
  return {
    backgroundColor: "transparent",
    textColor: "var(--color-foreground)",
  }
}
