import MetricsMini from './MetricsMini'

type Props = {
  isRecording: boolean
  onStart: () => void
  onStop: () => void
}

export default function RecorderBar({ isRecording, onStart, onStop }: Props) {
  return (
    <div className="flex items-center gap-3 bg-[--panel] p-3 rounded-xl">
      <span className="text-sm text-[--muted]">録音</span>
      {isRecording ? (
        <button onClick={onStop} className="btn btn-danger">■ 停止</button>
      ) : (
        <button onClick={onStart} className="btn btn-primary">● 開始</button>
      )}
      <MetricsMini />
    </div>
  )}

