/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, unknown>
  export default component
}

interface ImportMetaEnv {
    readonly VITE_WHISPER_URL?: string
    readonly VITE_OPENCLAW_URL?: string
    readonly VITE_OPENCLAW_API_KEY?: string
    readonly VITE_OPENCLAW_MODEL?: string
}

interface ImportMeta {
    readonly env: ImportMetaEnv
}
