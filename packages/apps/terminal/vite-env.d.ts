/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_FLINTTRADE_VERSION: string
  readonly DEV: boolean
  readonly MODE: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
