import fs from 'fs';
import path from 'path';
import { WebSocket } from 'ws';

function parseArgs() {
  const args = process.argv.slice(2);
  const result = {
    url: 'ws://127.0.0.1:8765',
    seconds: 10,
    silence: false,
    stdin: false,
    rate: 16000,
    channels: 1,
    sampleWidth: 2,
    chunkMs: 20
  };

  for (const arg of args) {
    if (!arg.startsWith('--')) {
      continue;
    }
    const body = arg.slice(2);
    if (!body) continue;
    const eq = body.indexOf('=');
    if (eq === -1) {
      if (body === 'silence') {
        result.silence = true;
      } else if (body === 'no-silence') {
        result.silence = false;
      } else if (body === 'stdin') {
        result.stdin = true;
      } else {
        result[body] = true;
      }
      continue;
    }
    const key = body.slice(0, eq);
    const value = body.slice(eq + 1);
    if (key === 'seconds') {
      const num = Number(value);
      if (!Number.isFinite(num) || num <= 0) {
        throw new Error('--seconds には正の数を指定してください');
      }
      result.seconds = num;
    } else if (key === 'url') {
      result.url = value || result.url;
    } else if (key === 'wav') {
      result.wav = value;
    } else if (key === 'chunk') {
      const num = Number(value);
      if (!Number.isFinite(num) || num <= 0) {
        throw new Error('--chunk には正の数を指定してください');
      }
      result.chunk = num;
    } else if (key === 'chunk-ms') {
      const num = Number(value);
      if (!Number.isFinite(num) || num <= 0) {
        throw new Error('--chunk-ms には正の数を指定してください');
      }
      result.chunkMs = num;
    } else if (key === 'rate') {
      const num = Number(value);
      if (!Number.isFinite(num) || num <= 0) {
        throw new Error('--rate には正の数を指定してください');
      }
      result.rate = num;
    } else if (key === 'channels') {
      const num = Number(value);
      if (!Number.isFinite(num) || num <= 0) {
        throw new Error('--channels には正の数を指定してください');
      }
      result.channels = num;
    } else if (key === 'sample-width') {
      const num = Number(value);
      if (!Number.isFinite(num) || num <= 0) {
        throw new Error('--sample-width には正の数を指定してください');
      }
      result.sampleWidth = num;
    } else {
      result[key] = value;
    }
  }

  if (!result.wav && !result.silence && !result.stdin) {
    const fallback = path.join('tests', 'asr_e2e', 'assets', 'yt.wav');
    if (fs.existsSync(fallback)) {
      result.wav = fallback;
    }
  }

  return result;
}

function* framesFromWav(wavPath, chunkSize = 640) {
  const abs = path.resolve(wavPath);
  if (!fs.existsSync(abs)) {
    throw new Error(`WAVファイルが見つかりません: ${abs}`);
  }
  const buf = fs.readFileSync(abs);
  if (buf.length < 44) {
    throw new Error(`WAVヘッダーが不足しています: ${abs}`);
  }
  const sr = buf.readUInt32LE(24);
  const ch = buf.readUInt16LE(22);
  const bits = buf.readUInt16LE(34);
  if (sr !== 16000 || ch !== 1 || bits !== 16) {
    throw new Error(`WAVは16kHz/mono/16bitのみ対応しています: sr=${sr} ch=${ch} bits=${bits}`);
  }
  const pcm = buf.subarray(44);
  for (let i = 0; i + chunkSize <= pcm.length; i += chunkSize) {
    yield pcm.subarray(i, i + chunkSize);
  }
}

function* silentFrames(seconds, chunkSize = 640, chunkMs = 20) {
  const durationMs = Number(seconds) * 1000;
  const interval = chunkMs > 0 ? chunkMs : 20;
  const totalFrames = Math.max(1, Math.round(durationMs / interval));
  const packet = Buffer.alloc(chunkSize);
  for (let i = 0; i < totalFrames; i++) {
    yield packet;
  }
}

function* framesFromBuffer(buffer, chunkSize) {
  for (let i = 0; i + chunkSize <= buffer.length; i += chunkSize) {
    yield buffer.subarray(i, i + chunkSize);
  }
  const rest = buffer.length % chunkSize;
  if (rest > 0) {
    const tail = Buffer.alloc(chunkSize);
    buffer.subarray(buffer.length - rest).copy(tail);
    yield tail;
  }
}

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  return Buffer.concat(chunks);
}

async function main() {
  const opts = parseArgs();
  const chunkMs = Number(opts.chunkMs) || 20;
  const chunkSize = Number(
    opts.chunk ||
      Math.round(Number(opts.rate) * Number(opts.channels) * Number(opts.sampleWidth) * (chunkMs / 1000))
  );
  if (!Number.isFinite(chunkSize) || chunkSize <= 0) {
    throw new Error('チャンクサイズの計算に失敗しました。パラメータを確認してください。');
  }

  if (!opts.silence && !opts.wav && !opts.stdin) {
    throw new Error('再生する WAV (--wav) か --stdin か --silence のいずれかを指定してください。');
  }

  let generator;
  if (opts.silence) {
    generator = silentFrames(opts.seconds, chunkSize, chunkMs);
  } else if (opts.stdin) {
    const buffer = await readStdin();
    if (!buffer.length) {
      throw new Error('STDIN が空でした。');
    }
    console.log(`[sender] read ${buffer.length} bytes from stdin`);
    generator = framesFromBuffer(buffer, chunkSize);
  } else {
    generator = framesFromWav(opts.wav, chunkSize);
  }

  const ws = new WebSocket(opts.url);
  await new Promise((resolve, reject) => {
    ws.once('open', resolve);
    ws.once('error', reject);
  });

  console.log(`[sender] connected: ${opts.url}`);
  if (opts.wav) {
    console.log(`[sender] streaming wav=${path.resolve(opts.wav)}`);
  } else if (opts.stdin) {
    console.log('[sender] streaming stdin PCM');
  } else {
    console.log(`[sender] streaming silence ${opts.seconds}s`);
  }
  console.log(
    `[sender] settings chunk=${chunkSize}B interval=${chunkMs}ms rate=${opts.rate}Hz channels=${opts.channels} width=${opts.sampleWidth}B`
  );

  const start = Date.now();
  let sent = 0;
  let lastLog = start;

  const tick = () => {
    const next = generator.next();
    if (next.done) {
      ws.close();
      return;
    }
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(next.value);
      sent++;
    }
    const now = Date.now();
    if (now - lastLog >= 1000) {
      const elapsed = (now - start) / 1000;
      const pps = sent / (elapsed || 1);
      console.log(`[sender] progress packets=${sent} pps=${pps.toFixed(2)}`);
      lastLog = now;
    }
    const elapsed = Date.now() - start;
    const ideal = sent * chunkMs;
    const delay = Math.max(0, chunkMs - (elapsed - ideal));
    setTimeout(tick, delay);
  };

  tick();

  await new Promise((resolve) => ws.once('close', resolve));
  const duration = (Date.now() - start) / 1000;
  const pps = sent / (duration || 1);
  console.log(`[sender] finished packets=${sent} duration=${duration.toFixed(2)}s pps=${pps.toFixed(2)}`);
}

main().catch((err) => {
  console.error('[sender] error', err);
  process.exit(1);
});
