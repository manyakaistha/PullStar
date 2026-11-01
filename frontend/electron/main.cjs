const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const { findPython } = require('./python.cjs');

let mainWindow;
let pythonProcess;
let backendOrigin;
let quitting = false;
const appIconPath = path.join(__dirname, '../resources/icons/icon.png');

ipcMain.handle('dialog:pickDirectory', async (event, purpose = 'source') => {
  if (event.sender !== mainWindow?.webContents) throw new Error('Unknown renderer');
  const result = await dialog.showOpenDialog(mainWindow, {
    title: purpose === 'converted' ? 'Choose where converted frames should be saved' : 'Choose the folder containing your photos',
    buttonLabel: 'Use This Folder',
    properties: ['openDirectory', 'createDirectory'],
  });
  return result.canceled ? null : result.filePaths[0] ?? null;
});

async function startPythonBackend() {
  const root = path.resolve(__dirname, '../..');
  const working = app.isPackaged ? app.getPath('userData') : root;
  fs.mkdirSync(working, { recursive: true });
  const executable = app.isPackaged
    ? path.join(process.resourcesPath, 'backend', 'pullstar-backend')
    : findPython(root, process.env.VIRTUAL_ENV);
  const args = app.isPackaged ? [] : ['-m', 'backend.desktop_entry'];
  // Vite's development proxy uses a fixed port; installed builds allocate their own.
  if (process.env.VITE_DEV_SERVER_URL) args.push('--port', '8000');
  const logPath = path.join(app.getPath('userData'), 'backend.log');
  // Keep at most one previous session instead of growing logs indefinitely.
  if (fs.existsSync(logPath)) fs.renameSync(logPath, `${logPath}.previous`);
  const log = fs.createWriteStream(logPath);
  pythonProcess = spawn(executable, args, {
    cwd: working,
    env: { ...process.env, MPLCONFIGDIR: path.join(app.getPath('userData'), 'matplotlib'), MPLBACKEND: 'Agg', PYTHONUNBUFFERED: '1' },
    detached: process.platform !== 'win32',
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  pythonProcess.stderr.pipe(log, { end: false });
  pythonProcess.stdout.pipe(log, { end: false });
  let ended = false;
  pythonProcess.on('error', () => { ended = true; });
  pythonProcess.on('exit', () => { ended = true; log.end(); });
  try {
    backendOrigin = await new Promise((resolve, reject) => {
      let buffer = '';
      const timer = setTimeout(() => reject(new Error(`Backend startup timed out. See ${logPath}`)), 90000);
      const fail = error => { clearTimeout(timer); reject(error); };
      pythonProcess.once('error', fail);
      pythonProcess.once('exit', code => fail(new Error(`Backend exited (${code}). See ${logPath}`)));
      pythonProcess.stdout.on('data', chunk => {
        buffer = (buffer + chunk.toString()).slice(-8192);
        const match = buffer.match(/PULLSTAR_BACKEND=(http:\/\/127\.0\.0\.1:\d+)/);
        if (match) { clearTimeout(timer); resolve(match[1]); }
      });
    });
    const deadline = Date.now() + 30000;
    while (Date.now() < deadline && !ended) {
      try {
        const response = await fetch(backendOrigin, { signal: AbortSignal.timeout(1000) });
        if (response.ok && (await response.json()).status === 'PullStar API is running') return;
      } catch { /* wait for Uvicorn startup */ }
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    throw new Error(`Backend did not become ready. See ${logPath}`);
  } catch (error) {
    stopBackend();
    throw error;
  }
}

function stopBackend() {
  if (!pythonProcess || pythonProcess.exitCode !== null) return;
  try {
    if (process.platform === 'win32') pythonProcess.kill();
    else process.kill(-pythonProcess.pid, 'SIGTERM');
  } catch { /* process has already exited */ }
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1360, height: 900, minWidth: 900, minHeight: 650,
    backgroundColor: '#111111', title: 'PullStar', icon: appIconPath,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true,
      nodeIntegration: false, sandbox: true,
      additionalArguments: [`--api-origin=${backendOrigin}`],
    },
  });
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  mainWindow.webContents.on('will-navigate', event => event.preventDefault());
  if (!app.isPackaged && process.env.VITE_DEV_SERVER_URL) await mainWindow.loadURL(process.env.VITE_DEV_SERVER_URL);
  else await mainWindow.loadFile(path.join(__dirname, '../dist/index.html'));
  mainWindow.on('closed', () => { mainWindow = null; });
  if (process.env.PULLSTAR_SMOKE_OUTPUT) {
    const result = await mainWindow.webContents.executeJavaScript(`(async () => ({brand: document.querySelector('.studio-brand strong')?.textContent, health: await fetch(window.starAligner.apiOrigin).then(r => r.json()), errors: document.body.innerText.includes('Something went wrong')}))()`);
    const output = process.env.PULLSTAR_SMOKE_OUTPUT;
    fs.writeFileSync(`${output}.json`, JSON.stringify(result, null, 2));
    fs.writeFileSync(`${output}.png`, (await mainWindow.webContents.capturePage()).toPNG());
    app.quit();
  }
}

if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => { if (mainWindow) { mainWindow.restore(); mainWindow.focus(); } });
  app.whenReady().then(async () => {
    if (process.platform === 'darwin') app.dock?.setIcon(appIconPath);
    try { await startPythonBackend(); await createWindow(); }
    catch (error) { dialog.showErrorBox('PullStar could not start', error.message); app.quit(); }
    app.on('activate', () => {
      if (!quitting && BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });
}
app.on('window-all-closed', () => app.quit());
app.on('before-quit', event => {
  if (quitting || !pythonProcess || pythonProcess.exitCode !== null) return;
  event.preventDefault();
  quitting = true;
  const finish = () => { clearTimeout(timer); app.exit(0); };
  const timer = setTimeout(() => {
    try {
      if (process.platform === 'win32') pythonProcess.kill('SIGKILL');
      else process.kill(-pythonProcess.pid, 'SIGKILL');
    } catch { /* service already stopped */ }
    finish();
  }, 3000);
  pythonProcess.once('exit', finish);
  stopBackend();
});
