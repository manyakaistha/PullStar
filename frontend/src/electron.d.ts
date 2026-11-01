export {}

declare global {
  interface Window {
    /**
     * Bridge exposed by electron/preload.cjs. Only present when running inside
     * the Electron shell; absent in a plain browser (e.g. `npm run dev`).
     */
    starAligner?: {
      apiOrigin: string
      platform: NodeJS.Platform | string
      /** Resolves to the chosen directory path, or null if cancelled. */
      pickDirectory: (purpose?: "source" | "converted") => Promise<string | null>
    }
  }
}
