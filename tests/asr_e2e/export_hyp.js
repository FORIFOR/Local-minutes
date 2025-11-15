import fs from 'fs';
import path from 'path';

function parseArgs() {
  const defaults = {
    base: 'http://127.0.0.1:3002'
  };
  const args = process.argv.slice(2);
  for (const arg of args) {
    if (!arg.startsWith('--')) continue;
    const body = arg.slice(2);
    if (!body) continue;
    const eq = body.indexOf('=');
    if (eq === -1) {
      defaults[body] = true;
    } else {
      defaults[body.slice(0, eq)] = body.slice(eq + 1);
    }
  }
  if (!defaults.token && process.env.M4_TOKEN) {
    defaults.token = process.env.M4_TOKEN;
  }
  return defaults;
}

async function main() {
  const opts = parseArgs();
  if (!opts.event) {
    console.error('イベントIDを --event=... で指定してください');
    process.exit(1);
  }

  const baseUrl = opts.base || 'http://127.0.0.1:3002';
  const url = new URL(`/api/events/${opts.event}/minutes`, baseUrl);
  const headers = { Accept: 'application/json' };
  if (opts.token) {
    headers.Authorization = `Bearer ${opts.token}`;
  }

  console.log(`[export:hyp] fetch ${url.toString()}`);
  const res = await fetch(url, { headers });
  if (!res.ok) {
    console.error(`[export:hyp] API error ${res.status}`);
    const body = await res.text();
    if (body) console.error(body);
    process.exit(1);
  }
  const data = await res.json();
  const md = (data && (data.md ?? data.minutes ?? '')).trim();

  const outDir = path.join(process.cwd(), 'tests', 'asr_e2e', 'out');
  fs.mkdirSync(outDir, { recursive: true });
  const dst = path.join(outDir, 'hyp.txt');
  fs.writeFileSync(dst, md ? `${md}\n` : '', { encoding: 'utf-8' });
  console.log(`[export:hyp] saved -> ${dst}`);
}

main().catch((err) => {
  console.error('[export:hyp] error', err);
  process.exit(1);
});
