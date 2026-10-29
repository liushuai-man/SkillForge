const { spawn } = require('node:child_process');
const { createInterface } = require('node:readline');

function localUrl(value) {
  const url = new URL(value);
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
      || !url.port || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('后端返回了无效的本机服务地址');
  }
  return url.origin;
}

function startBackend(command, args, options, onFailure) {
  const child = spawn(command, args, { ...options, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
  let stopping = false;
  let ready = false;
  let diagnostics = '';
  const lines = createInterface({ input: child.stdout });
  // Keep an unavailable backend from producing an unhandled pipe error during shutdown.
  child.stdin.on('error', () => {});
  const url = new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new Error('等待本机服务启动超时。请检查依赖和数据目录占用。'));
      stop();
    }, 60000);
    child.stderr.on('data', chunk => { diagnostics = (diagnostics + chunk.toString()).slice(-5000); });
    lines.on('line', line => {
      if (!line.startsWith('SKILLFORGE_DESKTOP ') || ready) return;
      try {
        const payload = JSON.parse(line.slice('SKILLFORGE_DESKTOP '.length));
        const base = localUrl(payload.base_url);
        ready = true;
        clearTimeout(timer);
        resolve(base);
      } catch (error) {
        clearTimeout(timer);
        reject(error);
        stop();
      }
    });
    child.once('error', error => { clearTimeout(timer); reject(error); });
    child.once('exit', code => {
      clearTimeout(timer);
      lines.close();
      const error = new Error(`本机服务已退出（${code}）。\n${diagnostics}`);
      if (!ready) reject(error);
      else if (!stopping) onFailure(error);
    });
  });
  function stop() {
    stopping = true;
    // EOF requests graceful shutdown; reused services are left running by Python.
    child.stdin.end();
  }
  return { url, stop, child };
}

module.exports = { localUrl, startBackend };
