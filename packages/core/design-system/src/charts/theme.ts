export type FlintChartDensity = "compact" | "standard" | "pro";

export interface FlintChartPalette {
  background: string;
  grid: string;
  text: string;
  border: string;
  up: string;
  down: string;
  accent: string;
  muted: string;
}

export interface FlintChartThemeOptions {
  density?: FlintChartDensity;
}

export interface FlintLightweightChartTheme {
  layout: {
    background: { color: string };
    textColor: string;
    fontFamily: string;
    fontSize: number;
    panes: {
      enableResize: boolean;
      separatorColor: string;
      separatorHoverColor: string;
    };
  };
  grid: {
    vertLines: { color: string; style: number; visible: boolean };
    horzLines: { color: string; style: number; visible: boolean };
  };
  crosshair: {
    mode: number;
    vertLine: {
      color: string;
      width: number;
      style: number;
      visible: boolean;
      labelVisible: boolean;
      labelBackgroundColor: string;
    };
    horzLine: {
      color: string;
      width: number;
      style: number;
      visible: boolean;
      labelVisible: boolean;
      labelBackgroundColor: string;
    };
    doNotSnapToHiddenSeriesIndices: boolean;
  };
  rightPriceScale: {
    autoScale: boolean;
    borderVisible: boolean;
    borderColor: string;
    textColor: string;
    entireTextOnly: boolean;
    ticksVisible: boolean;
    minimumWidth: number;
    ensureEdgeTickMarksVisible: boolean;
    tickMarkDensity: number;
    scaleMargins: { top: number; bottom: number };
  };
  timeScale: {
    borderVisible: boolean;
    borderColor: string;
    visible: boolean;
    timeVisible: boolean;
    secondsVisible: boolean;
    ticksVisible: boolean;
    rightOffset: number;
    barSpacing: number;
    minBarSpacing: number;
    maxBarSpacing: number;
    fixLeftEdge: boolean;
    fixRightEdge: boolean;
    lockVisibleTimeRangeOnResize: boolean;
    rightBarStaysOnScroll: boolean;
    shiftVisibleRangeOnNewBar: boolean;
    allowShiftVisibleRangeOnWhitespaceReplacement: boolean;
    tickMarkMaxCharacterLength: number;
  };
  handleScale: {
    mouseWheel: boolean;
    pinch: boolean;
    axisPressedMouseMove: { time: boolean; price: boolean };
    axisDoubleClickReset: { time: boolean; price: boolean };
  };
  handleScroll: {
    mouseWheel: boolean;
    pressedMouseMove: boolean;
    horzTouchDrag: boolean;
    vertTouchDrag: boolean;
  };
  kineticScroll: { touch: boolean; mouse: boolean };
  trackingMode: { exitMode: number };
  candle: {
    upColor: string;
    downColor: string;
    borderUpColor: string;
    borderDownColor: string;
    wickUpColor: string;
    wickDownColor: string;
  };
  volume: {
    priceFormat: { type: "volume" };
    priceScaleId: string;
    color: string;
  };
}

const CROSSHAIR_NORMAL = 0;
const LINE_DOTTED = 1;
const LINE_DASHED = 2;
const TRACKING_EXIT_ON_NEXT_TAP = 1;

function withAlpha(colour: string, alpha: number): string {
  const value = colour.trim();
  const hex = value.startsWith("#") ? value.slice(1) : value;

  if (/^[0-9a-fA-F]{3}$/.test(hex)) {
    const [r, g, b] = hex.split("").map((part) => parseInt(`${part}${part}`, 16));
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  if (/^[0-9a-fA-F]{6}$/.test(hex)) {
    const r = parseInt(hex.slice(0, 2), 16);
    const g = parseInt(hex.slice(2, 4), 16);
    const b = parseInt(hex.slice(4, 6), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  return value;
}

export function createFlintLightweightChartTheme(
  palette: FlintChartPalette,
  options: FlintChartThemeOptions = {},
): FlintLightweightChartTheme {
  const density = options.density ?? "standard";
  const compact = density === "compact";
  const pro = density === "pro";
  const textSize = compact ? 10 : 11;
  const barSpacing = compact ? 5 : pro ? 8 : 7;

  return {
    layout: {
      background: { color: palette.background },
      textColor: palette.text,
      fontFamily: "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace",
      fontSize: textSize,
      panes: {
        enableResize: true,
        separatorColor: withAlpha(palette.border, 0.7),
        separatorHoverColor: withAlpha(palette.accent, 0.32),
      },
    },
    grid: {
      vertLines: { color: withAlpha(palette.grid, 0.48), style: LINE_DOTTED, visible: true },
      horzLines: { color: withAlpha(palette.grid, 0.54), style: LINE_DOTTED, visible: true },
    },
    crosshair: {
      mode: CROSSHAIR_NORMAL,
      vertLine: {
        color: withAlpha(palette.accent, 0.75),
        width: 1,
        style: LINE_DASHED,
        visible: true,
        labelVisible: true,
        labelBackgroundColor: palette.accent,
      },
      horzLine: {
        color: withAlpha(palette.accent, 0.68),
        width: 1,
        style: LINE_DASHED,
        visible: true,
        labelVisible: true,
        labelBackgroundColor: palette.accent,
      },
      doNotSnapToHiddenSeriesIndices: true,
    },
    rightPriceScale: {
      autoScale: true,
      borderVisible: true,
      borderColor: withAlpha(palette.border, 0.78),
      textColor: palette.text,
      entireTextOnly: true,
      ticksVisible: true,
      minimumWidth: compact ? 60 : 72,
      ensureEdgeTickMarksVisible: true,
      tickMarkDensity: compact ? 3 : 2.5,
      scaleMargins: { top: 0.08, bottom: 0.14 },
    },
    timeScale: {
      borderVisible: true,
      borderColor: withAlpha(palette.border, 0.78),
      visible: true,
      timeVisible: true,
      secondsVisible: false,
      ticksVisible: true,
      rightOffset: compact ? 5 : 8,
      barSpacing,
      minBarSpacing: 2,
      maxBarSpacing: compact ? 20 : 28,
      fixLeftEdge: false,
      fixRightEdge: false,
      lockVisibleTimeRangeOnResize: true,
      rightBarStaysOnScroll: true,
      shiftVisibleRangeOnNewBar: true,
      allowShiftVisibleRangeOnWhitespaceReplacement: true,
      tickMarkMaxCharacterLength: 10,
    },
    handleScale: {
      mouseWheel: true,
      pinch: true,
      axisPressedMouseMove: { time: true, price: true },
      axisDoubleClickReset: { time: true, price: true },
    },
    handleScroll: {
      mouseWheel: true,
      pressedMouseMove: true,
      horzTouchDrag: true,
      vertTouchDrag: false,
    },
    kineticScroll: { touch: true, mouse: true },
    trackingMode: { exitMode: TRACKING_EXIT_ON_NEXT_TAP },
    candle: {
      upColor: palette.up,
      downColor: palette.down,
      borderUpColor: palette.up,
      borderDownColor: palette.down,
      wickUpColor: withAlpha(palette.up, 0.92),
      wickDownColor: withAlpha(palette.down, 0.92),
    },
    volume: {
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
      color: withAlpha(palette.muted, 0.28),
    },
  };
}
