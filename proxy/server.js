#!/usr/bin/env node
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import fs from 'node:fs';
import os from 'node:os';
import express from 'express';
import compression from 'compression';
import helmet from 'helmet';
import { createProxyMiddleware } from 'http-proxy-middleware';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(__dirname, '..');
const distDir = path.resolve(rootDir, 'frontend', 'dist');

if (!fs.existsSync(distDir)) {
  console.error('[proxy] frontend/dist が見つかりません。先に `npm run build` を実行してください。');
  process.exit(1);
}

const BACKEND_BASE = process.env.BACKEND_BASE || 'http://127.0.0.1:8000';
const HOST = process.env.FRONTEND_HOST || '0.0.0.0';
const PORT = Number(process.env.FRONTEND_PORT || 3000);

const app = express();
app.disable('x-powered-by');
app.use(
  helmet({
    crossOriginResourcePolicy: false,
  }),
);
app.use(compression());

const logPrefix = '[proxy]';
console.log(`${logPrefix} BACKEND_BASE=${BACKEND_BASE}`);

const commonProxyOptions = {
  changeOrigin: false,
  logLevel: 'warn',
  timeout: 0,
  proxyTimeout: 0,
  preserveHeaderKeyCase: true,
};

const apiProxy = createProxyMiddleware({
  ...commonProxyOptions,
  target: BACKEND_BASE,
});

const sseProxy = createProxyMiddleware({
  ...commonProxyOptions,
  target: BACKEND_BASE,
  selfHandleResponse: false,
  onProxyReq: (proxyReq) => {
    proxyReq.setHeader('Connection', 'keep-alive');
  },
});

const wsProxy = createProxyMiddleware({
  ...commonProxyOptions,
  target: BACKEND_BASE.replace(/^http/, 'ws'),
  ws: true,
});

app.use('/api/events/:id/summary/stream', sseProxy);
app.use(['/api', '/healthz', '/download.srt', '/download.vtt', '/download.rttm', '/download.ics'], apiProxy);
app.use('/ws', wsProxy);

app.use(express.static(distDir, { extensions: ['html'] }));
app.get('*', (req, res) => {
  res.sendFile(path.join(distDir, 'index.html'));
});

app.listen(PORT, HOST, () => {
  console.log(`${logPrefix} UI server listening on http://${HOST}:${PORT}`);
  if (HOST === '0.0.0.0') {
    const interfaces = os.networkInterfaces();
    for (const addrs of Object.values(interfaces)) {
      if (!addrs) continue;
      for (const addr of addrs) {
        if (!addr || addr.internal || addr.family !== 'IPv4') continue;
        console.log(`${logPrefix} LAN URL: http://${addr.address}:${PORT}`);
      }
    }
  }
});
