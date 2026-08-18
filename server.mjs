import { createServer } from 'node:http';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { createServer as createViteServer } from 'vite';

const root = path.dirname(new URL(import.meta.url).pathname);
const port = Number(process.env.PORT || 4141);
const isProduction = process.env.NODE_ENV === 'production';

function expandHome(value) {
  return value === '~' ? os.homedir() : value.replace(/^~\//, `${os.homedir()}/`);
}

async function walk(dir, files = []) {
  let entries;
  try { entries = await fs.readdir(dir, { withFileTypes: true }); }
  catch { return files; }

  await Promise.all(entries.map(async entry => {
    const target = path.join(dir, entry.name);
    if (entry.isDirectory()) await walk(target, files);
    else if (entry.name.endsWith('.jsonl')) {
      const stat = await fs.stat(target);
      files.push({ target, mtime: stat.mtimeMs, size: stat.size });
    }
  }));
  return files;
}

async function readTail(file, maxBytes = 512 * 1024) {
  const start = Math.max(0, file.size - maxBytes);
  const handle = await fs.open(file.target, 'r');
  try {
    const buffer = Buffer.alloc(file.size - start);
    await handle.read(buffer, 0, buffer.length, start);
    const content = buffer.toString('utf8');
    return start ? content.slice(content.indexOf('\n') + 1) : content;
  } finally { await handle.close(); }
}

function normalizeWindow(window, source) {
  if (!window || typeof window.used_percent !== 'number') return null;
  return {
    usedPercent: window.used_percent,
    windowMinutes: window.window_minutes,
    resetsAt: window.resets_at ? new Date(window.resets_at * 1000).toISOString() : null,
    source,
  };
}

async function getCodexUsage(home) {
  const sessionsRoot = path.join(home, 'sessions');
  const files = (await walk(sessionsRoot)).sort((a, b) => b.mtime - a.mtime).slice(0, 40);
  let newest = null;

  for (const file of files) {
    const lines = (await readTail(file)).trim().split('\n').reverse();
    for (const line of lines) {
      try {
        const event = JSON.parse(line);
        const limits = event?.payload?.rate_limits;
        if (!limits) continue;
        const timestamp = Date.parse(event.timestamp || 0);
        if (!newest || timestamp > newest.timestamp) newest = { limits, timestamp };
        break;
      } catch { /* Skip incomplete or unrelated log lines. */ }
    }
  }

  if (!newest) {
    return { available: false, message: 'No usage snapshot found in this Codex home.' };
  }

  const windows = [
    normalizeWindow(newest.limits.primary, 'primary'),
    normalizeWindow(newest.limits.secondary, 'secondary'),
  ].filter(Boolean);

  return {
    available: true,
    updatedAt: new Date(newest.timestamp).toISOString(),
    planType: newest.limits.plan_type || null,
    limitId: newest.limits.limit_id || 'codex',
    credits: newest.limits.credits || null,
    windows,
  };
}

async function getAntigravityUsage(home) {
  const logPath = path.join(home, 'logs', 'language_server.log');
  try {
    const stat = await fs.stat(logPath);
    const content = await readTail({ target: logPath, size: stat.size });
    const matches = [...content.matchAll(/Individual quota reached[\s\S]{0,160}?Resets in (\d+)h(\d+)m(\d+)s/g)];
    if (!matches.length) return { available: false, message: 'No quota event found in recent Agy logs.' };
    const latest = matches.at(-1);
    const duration = (+latest[1] * 3600 + +latest[2] * 60 + +latest[3]) * 1000;
    const resetsAt = new Date(stat.mtimeMs + duration);
    if (resetsAt <= new Date()) return { available: false, message: 'The last quota event is stale; use Agy once to refresh it.' };
    return {
      available: true,
      updatedAt: new Date(stat.mtimeMs).toISOString(),
      limitReached: true,
      windows: [{ usedPercent: 100, windowMinutes: Math.round(duration / 60000), resetsAt: resetsAt.toISOString(), source: 'quota-event' }],
    };
  } catch { return { available: false, message: 'Agy is installed, but no readable usage log is available.' }; }
}

async function getAccounts() {
  const definitions = JSON.parse(await fs.readFile(path.join(root, 'accounts.json'), 'utf8'));
  return Promise.all(definitions.map(async account => {
    const home = expandHome(account.home);
    let usage;
    if (account.provider === 'codex') usage = await getCodexUsage(home);
    else if (account.provider === 'antigravity') usage = await getAntigravityUsage(home);
    else usage = { available: false, message: 'Claude does not expose continuous plan usage in local logs. Run /usage in Claude to check it.' };
    return { id: account.id, name: account.name, provider: account.provider, configuredHome: account.home, ...usage };
  }));
}

const vite = isProduction ? null : await createViteServer({ root, server: { middlewareMode: true }, appType: 'spa' });

const server = createServer(async (req, res) => {
  if (req.url === '/api/usage') {
    res.setHeader('Content-Type', 'application/json');
    res.setHeader('Cache-Control', 'no-store');
    try { res.end(JSON.stringify({ available: true, accounts: await getAccounts() })); }
    catch (error) {
      res.statusCode = 500;
      res.end(JSON.stringify({ available: false, error: error.message }));
    }
    return;
  }

  if (vite) return vite.middlewares(req, res);

  const requested = req.url === '/' ? 'index.html' : req.url.split('?')[0].replace(/^\//, '');
  const target = path.join(root, 'dist', requested);
  try {
    const data = await fs.readFile(target);
    const ext = path.extname(target);
    const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.svg': 'image/svg+xml' };
    res.setHeader('Content-Type', types[ext] || 'application/octet-stream');
    res.end(data);
  } catch {
    try {
      res.setHeader('Content-Type', 'text/html');
      res.end(await fs.readFile(path.join(root, 'dist', 'index.html')));
    } catch {
      res.statusCode = 404;
      res.end('Run npm run build before npm start.');
    }
  }
});

server.listen(port, '127.0.0.1', () => {
  console.log(`Agent Meter running at http://localhost:${port}`);
});
