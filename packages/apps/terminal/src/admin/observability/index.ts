/**
 * Public entry point for the /admin/observability aggregator screen.
 *
 * Re-exports the dashboard component so the route registry can lazy-load it
 * with a clean import path. The dashboard itself imports each widget directly
 * from its real path (no barrel imports inside the component).
 */

export { ObservabilityDashboard, default } from "./ObservabilityDashboard";
