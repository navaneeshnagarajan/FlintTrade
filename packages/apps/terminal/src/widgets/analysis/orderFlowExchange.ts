import { MCX_COMMODITIES } from "@/lib/mcxLots";

const NSE_INDEX_SYMBOLS = new Set([
  "NIFTY",
  "NIFTYNXT50",
  "BANKNIFTY",
  "FINNIFTY",
  "MIDCPNIFTY",
  "INDIAVIX",
  "HANGSENGBEESNAV",
  "NIFTY100",
  "NIFTY200",
  "NIFTY500",
  "NIFTYALPHA50",
  "NIFTYAUTO",
  "NIFTYCOMMODITIES",
  "NIFTYCONSUMPTION",
  "NIFTYCPSE",
  "NIFTYDIVOPPS50",
  "NIFTYENERGY",
  "NIFTYFMCG",
  "NIFTYGROWSECT15",
  "NIFTYGS10YR",
  "NIFTYGS10YRCLN",
  "NIFTYGS1115YR",
  "NIFTYGS15YRPLUS",
  "NIFTYGS48YR",
  "NIFTYGS813YR",
  "NIFTYGSCOMPSITE",
  "NIFTYINFRA",
  "NIFTYIT",
  "NIFTYMEDIA",
  "NIFTYMETAL",
  "NIFTYMIDLIQ15",
  "NIFTYMIDCAP100",
  "NIFTYMIDCAP150",
  "NIFTYMIDCAP50",
  "NIFTYMIDSML400",
  "NIFTYMNC",
  "NIFTYPHARMA",
  "NIFTYPSE",
  "NIFTYPSUBANK",
  "NIFTYPVTBANK",
  "NIFTYREALTY",
  "NIFTYSERVSECTOR",
  "NIFTYSMLCAP100",
  "NIFTYSMLCAP250",
  "NIFTYSMLCAP50",
  "NIFTY100EQLWGT",
  "NIFTY100LIQ15",
  "NIFTY100LOWVOL30",
  "NIFTY100QUALTY30",
  "NIFTY200QUALTY30",
  "NIFTY50DIVPOINT",
  "NIFTY50EQLWGT",
  "NIFTY50PR1XINV",
  "NIFTY50PR2XLEV",
  "NIFTY50TR1XINV",
  "NIFTY50TR2XLEV",
  "NIFTY50VALUE20",
]);
const BSE_INDEX_SYMBOLS = new Set([
  "SENSEX",
  "BANKEX",
  "SENSEX50",
  "BSE100",
  "BSE150MIDCAPINDEX",
  "BSE200",
  "BSE250LARGEMIDCAPINDEX",
  "BSE400MIDSMALLCAPINDEX",
  "BSE500",
  "BSEAUTO",
  "BSECAPITALGOODS",
  "BSECARBONEX",
  "BSECONSUMERDURABLES",
  "BSECPSE",
  "BSEDOLLEX100",
  "BSEDOLLEX200",
  "BSEDOLLEX30",
  "BSEENERGY",
  "BSEFASTMOVINGCONSUMERGOODS",
  "BSEFINANCIALSERVICES",
  "BSEGREENEX",
  "BSEHEALTHCARE",
  "BSEINDIAINFRASTRUCTUREINDEX",
  "BSEINDUSTRIALS",
  "BSEINFORMATIONTECHNOLOGY",
  "BSEIPO",
  "BSELARGECAP",
  "BSEMETAL",
  "BSEMIDCAP",
  "BSEMIDCAPSELECTINDEX",
  "BSEOIL&GAS",
  "BSEPOWER",
  "BSEPSU",
  "BSEREALTY",
  "BSESENSEXNEXT50",
  "BSESMALLCAP",
  "BSESMALLCAPSELECTINDEX",
  "BSESMEIPO",
  "BSETECK",
  "BSETELECOM",
]);
const MCX_INDEX_SYMBOLS = new Set([
  "MCXAGRI",
  "MCXBULLDEX",
  "MCXCOMDEX",
  "MCXCOMPDEX",
  "MCXCOPRDEX",
  "MCXCRUDEX",
  "MCXENERGY",
  "MCXGOLDEX",
  "MCXMETAL",
  "MCXMETLDEX",
  "MCXSILVDEX",
]);
const GLOBAL_INDEX_SYMBOLS = new Set([
  "AUS200",
  "FRANCE40",
  "GERMANY40",
  "GIFTNIFTY",
  "HANGSENG",
  "JAPAN225",
  "SHANGHAICHINA",
  "UK100",
  "US100",
  "US10YRYIELD",
  "US30",
  "US500",
  "USCOMPOSITE",
]);
const CDS_UNDERLYINGS = [
  "USDINR",
  "EURINR",
  "GBPINR",
  "JPYINR",
  "EURUSD",
  "GBPUSD",
  "USDJPY",
];

function isKnownUnderlyingOrContract(
  symbol: string,
  underlyings: Iterable<string>,
): boolean {
  for (const underlying of underlyings) {
    if (symbol === underlying) return true;
    if (symbol.startsWith(underlying) && /^\d/.test(symbol.slice(underlying.length))) {
      return true;
    }
  }
  return false;
}

function isDerivativeContractSymbol(symbol: string): boolean {
  return /\d.*(?:CE|PE|FUT)$/.test(symbol);
}

/** Resolves the capture exchange for an order-flow instrument. */
export function resolveOrderFlowExchange(symbol: string, explicitExchange?: string): string {
  const normalisedExchange = explicitExchange?.trim().toUpperCase();
  if (normalisedExchange) return normalisedExchange;

  const normalisedSymbol = symbol.trim().toUpperCase();

  if (isKnownUnderlyingOrContract(normalisedSymbol, MCX_COMMODITIES)) return "MCX";
  if (isKnownUnderlyingOrContract(normalisedSymbol, CDS_UNDERLYINGS)) return "CDS";
  if (MCX_INDEX_SYMBOLS.has(normalisedSymbol)) return "MCX_INDEX";
  if (GLOBAL_INDEX_SYMBOLS.has(normalisedSymbol)) return "GLOBAL_INDEX";
  if (BSE_INDEX_SYMBOLS.has(normalisedSymbol)) return "BSE_INDEX";
  if (NSE_INDEX_SYMBOLS.has(normalisedSymbol)) return "NSE_INDEX";
  if (isDerivativeContractSymbol(normalisedSymbol)) {
    if (isKnownUnderlyingOrContract(normalisedSymbol, MCX_INDEX_SYMBOLS)) return "MCX";
    if (isKnownUnderlyingOrContract(normalisedSymbol, BSE_INDEX_SYMBOLS)) return "BFO";
    return "NFO";
  }
  return "NSE";
}
