/// <reference types="vite/client" />

// SECURITY: VITE_OPENALGO_API_KEY is intentionally NOT declared. Vite inlines
// VITE_* env vars into the production JS bundle at build time, which would
// leak the broker API key to anyone who downloads the static site. The key
// is set via the in-app Settings → Connection flow only — that path
// persists to ~/.flinttrade/workspace.json server-side and never crosses
// the Vite build boundary.
interface ImportMetaEnv {
  readonly VITE_OPENALGO_HOST: string
  readonly VITE_OPENALGO_WS: string
  readonly VITE_OPENALGO_WS_PORT: string
  readonly VITE_FLINTTRADE_VERSION: string
  readonly DEV: boolean
  readonly MODE: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

declare module "plotly.js-dist-min" {
  import type { PlotlyStatic } from "plotly.js"

  const Plotly: PlotlyStatic
  export default Plotly
}
