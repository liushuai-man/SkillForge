const test = require('node:test');
const assert = require('node:assert/strict');
const { localUrl, startBackend } = require('../backend.cjs');

test('only a root loopback HTTP address can be loaded', () => {
  for (const url of ['https://127.0.0.1:1/', 'http://example.com:1/',
    'http://user@127.0.0.1:1/', 'http://127.0.0.1:1/api', 'http://127.0.0.1:1/?x=1']) {
    assert.throws(() => localUrl(url));
  }
  assert.equal(localUrl('http://127.0.0.1:8756/'), 'http://127.0.0.1:8756');
});

test('ready handshake and EOF shutdown use a real child process', async () => {
  const backend = startBackend(process.execPath, ['-e', `
    console.log('SKILLFORGE_DESKTOP {"base_url":"http://127.0.0.1:8756","owned":true}');
    process.stdin.resume(); process.stdin.on('end', () => process.exit(0));
  `], {}, () => assert.fail('intentional exit must not signal failure'));
  assert.equal(await backend.url, 'http://127.0.0.1:8756');
  const exited = new Promise(resolve => backend.child.once('exit', resolve));
  backend.stop();
  assert.equal(await exited, 0);
});

test('startup failure preserves stderr diagnostics', async () => {
  const backend = startBackend(process.execPath, ['-e',
    'console.error("data root busy"); process.exit(1);'], {}, () => {});
  await assert.rejects(backend.url, /data root busy/);
});

test('reject remote ready handshake and close the child', async () => {
  const backend = startBackend(process.execPath, ['-e', `
    console.log('SKILLFORGE_DESKTOP {"base_url":"http://example.com:8756"}');
    process.stdin.resume(); process.stdin.on('end', () => process.exit(0));
  `], {}, () => {});
  await assert.rejects(backend.url, /本机/);
});
