/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_OPENALGO_HOST: string
  readonly VITE_OPENALGO_API_KEY: string
  readonly VITE_OPENALGO_WS: string
  readonly DEV: boolean
  readonly MODE: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
