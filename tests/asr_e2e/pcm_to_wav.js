import fs from 'fs';

export function pcmToWav(inPath, outPath, sampleRate = 16000, numChannels = 1) {
  if (!fs.existsSync(inPath)) {
    console.warn('[wav] PCM file not found', inPath);
    return;
  }

  const pcm = fs.readFileSync(inPath);
  const byteRate = sampleRate * numChannels * 2;
  const blockAlign = numChannels * 2;
  const dataSize = pcm.length;

  const header = Buffer.alloc(44);
  header.write('RIFF', 0);
  header.writeUInt32LE(36 + dataSize, 4);
  header.write('WAVE', 8);
  header.write('fmt ', 12);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20);
  header.writeUInt16LE(numChannels, 22);
  header.writeUInt32LE(sampleRate, 24);
  header.writeUInt32LE(byteRate, 28);
  header.writeUInt16LE(blockAlign, 32);
  header.writeUInt16LE(16, 34);
  header.write('data', 36);
  header.writeUInt32LE(dataSize, 40);

  fs.writeFileSync(outPath, Buffer.concat([header, pcm]));
  console.log('[wav] wrote', outPath);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const [, , inPath, outPath] = process.argv;
  if (!inPath || !outPath) {
    console.error('Usage: node tests/asr_e2e/pcm_to_wav.js <input.pcm> <output.wav>');
    process.exit(1);
  }
  pcmToWav(inPath, outPath);
}
