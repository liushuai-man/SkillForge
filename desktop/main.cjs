const { app, BrowserWindow, Menu, Tray, nativeImage, dialog } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const { startBackend } = require('./backend.cjs');

let window;
let tray;
let backend;
let quitting = false;
let exiting = false;
const dataIndex = process.argv.indexOf('--data-root');
const dataRoot = dataIndex >= 0 ? process.argv[dataIndex + 1] : undefined;
if (dataIndex >= 0 && (!dataRoot || dataRoot.startsWith('--'))) {
  dialog.showErrorBox('留痕', '--data-root 后需要指定数据目录');
  app.exit(1);
}
// Separate desktop instances can use separate data roots; the service writer lock remains authoritative.
if (dataRoot) app.setPath('userData', path.resolve(dataRoot, 'desktop'));
app.setName('留痕');

function showWindow() {
  if (!window || window.isDestroyed()) return;
  if (window.isMinimized()) window.restore();
  window.show();
  window.focus();
}

function backendCommand() {
  if (app.isPackaged) {
    return { command: path.join(process.resourcesPath, 'python', 'python.exe'), args: ['-I', '-X', 'utf8', '-m', 'skillforge_vm.cli.desktop'] };
  }
  const root = path.resolve(__dirname, '..');
  const python = process.env.SKILLFORGE_DESKTOP_PYTHON || path.join(root, '.venv',
    process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  if (!fs.existsSync(python)) throw new Error('缺少 Python 环境，请先在项目根执行 uv sync。');
  if (process.platform === 'win32' && !process.env.SKILLFORGE_DESKTOP_PYTHON) {
    const venv = path.join(root, '.venv');
    const config = fs.readFileSync(path.join(venv, 'pyvenv.cfg'), 'utf8');
    const home = config.match(/^home\s*=\s*(.+)$/m)?.[1]?.trim();
    if (!home) throw new Error('Python 虚拟环境缺少 home 配置，请重新执行 uv sync。');
    const packages = path.join(venv, 'Lib', 'site-packages');
    const bootstrap = `import site,runpy; site.addsitedir(${JSON.stringify(packages)}); runpy.run_module('skillforge_vm.cli.desktop',run_name='__main__',alter_sys=True)`;
    return { command: path.join(home, 'python.exe'), args: ['-I', '-X', 'utf8', '-c', bootstrap] };
  }
  return { command: python, args: ['-m', 'skillforge_vm.cli.desktop'] };
}

function createWindow(base) {
  const icon = nativeImage.createFromPath(path.join(__dirname, 'icon.png'));
  window = new BrowserWindow({
    title: '留痕', width: 1440, height: 940, minWidth: 760, minHeight: 540,
    show: false, icon, backgroundColor: '#181a20',
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, spellcheck: false },
  });
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { label: '应用', submenu: [
      { label: '显示窗口', click: showWindow },
      { label: '退出 留痕', click: () => app.quit() },
    ] },
    { label: '编辑', submenu: [{ label: '复制', role: 'copy' }, { label: '全选', role: 'selectAll' }] },
    { label: '视图', submenu: [{ label: '重新加载', role: 'reload' }, { label: '恢复原始大小', role: 'resetZoom' }, { label: '放大', role: 'zoomIn' }, { label: '缩小', role: 'zoomOut' }] },
  ]));
  // The renderer consumes the existing HTTP API without a privileged preload bridge.
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  const allowed = target => { try { return new URL(target).origin === base; } catch { return false; } };
  window.webContents.on('will-navigate', (event, target) => { if (!allowed(target)) event.preventDefault(); });
  window.webContents.on('will-redirect', (event, target) => { if (!allowed(target)) event.preventDefault(); });
  window.webContents.session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  window.webContents.session.setPermissionCheckHandler(() => false);
  window.once('ready-to-show', showWindow);
  window.on('close', event => {
    if (!quitting && tray) { event.preventDefault(); window.hide(); }
  });
  tray = new Tray(icon);
  tray.setToolTip('留痕 · 关闭窗口后继续监听');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: '打开 留痕', click: showWindow },
    { label: '退出', click: () => app.quit() },
  ]));
  tray.on('double-click', showWindow);
  return window.loadURL(base + '/');
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', showWindow);
  app.on('activate', showWindow);
  app.on('before-quit', event => {
    quitting = true;
    if (!backend || exiting || backend.child.exitCode !== null || !backend.child.pid) return;
    event.preventDefault();
    exiting = true;
    backend.child.once('exit', () => app.quit());
    backend.stop();
    // Python's stdin watchdog also handles parent crashes. Do not kill another service by PID.
    const timer = setTimeout(() => { backend.child.kill(); app.quit(); }, 10000);
    timer.unref();
  });
  app.whenReady().then(async () => {
    const config = backendCommand();
    const args = [...config.args, '--parent-pid', String(process.pid)];
    if (dataRoot) args.push('--data-root', path.resolve(dataRoot));
    backend = startBackend(config.command, args, {
      cwd: app.isPackaged ? process.resourcesPath : path.resolve(__dirname, '..'),
      env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' },
    }, error => { dialog.showErrorBox('本机服务连接中断', error.message); app.quit(); });
    await createWindow(await backend.url);
  }).catch(error => { dialog.showErrorBox('留痕 启动失败', error.message); app.quit(); });
}
