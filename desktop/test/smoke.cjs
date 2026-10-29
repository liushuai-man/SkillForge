// Run with Electron, not Node: npm --prefix desktop run smoke -- --data-root <new test directory>
const { app, BrowserWindow } = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const dataIndex = process.argv.indexOf('--data-root');
assert.ok(dataIndex >= 0, 'Use an isolated --data-root for the smoke check');
const data = path.resolve(process.argv[dataIndex + 1]);
assert.ok(!fs.existsSync(data), 'Smoke data directory must not already exist');
require('../main.cjs');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function waitFor(check, label) {
  const until = Date.now() + 45000;
  while (Date.now() < until) {
    const result = await check();
    if (result) return result;
    await delay(150);
  }
  throw new Error(`Timed out: ${label}`);
}
app.whenReady().then(async () => {
  const win = await waitFor(() => BrowserWindow.getAllWindows()[0], 'window');
  await waitFor(() => win.webContents.getURL().startsWith('http://'), 'local URL');
  await waitFor(() => win.webContents.executeJavaScript("document.body.innerText.includes('添加 Skill 目录')"), 'welcome page');
  const base = new URL(win.webContents.getURL()).origin;
  assert.equal(await win.webContents.executeJavaScript('typeof require'), 'undefined');
  const skill = path.join(data, 'generated-skill');
  fs.mkdirSync(skill, { recursive: true });
  const file = path.join(skill, 'SKILL.md');
  fs.writeFileSync(file, '# Desktop smoke\noriginal line\n');
  const created = await fetch(base + '/api/workspaces', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: skill }),
  }).then(r => r.json());
  assert.equal(created.ok, true);
  const ws = created.data.workspace.workspace_id;
  await win.webContents.reload();
  await waitFor(() => win.webContents.executeJavaScript("document.querySelectorAll('.cm-editor').length === 2"), 'CodeMirror full text');
  fs.writeFileSync(file, '# Desktop smoke\nchanged line\n');
  await waitFor(() => win.webContents.executeJavaScript("document.body.innerText.includes('changed line')"), 'save and SSE refresh');
  const comparison = await fetch(`${base}/api/workspaces/${ws}/compare`).then(r => r.json());
  assert.ok(comparison.data.files.some(f => f.path === 'SKILL.md'));
  const shot = await win.webContents.capturePage();
  fs.writeFileSync(path.join(data, 'desktop.png'), shot.toPNG());
  const originalId = win.id;
  win.close();
  assert.equal(win.isDestroyed(), false);
  assert.equal(win.isVisible(), false);
  assert.equal((await fetch(base + '/api/health').then(r => r.json())).ok, true);
  // A real second process must hand off to the same window and immediately exit.
  const second = spawn(process.execPath, [path.resolve(__dirname, '..'), '--data-root', data], { stdio: 'ignore' });
  await new Promise((resolve, reject) => { second.on('error', reject); second.on('exit', code => code === 0 ? resolve() : reject(Error(`second exit ${code}`))); });
  await waitFor(() => win.isVisible(), 'second launch restores hidden window');
  assert.equal(BrowserWindow.getAllWindows().length, 1);
  assert.equal(win.id, originalId);
  console.log(JSON.stringify({ ok: true, base, workspace: ws, screenshot: path.join(data, 'desktop.png'),
    checks: ['local window', 'sandbox', 'full text', 'save/SSE', 'tray hide', 'single instance'] }));
  app.quit();
}).catch(error => { console.error(error); app.exit(1); });
