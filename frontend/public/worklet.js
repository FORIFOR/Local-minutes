class Downsampler extends AudioWorkletProcessor {
  constructor() {
    super()
    this.acc = []
    this.inRate = 48000
    this.outRate = 16000
    this.ratio = this.inRate / this.outRate
    this.accTime = 0
  }
  process(inputs) {
    const input = inputs[0]
    if (!input || !input[0]) return true
    const ch = input[0]
    const out = []
    for (let i = 0; i < ch.length; i += this.ratio) {
      out.push(ch[Math.floor(i)])
    }
    this.acc.push(...out)
    // 1秒分たまったらPCM16にして送る
    if (this.acc.length >= 16000) {
      const take = this.acc.splice(0, 16000)
      const pcm16 = new Int16Array(take.length)
      for (let i = 0; i < take.length; i++) {
        let s = Math.max(-1, Math.min(1, take[i]))
        pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff
      }
      this.port.postMessage({ type: 'chunk', data: pcm16.buffer }, [pcm16.buffer])
    }
    return true
  }
}
registerProcessor('downsampler', Downsampler)

