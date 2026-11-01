const { contextBridge, ipcRenderer } = require('electron');

/**
 * Preload bridge.
 *
 * The renderer runs with contextIsolation on and nodeIntegration off, so this is
 * the only channel it has to the main process. Keep it small and explicit.
 */
contextBridge.exposeInMainWorld('starAligner', {
  apiOrigin: process.argv.find(arg => arg.startsWith('--api-origin='))?.slice('--api-origin='.length),
  platform: process.platform,

  /**
   * Show the OS-native directory chooser and resolve to the chosen path.
   * macOS gets a Finder panel, Windows an Explorer folder picker, Linux a
   * GTK/Qt file chooser. Resolves to null if the user cancels.
   */
  pickDirectory: (purpose = 'source') => ipcRenderer.invoke('dialog:pickDirectory', purpose),
});
