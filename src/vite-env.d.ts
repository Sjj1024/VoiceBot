/// <reference types="vite/client" />

interface ImportMetaEnv {
    readonly VITE_WHISPER_URL?: string
}

interface ImportMeta {
    readonly env: ImportMetaEnv
}
