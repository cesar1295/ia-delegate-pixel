import {spawn} from 'node:child_process';
import {mkdtemp, mkdir, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import net from 'node:net';
const [browser, port, output, rawPaths] = process.argv.slice(2);
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const socket = net.createServer();
await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
const debugPort = socket.address().port;
await new Promise(resolve => socket.close(resolve));
const profile = await mkdtemp(join(tmpdir(), 'aidelegate-visual-'));
const proc = spawn(browser, ['--headless=new', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
  `--remote-debugging-port=${debugPort}`, `--user-data-dir=${profile}`, 'about:blank'], {stdio: 'ignore'});
proc.on('error', () => {});
let ws, context;
const errors = [], shots = [];
try {
  let target;
  for (let i = 0; i < 100; i++) {
    try {
      const tabs = await (await fetch(`http://127.0.0.1:${debugPort}/json/list`)).json();
      target = tabs.find(tab => tab.type === 'page');
      if (target) break;
    } catch {}
    await delay(100);
  }
  if (!target) throw new Error('Chromium no abrió CDP');
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {ws.onopen = resolve; ws.onerror = reject;});
  let sequence = 0;
  const pending = new Map();
  let loaded;
  ws.onmessage = event => {
    const msg = JSON.parse(event.data);
    if (msg.id) {
      const call = pending.get(msg.id);
      pending.delete(msg.id);
      if (call) msg.error ? call.reject(new Error(JSON.stringify(msg.error))) : call.resolve(msg.result);
    }
    if (msg.method === 'Page.loadEventFired') loaded?.();
    if (!context) return;
    if (msg.method === 'Runtime.exceptionThrown') {
      const d = msg.params.exceptionDetails;
      errors.push({...context, text: d.exception?.description || d.text});
    }
    if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
      errors.push({...context, text: msg.params.args.map(a => a.description || a.value || '').join(' ')});
    }
  };
  function call(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++sequence;
      pending.set(id, {resolve, reject});
      ws.send(JSON.stringify({id, method, params}));
    });
  }
  await call('Page.enable');
  await call('Runtime.enable');
  await mkdir(join(output, 'screens'), {recursive: true});
  for (const [index, path] of JSON.parse(rawPaths).entries()) {
    for (const [size, width, height] of [['escritorio',1280,800], ['movil',390,844]]) {
      context = {path, size};
      await call('Emulation.setDeviceMetricsOverride', {width, height, deviceScaleFactor: 1, mobile: size === 'movil'});
      let timer;
      const load = new Promise((resolve, reject) => {
        loaded = resolve;
        timer = setTimeout(() => reject(new Error(`No cargó ${path}`)), 30000);
      });
      try {
        await call('Page.navigate', {url: `http://127.0.0.1:${port}${path}`});
        await load;
      } finally { clearTimeout(timer); }
      await delay(2000);
      const shot = await call('Page.captureScreenshot', {format: 'png'});
      const slug = path.replace(/[^a-zA-Z0-9_-]+/g, '-').replace(/^-|-$/g, '') || 'inicio';
      const file = `screens/${slug}-${size}.png`;
      await writeFile(join(output, file), Buffer.from(shot.data, 'base64'));
      shots.push(file);
    }
  }
  process.stdout.write(JSON.stringify({shots, errors}));
} catch (error) {
  errors.push({path: context?.path || "", size: context?.size || "", text: String(error)});
  process.stdout.write(JSON.stringify({shots, errors}));
} finally {
  ws?.close();
  proc.kill('SIGTERM');
  await Promise.race([new Promise(resolve => proc.once('exit', resolve)), delay(3000)]);
  if (proc.exitCode === null) proc.kill('SIGKILL');
  await rm(profile, {recursive: true, force: true, maxRetries: 5, retryDelay: 100});
}
