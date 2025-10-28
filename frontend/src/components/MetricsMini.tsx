type Props = { asr?: string; diar?: string; mt?: string; llm?: string }
export default function MetricsMini({ asr = '—', diar = '—', mt = '—', llm = '—' }: Props) {
  return (
    <div className="ml-auto flex gap-4 text-xs text-[--muted]">
      <div>ASR {asr}</div>
      <div>DIAR {diar}</div>
      <div>MT {mt}</div>
      <div>LLM {llm}</div>
    </div>
  )
}

