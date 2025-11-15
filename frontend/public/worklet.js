class Downsampler extends AudioWorkletProcessor {
  constructor(options) {
    super()
    const opts = (options && options.processorOptions) || {}
    this.inRate = 48000
    this.targetRate = opts.targetSampleRate || 16000
    this.frameMs = opts.frameMs || 20
    this.decimation = this.inRate / this.targetRate
    this.frameSamples = Math.max(1, Math.round((this.targetRate * this.frameMs) / 1000))
    this.buffer = new Float32Array(0)
  }

  process(inputs) {
    const input = inputs[0]
    if (!input || !input[0]) {
      return true
    }
    const channel = input[0]
    const downsampledLength = Math.ceil(channel.length / this.decimation)
    const downsampled = new Float32Array(downsampledLength)
    for (let i = 0; i < downsampledLength; i++) {
      const idx = Math.floor(i * this.decimation)
      downsampled[i] = channel[idx] || 0
    }
    const merged = new Float32Array(this.buffer.length + downsampled.length)
    merged.set(this.buffer)
    merged.set(downsampled, this.buffer.length)
    this.buffer = merged

    while (this.buffer.length >= this.frameSamples) {
      const frame = this.buffer.slice(0, this.frameSamples)
      this.buffer = this.buffer.slice(this.frameSamples)
      const pcm16 = new Int16Array(frame.length)
      for (let i = 0; i < frame.length; i++) {
        const sample = Math.max(-1, Math.min(1, frame[i]))
        pcm16[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff
      }
      this.port.postMessage(pcm16, [pcm16.buffer])
    }

    return true
  }
}

registerProcessor('downsampler', Downsampler)
