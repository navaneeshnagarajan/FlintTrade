import type { InstrumentIdentity } from "./marketData";
import type { OrderTypeValue, ProductValue } from "@/lib/tradingConstants";

/** UI-to-FlintTrade contracts, separate from broker request wire formats. */
export type OrderSide = "BUY" | "SELL";
export interface ApiResponse<T> { status: "success" | "error"; message?: string; data?: T }
interface TradeInstruction extends InstrumentIdentity {
  action: OrderSide; quantity: number; orderType: OrderTypeValue; product: ProductValue;
  price?: number; triggerPrice?: number;
}
export interface PlaceOrderParams extends TradeInstruction {
  strategy?: string;
  marketProtection?: boolean;
  /** Exchange-visible amount, independent of total order quantity. */
  disclosedQuantity?: number;
  /** Admission plan; it is not passed as an adapter instruction. */
  rationale?: string;
  /** Confirms the supplied price came from a quote, for Practice fills. */
  priceBasis?: "ltp";
}
export interface ModifyOrderParams extends TradeInstruction { orderId: string; strategy?: string; disclosedQuantity?: number }
export interface OrderStatusParams { orderId: string; strategy?: string }
export type BasketOrderLeg = TradeInstruction;
export interface BasketOrderParams { strategy?: string; orders: BasketOrderLeg[] }
export interface SplitOrderParams extends Omit<TradeInstruction, "quantity"> { totalQuantity: number; chunkSize: number; delaySeconds?: number; strategy?: string }
export interface OptionsMultiOrderLeg extends Omit<TradeInstruction, "symbol" | "exchange"> { expiry: string; strike: number; optionType: "CE" | "PE" }
export interface OptionsOrderParams extends OptionsMultiOrderLeg { underlying: string; exchange: string; strategy?: string }
export interface OptionsMultiOrderParams { underlying: string; exchange: string; legs: OptionsMultiOrderLeg[]; strategy?: string }

/** Exact per-leg execution and rollback outcomes from order_routes.py. */
export interface BasketLegResult {
  leg_index: number; symbol: string; action: string; quantity: number;
  success: boolean; order_id: string; error: string;
  rolled_back: boolean; rollback_order_id: string;
}
export interface BasketOrderResult {
  status: "success" | "error"; strategy: string; timestamp: string;
  placed_count: number; failed_count: number; rolled_back: boolean;
  order_ids: string[]; legs: BasketLegResult[]; message?: string; failed_leg_index?: number | null;
}

interface ValuedQuantity extends InstrumentIdentity {
  quantity: number; averagePrice: number; ltp: number; pnl: number; pnlPercent: number;
}
export interface Holding extends ValuedQuantity {}
export interface Position extends ValuedQuantity {
  product: string; restored?: boolean;
  ltpBasis?: "ltp" | "last_close" | "fill_price";
  priceSource?: "ltp" | "last_close"; priceAgeS?: number; priceLabel?: string;
  markSource?: "avg" | "fallback"; settlementPrice?: number;
}
export interface Order extends InstrumentIdentity {
  orderId: string; action: OrderSide; quantity: number; price: number;
  orderType: string; status: string; product: string; strategy: string; timestamp: string;
  triggerPrice?: number;
}
export interface Trade extends InstrumentIdentity {
  tradeId: string; orderId: string; action: OrderSide; quantity: number; price: number;
  timestamp: string; strategy?: string; estimatedCharges?: EstimatedCharges;
}
export interface Funds {
  availableCash: number; usedMargin: number; totalBalance: number;
  ledgerBalance?: number; futuresMtmInLedger?: boolean; estimatedCharges?: number;
}
export interface EstimatedCharges { total: number; stt: number; exchangeCharges: number; exchangeLabel: string; sebiFee: number; stampDuty: number; gst: number }
