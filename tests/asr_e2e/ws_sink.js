import fs from 'fs';
import path from 'path';
import { WebSocketServer } from 'ws';

const OUT_DIR = path.join(process.cwd(), 'tests', 'asr_e2e', 'out');
fs.mkdirSync(OUT_DIR, { recursive: true });
const RAW = path.join(OUT_DIR, 'raw.pcm');
const MET = path.join(OUT_DIR, 'metrics.json');
const ANOM = path.join(OUT_DIR, 'anomalies.json');

const st = { start: 0, last: 0, n: 0, bytes: 0, gaps: [], bad: 0 };
const anomalies = [];

if (fs.existsSync(RAW)) fs.unlinkSync(RAW);

const wss = new WebSocketServer({ host: '127.0.0.1', port: 8765 });
console.log('[sink] listening ws://127.0.0.1:8765');

wss.on('connection', (ws, req) => {
  console.log('[sink] client connected', req.socket.remoteAddress);
  st.start = Date.now();
  st.last = st.start;

  ws.on('message', (data) => {
    const now = Date.now();
    const gap = now - st.last;
    st.last = now;

    if (Buffer.isBuffer(data)) {
      const len = data.byteLength;
      if (len !== 640) {
        st.bad++;
        anomalies.push({ idx: st.n, len, t: now });
      }
      fs.appendFileSync(RAW, data);
      st.n++;
      st.bytes += len;
      st.gaps.push(gap);
    }
  });

  ws.on('close', async () => {
    const durMs = Math.max(1, Date.now() - st.start);
    const pps = st.n / (durMs / 1000);
    const avgGap = st.gaps.length ? st.gaps.reduce((a, b) => a + b, 0) / st.gaps.length : 0;
    const maxGap = st.gaps.length ? Math.max(...st.gaps) : 0;

    const metrics = {
      packets: st.n,
      bytes: st.bytes,
      duration_ms: durMs,
      packets_per_sec: Number(pps.toFixed(2)),
      avg_gap_ms: Number(avgGap.toFixed(2)),
      max_gap_ms: maxGap,
      bad_packets: st.bad,
      ideal_packet_bytes: 640
    };
    fs.writeFileSync(MET, JSON.stringify(metrics, null, 2));
    fs.writeFileSync(ANOM, JSON.stringify(anomalies, null, 2));
    console.log('[sink] closed. metrics:', metrics);

    // WAV封入
    await import('./pcm_to_wav.js').then((m) => m.pcmToWav(RAW, path.join(OUT_DIR, 'recv.wav')));
    process.exit(0);
  });
});
