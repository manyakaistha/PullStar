// Build-time SVG rasterization using the project's own Chromium renderer.
const { app, BrowserWindow } = require('electron');
const fs = require('node:fs');
const [source, destination] = process.argv.slice(2);
app.disableHardwareAcceleration();
app.commandLine.appendSwitch('force-device-scale-factor', '2');
app.whenReady().then(async () => {
  const window = new BrowserWindow({
    width: 1024, height: 1024, useContentSize: true, frame: false,
    show: false, transparent: true, backgroundColor: '#00000000',
    webPreferences: { offscreen: true, contextIsolation: true, nodeIntegration: false },
  });
  try {
    await window.loadFile(source);
    await window.webContents.executeJavaScript('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))');
    const image = await window.webContents.capturePage({ x: 0, y: 0, width: 1024, height: 1024 });
    fs.writeFileSync(destination, image.toPNG());
    app.exit(0);
  } catch (error) {
    console.error(error);
    app.exit(1);
  }
});
