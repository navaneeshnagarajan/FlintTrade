/** Public terminal model exports. Native transports normalise their responses
 * into these models before data enters queries, atoms or order-entry widgets.
 */
export type * from "./marketData";
export type * from "./trading";
export type * from "./analytics";

/** Detached HTTP JSON observations, not SDK objects or callable evidence hooks. */
export type PlacementJsonValue = null | boolean | number | string
  | PlacementJsonValue[] | { [key: string]: PlacementJsonValue };

/** Documented native execution semantics; not a quote, fill or readiness grant. */
export interface NativeExecutionEffects {
  requested_type: string;
  effective_type: string;
  effective_limit_price: number | null;
  trailing_active: boolean;
  limitations: string[];
}

/**
 * Additive evidence on an object placement acknowledgement. Keep the existing
 * camel-case client contract; native aliases and observations are optional.
 * placeOrder selects known top-level evidence from the native scalar-data
 * envelope with its original orderid. Legacy scalars without that evidence,
 * bare objects and object-data wrappers remain unchanged at runtime.
 * Never infer fills/terminal children from ACK IDs, or exchange children from
 * GTT resource IDs. Absence is not a verified empty collection.
 */
export interface OrderPlacementAcknowledgement {
  orderId: string;
  order_id?: string;
  orderid?: string;
  order_ids?: string[];
  gtt_order_ids?: string[];
  child_order_id?: string | null;
  execution_effects?: NativeExecutionEffects;
  broker_response?: PlacementJsonValue;
}
