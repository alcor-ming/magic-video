// Real Studio HTTP handlers; isolated files only, no WorkStore or production data.
// Run as a non-root Linux/macOS user with HF_PACKAGE pointing to existing Studio 0.8.150.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {createHash} from 'node:crypto';
import {spawn} from 'node:child_process';
import {once} from 'node:events';

assert(['linux', 'darwin'].includes(process.platform), 'This fixture requires POSIX permissions');
assert.notEqual(process.getuid(), 0, 'Root bypasses readonly file permissions');
const {HF_PACKAGE} = process.env;
assert(HF_PACKAGE, 'Set HF_PACKAGE to the installed HyperFrames package');
assert.equal(JSON.parse(await fs.readFile(path.join(HF_PACKAGE, 'package.json'))).version, '0.8.150');
const root = await fs.mkdtemp(path.join(os.tmpdir(), 'hf-studio-readonly-'));
const project = path.join(root, 'fixture');
await fs.mkdir(path.join(project, 'compositions'), {recursive: true});
const files = ['index.html', 'compositions/child.html'];
const source = id => `<!doctype html><html><head><title>${id}</title></head><body>
<main data-composition-id="${id}" data-width="960" data-height="540" data-duration="2" data-no-timeline="true">
<p id="evidence">Readonly review fixture</p></main></body></html>`;
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const socket = net.createServer();
socket.listen(0, '127.0.0.1'); await once(socket, 'listening');
const port = socket.address().port;
await new Promise(resolve => socket.close(resolve));
let server, log = '';
const checks = [];
try {
  for (const readonly of [false, true]) {
    for (const file of files) {
      await fs.writeFile(path.join(project, file), source(file));
      await fs.chmod(path.join(project, file), readonly ? 0o444 : 0o644);
    }
    const before = await Promise.all(files.map(file => fs.readFile(path.join(project, file)).then(hash)));
    server = spawn(process.execPath, [path.join(HF_PACKAGE, 'dist/cli.js'), 'preview', project,
      '--port', String(port), '--foreground', '--no-open', '--no-proxy'], {
      env: {...process.env, HOME: root, XDG_CONFIG_HOME: root, XDG_CACHE_HOME: root, XDG_STATE_HOME: root,
        DO_NOT_TRACK: '1', HYPERFRAMES_NO_TELEMETRY: '1'},
    });
    server.stdout.on('data', data => { log += data; });
    server.stderr.on('data', data => { log += data; });
    const base = `http://127.0.0.1:${port}`;
    let ready = false;
    for (let i = 0; i < 100; i++) {
      try { if ((await fetch(base)).ok) { ready = true; break; } } catch {}
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert(ready, log);
    const endpoints = ['/api/projects/fixture/preview', '/api/projects/fixture/preview/comp/compositions/child.html'];
    for (const [index, endpoint] of endpoints.entries()) {
      const response = await fetch(base + endpoint);
      assert.equal(response.status, 200, `${endpoint}: ${await response.clone().text()}`);
      assert.match(await response.text(), /data-hf-id=/, 'IDs remain available in the served HTML');
      const disk = await fs.readFile(path.join(project, files[index]));
      if (readonly) {
        assert.equal(hash(disk), before[index], `${files[index]} must retain its original digest`);
        assert.doesNotMatch(disk.toString(), /data-hf-id=/);
      } else {
        assert.notEqual(hash(disk), before[index], `${files[index]} reproduces writable source mutation`);
        assert.match(disk.toString(), /data-hf-id=/);
      }
      checks.push({readonly, file: files[index], diskChanged: hash(disk) !== before[index], responseHasIds: true});
    }
    server.kill('SIGTERM'); await once(server, 'exit'); server = null;
  }
  console.log(JSON.stringify({actualStudio: '0.8.150', uid: process.getuid(), checks, evidence: root}));
} finally {
  if (server && server.exitCode === null) { server.kill('SIGTERM'); await once(server, 'exit'); }
}
