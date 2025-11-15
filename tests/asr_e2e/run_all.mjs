import { spawn } from 'child_process';
import fs from 'fs';
import { once } from 'events';

function logStream(stream, prefix) {
  if (!stream) return;
  stream.on('data', (chunk) => {
    process.stdout.write(chunk.toString().split(/\r?\n/).filter(Boolean).map((line) => `[${prefix}] ${line}\n`).join(''));
  });
}

function startSink() {
  const child = spawn('node', ['tests/asr_e2e/ws_sink.js'], { stdio: 'pipe' });
  logStream(child.stdout, 'sink');
  logStream(child.stderr, 'sink!');
  return child;
}

function runCmd(command, args, name, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: 'pipe', ...options });
    logStream(child.stdout, name);
    logStream(child.stderr, `${name}!`);
    child.on('error', reject);
    child.on('close', (code) => {
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`${name} exited with code ${code}`));
      }
    });
  });
}

async function main() {
  fs.mkdirSync('tests/asr_e2e/out', { recursive: true });

  const sink = startSink();
  await new Promise((res) => setTimeout(res, 500));

  const wavPath = 'tests/asr_e2e/assets/yt.wav';
  if (!fs.existsSync(wavPath)) {
    throw new Error(`${wavPath} が存在しません。YouTube音源などを 16kHz/mono/16bit に変換して配置してください（例: npm run yt:audio -- --url=... && npm run wav:fix16k）`);
  }

  await runCmd('node', ['tests/asr_e2e/ws_sender.js', `--wav=${wavPath}`, '--url=ws://127.0.0.1:8765'], 'sender');

  const [code] = await once(sink, 'close');
  if (code !== 0) {
    throw new Error(`sink exited with code ${code}`);
  }

  await runCmd('python3.11', ['tests/asr_e2e/collect_results.py'], 'results');

  const metricsPath = 'tests/asr_e2e/out/metrics.json';
  if (!fs.existsSync(metricsPath)) {
    throw new Error('metrics.json が生成されていません');
  }
  const metrics = JSON.parse(fs.readFileSync(metricsPath, 'utf-8'));
  const pass = metrics.bad_packets === 0 && metrics.packets_per_sec > 45 && metrics.avg_gap_ms < 30 && metrics.max_gap_ms < 150;
  console.log(pass ? '✅ Transport PASS' : '❌ Transport FAIL', metrics);
  process.exit(pass ? 0 : 1);
}

main().catch((err) => {
  console.error('[run_all] error', err);
  process.exit(1);
});
