/**
 * gridConfig — Glide Data Grid column definitions, cell builders, and theme.
 *
 * All Glide-specific config lives here so OptionChainWidget stays clean.
 */

import type { GridColumn, GridCell, Theme } from "@glideapps/glide-data-grid";
import { GridCellKind } from "@glideapps/glide-data-grid";
import type { ViewType, OISignal, StrikeRow } from "./types";
import {
  fmtLtp,
  fmtOI,
  fmtChg,
  fmtDelta,
  fmtGreek,
  fmtIV,
  NUM0,
  getOISignal,
  oiSignalShort,
} from "./formatters";

// ---------------------------------------------------------------------------
// Theme
// ---------------------------------------------------------------------------

/** Glide theme — uses design token hex values */
export const GLIDE_THEME: Partial<Theme> = {
  bgCell:            "#0a0a0f",   // surface-base
  bgCellMedium:      "#16161f",   // surface-card
  bgHeader:          "#16161f",   // surface-card
  bgHeaderHasFocus:  "#24242e",   // surface-hover
  bgHeaderHovered:   "#24242e",   // surface-hover
  textDark:          "#e4e4e7",   // text-primary
  textMedium:        "#8b8b95",   // text-secondary
  textLight:         "#6b6b78",   // text-muted
  textHeader:        "#8b8b95",   // text-secondary
  accentColor:       "#6366f1",
  accentFg:          "#ffffff",
  borderColor:       "#2a2a3a",   // border-default
  fontFamily:        "JetBrains Mono, monospace",
  baseFontStyle:     "11px",
  headerFontStyle:   "500 10px",
  editorFontSize:    "11px",
};

// ATM row theme override
export const ATM_ROW_THEME = { bgCell: "#eab30812", bgCellMedium: "#eab30818" };

// ---------------------------------------------------------------------------
// Column definitions per view
// ---------------------------------------------------------------------------

export function getColumns(view: ViewType): GridColumn[] {
  if (view === "LTP") {
    return [
      { title: "SIG",    width: 38, id: "c_sig"  },
      { title: "CHG%",   width: 52, id: "c_chg"  },
      { title: "LTP",    width: 60, id: "c_ltp"  },
      { title: "OI",     width: 54, id: "c_oi"   },
      { title: "CALL",   width: 52, id: "c_act"  },
      { title: "STRIKE", width: 58, id: "strike" },
      { title: "PUT",    width: 52, id: "p_act"  },
      { title: "LTP",    width: 60, id: "p_ltp"  },
      { title: "CHG%",   width: 52, id: "p_chg"  },
      { title: "OI",     width: 54, id: "p_oi"   },
      { title: "SIG",    width: 38, id: "p_sig"  },
    ];
  }
  if (view === "OI") {
    return [
      { title: "SIG",    width: 38, id: "c_sig"    },
      { title: "OI CHG", width: 58, id: "c_oichg"  },
      { title: "OI",     width: 54, id: "c_oi"     },
      { title: "LTP",    width: 60, id: "c_ltp"    },
      { title: "CALL",   width: 52, id: "c_act"    },
      { title: "STRIKE", width: 58, id: "strike"   },
      { title: "PUT",    width: 52, id: "p_act"    },
      { title: "LTP",    width: 60, id: "p_ltp"    },
      { title: "OI",     width: 54, id: "p_oi"     },
      { title: "OI CHG", width: 58, id: "p_oichg"  },
      { title: "SIG",    width: 38, id: "p_sig"    },
    ];
  }
  // GREEKS
  return [
    { title: "IV",     width: 50, id: "c_iv"    },
    { title: "DELTA",  width: 52, id: "c_delta" },
    { title: "GAMMA",  width: 52, id: "c_gamma" },
    { title: "THETA",  width: 52, id: "c_theta" },
    { title: "VEGA",   width: 52, id: "c_vega"  },
    { title: "CALL",   width: 52, id: "c_act"   },
    { title: "STRIKE", width: 58, id: "strike"  },
    { title: "PUT",    width: 52, id: "p_act"   },
    { title: "DELTA",  width: 52, id: "p_delta" },
    { title: "GAMMA",  width: 52, id: "p_gamma" },
    { title: "THETA",  width: 52, id: "p_theta" },
    { title: "VEGA",   width: 52, id: "p_vega"  },
    { title: "IV",     width: 50, id: "p_iv"    },
  ];
}

// ---------------------------------------------------------------------------
// Cell builder helpers
// ---------------------------------------------------------------------------

function mkText(
  display: string,
  opts?: { themeOverride?: Partial<Theme> },
): GridCell {
  return {
    kind: GridCellKind.Text,
    data: display,
    displayData: display,
    allowOverlay: false,
    themeOverride: opts?.themeOverride,
    readonly: true,
  };
}

function mkAction(label: "B/S CE" | "B/S PE", inBasket: boolean): GridCell {
  return {
    kind: GridCellKind.Text,
    data: label,
    displayData: inBasket ? "✓ B" : "+B",
    allowOverlay: false,
    themeOverride: inBasket
      ? { textDark: "#818cf8", baseFontStyle: "bold 10px" }
      : { textDark: "#6366f1", baseFontStyle: "600 10px" },
    readonly: true,
  };
}

/**
 * Gradient OI bar — uses unicode block characters with varying density to simulate
 * a gradient visual. Low OI: sparse chars (░), mid OI: medium (▒), high OI: dense (█).
 */
function oiBarGradient(value: number | null | undefined, maxValue: number): string {
  if (!value || !maxValue) return "";
  const pct = Math.min((Number(value) / Number(maxValue)) * 100, 100);
  const totalWidth = 5;
  const filled = Math.round((pct / 100) * totalWidth);
  let bar = "";
  for (let i = 0; i < totalWidth; i++) {
    if (i < filled) {
      // gradient: last segment lighter to give gradient feel
      if (i === filled - 1 && filled < totalWidth) {
        bar += "▓";
      } else {
        bar += "█";
      }
    } else if (i === filled) {
      bar += pct > 5 ? "▒" : "";
    }
  }
  return bar + " " + fmtOI(value);
}

function oiSigText(signal: OISignal): string {
  return signal ? oiSignalShort(signal) : "—";
}

function chgColour(v: number | null | undefined): string | undefined {
  if (v == null) return undefined;
  return Number(v) >= 0 ? "#4ade80" : "#f87171";
}

// ---------------------------------------------------------------------------
// getCellContent — column/row → GridCell
// ---------------------------------------------------------------------------

interface CellParams {
  view: ViewType;
  columns: GridColumn[];
  strikes: StrikeRow[];
  atmStrike: number | null;
  maxCallOI: number;
  maxPutOI: number;
  isInBasket: (strike: number, optionType: "CE" | "PE") => boolean;
  /** Map of "<strike>_CE" | "<strike>_PE" → "up" | "down" for active flash state */
  flashState?: Map<string, "up" | "down">;
}

/** Returns a bgCell override colour for flash animation, or undefined if not flashing */
function flashBg(flashState: Map<string, "up" | "down"> | undefined, key: string): string | undefined {
  if (!flashState) return undefined;
  const dir = flashState.get(key);
  if (dir === "up")   return "rgba(34, 197, 94, 0.25)";
  if (dir === "down") return "rgba(239, 68, 68, 0.25)";
  return undefined;
}

export function buildGetCellContent(params: CellParams) {
  const { view, columns, strikes, atmStrike, maxCallOI, maxPutOI, isInBasket, flashState } = params;

  return ([col, row]: [number, number]): GridCell => {
    const strikeRow = strikes[row];
    if (!strikeRow) return mkText("—");

    const { strike, call, put } = strikeRow;
    const colId = columns[col]?.id ?? "";

    // Strike column
    if (colId === "strike") {
      const isAtm = strike === atmStrike;
      return {
        kind: GridCellKind.Text,
        data: NUM0.format(strike),
        displayData: isAtm ? `▶ ${NUM0.format(strike)}` : NUM0.format(strike),
        allowOverlay: false,
        themeOverride: isAtm ? { textDark: "#eab308", baseFontStyle: "bold 11px" } : undefined,
        readonly: true,
      };
    }

    const ceInBasket = isInBasket(strike, "CE");
    const peInBasket = isInBasket(strike, "PE");

    // LTP view
    if (view === "LTP") {
      const cLtp = call?.ltp ?? call?.last_price ?? null;
      const cChg = call?.change_percent ?? call?.change_pct ?? null;
      const cOI  = call?.oi ?? call?.open_interest ?? null;
      const cSig = getOISignal(call);
      const pLtp = put?.ltp ?? put?.last_price ?? null;
      const pChg = put?.change_percent ?? put?.change_pct ?? null;
      const pOI  = put?.oi ?? put?.open_interest ?? null;
      const pSig = getOISignal(put);
      const cFlash = flashBg(flashState, `${strike}_CE`);
      const pFlash = flashBg(flashState, `${strike}_PE`);

      switch (colId) {
        case "c_sig":  return mkText(oiSigText(cSig), cFlash ? { themeOverride: { bgCell: cFlash } } : undefined);
        case "c_chg":  return mkText(fmtChg(cChg), { themeOverride: { textDark: chgColour(cChg) ?? "#a0a0b0", ...(cFlash ? { bgCell: cFlash } : {}) } });
        case "c_ltp":  return mkText(fmtLtp(cLtp), cFlash ? { themeOverride: { bgCell: cFlash } } : undefined);
        case "c_oi":   return mkText(oiBarGradient(cOI, maxCallOI), cFlash ? { themeOverride: { bgCell: cFlash } } : undefined);
        case "c_act":  return mkAction("B/S CE", ceInBasket);
        case "p_act":  return mkAction("B/S PE", peInBasket);
        case "p_ltp":  return mkText(fmtLtp(pLtp), pFlash ? { themeOverride: { bgCell: pFlash } } : undefined);
        case "p_chg":  return mkText(fmtChg(pChg), { themeOverride: { textDark: chgColour(pChg) ?? "#a0a0b0", ...(pFlash ? { bgCell: pFlash } : {}) } });
        case "p_oi":   return mkText(oiBarGradient(pOI, maxPutOI), pFlash ? { themeOverride: { bgCell: pFlash } } : undefined);
        case "p_sig":  return mkText(oiSigText(pSig), pFlash ? { themeOverride: { bgCell: pFlash } } : undefined);
      }
    }

    // OI view
    if (view === "OI") {
      const cLtp   = call?.ltp ?? call?.last_price ?? null;
      const cOI    = call?.oi ?? call?.open_interest ?? null;
      const cOiChg = call?.oi_change ?? null;
      const cSig   = getOISignal(call);
      const pLtp   = put?.ltp ?? put?.last_price ?? null;
      const pOI    = put?.oi ?? put?.open_interest ?? null;
      const pOiChg = put?.oi_change ?? null;
      const pSig   = getOISignal(put);
      const cFlashOI = flashBg(flashState, `${strike}_CE`);
      const pFlashOI = flashBg(flashState, `${strike}_PE`);

      const fmtOiChg = (v: number | null) =>
        v != null ? `${Number(v) >= 0 ? "+" : ""}${fmtOI(Math.abs(v))}` : "—";

      switch (colId) {
        case "c_sig":   return mkText(oiSigText(cSig), cFlashOI ? { themeOverride: { bgCell: cFlashOI } } : undefined);
        case "c_oichg": return mkText(fmtOiChg(cOiChg), { themeOverride: { textDark: chgColour(cOiChg) ?? "#a0a0b0", ...(cFlashOI ? { bgCell: cFlashOI } : {}) } });
        case "c_oi":    return mkText(oiBarGradient(cOI, maxCallOI), cFlashOI ? { themeOverride: { bgCell: cFlashOI } } : undefined);
        case "c_ltp":   return mkText(fmtLtp(cLtp), cFlashOI ? { themeOverride: { bgCell: cFlashOI } } : undefined);
        case "c_act":   return mkAction("B/S CE", ceInBasket);
        case "p_act":   return mkAction("B/S PE", peInBasket);
        case "p_ltp":   return mkText(fmtLtp(pLtp), pFlashOI ? { themeOverride: { bgCell: pFlashOI } } : undefined);
        case "p_oi":    return mkText(oiBarGradient(pOI, maxPutOI), pFlashOI ? { themeOverride: { bgCell: pFlashOI } } : undefined);
        case "p_oichg": return mkText(fmtOiChg(pOiChg), { themeOverride: { textDark: chgColour(pOiChg) ?? "#a0a0b0", ...(pFlashOI ? { bgCell: pFlashOI } : {}) } });
        case "p_sig":   return mkText(oiSigText(pSig), pFlashOI ? { themeOverride: { bgCell: pFlashOI } } : undefined);
      }
    }

    // GREEKS view
    {
      const cIV    = call?.iv ?? call?.implied_volatility ?? null;
      const cDelta = call?.delta ?? null;
      const cGamma = call?.gamma ?? null;
      const cTheta = call?.theta ?? null;
      const cVega  = call?.vega ?? null;
      const pIV    = put?.iv ?? put?.implied_volatility ?? null;
      const pDelta = put?.delta ?? null;
      const pGamma = put?.gamma ?? null;
      const pTheta = put?.theta ?? null;
      const pVega  = put?.vega ?? null;

      switch (colId) {
        case "c_iv":    return mkText(fmtIV(cIV));
        case "c_delta": return mkText(fmtDelta(cDelta));
        case "c_gamma": return mkText(fmtGreek(cGamma));
        case "c_theta": return mkText(fmtGreek(cTheta));
        case "c_vega":  return mkText(fmtGreek(cVega));
        case "c_act":   return mkAction("B/S CE", ceInBasket);
        case "p_act":   return mkAction("B/S PE", peInBasket);
        case "p_delta": return mkText(fmtDelta(pDelta));
        case "p_gamma": return mkText(fmtGreek(pGamma));
        case "p_theta": return mkText(fmtGreek(pTheta));
        case "p_vega":  return mkText(fmtGreek(pVega));
        case "p_iv":    return mkText(fmtIV(pIV));
      }
    }

    return mkText("—");
  };
}
