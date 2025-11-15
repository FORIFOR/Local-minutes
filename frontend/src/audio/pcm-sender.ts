export class PcmSender {
  private ws: WebSocket
  private ctx: AudioContext | null = null
  private workletNode: AudioWorkletNode | null = null
  private source: MediaStreamAudioSourceNode | null = null

  constructor(ws: WebSocket) {
    this.ws = ws
  }

  async start(stream: MediaStream): Promise<void> {
    this.ctx = new AudioContext({ sampleRate: 48000 })
    if (this.ctx.state === 'suspended') {
      try {
        await this.ctx.resume()
      } catch {}
    }
    await this.ctx.audioWorklet.addModule('/worklet.js')
    this.source = new MediaStreamAudioSourceNode(this.ctx, { mediaStream: stream })
    this.workletNode = new AudioWorkletNode(this.ctx, 'downsampler', {
      processorOptions: { targetSampleRate: 16000, frameMs: 20 },
    })
    this.workletNode.port.onmessage = (event: MessageEvent) => {
      const payload = event.data
      let chunk: Int16Array | null = null
      if (payload instanceof Int16Array) {
        chunk = payload
      } else if (payload && payload.type === 'chunk' && payload.data instanceof ArrayBuffer) {
        chunk = new Int16Array(payload.data)
      }
      if (!chunk) {
        return
      }
      if (this.ws.readyState === WebSocket.OPEN) {
        try {
          this.ws.send(chunk.buffer)
        } catch (err) {
          console.warn('pcm sender ws.send failed', err)
        }
      }
    }
    const silent = this.ctx.createGain()
    silent.gain.value = 0
    this.source.connect(this.workletNode).connect(silent).connect(this.ctx.destination)
  }

  attachAnalyser(analyser: AnalyserNode) {
    if (this.source) {
      try {
        this.source.connect(analyser)
      } catch {}
    }
  }

  getContext(): AudioContext | null {
    return this.ctx
  }

  async stop(): Promise<void> {
    try {
      this.workletNode?.port?.close?.()
    } catch {}
    try {
      this.workletNode?.disconnect()
    } catch {}
    try {
      this.source?.disconnect()
    } catch {}
    if (this.ctx) {
      try {
        await this.ctx.close()
      } catch {}
    }
    this.workletNode = null
    this.ctx = null
    this.source = null
  }
}
