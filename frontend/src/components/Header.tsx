import { Link } from 'react-router-dom'

export default function Header() {
  return (
    <header className="border-b border-gray-200 dark:border-gray-800">
      <div className="max-w-6xl mx-auto p-4 flex items-center justify-between">
        <Link to="/meetings" className="font-semibold text-lg">M4-Meet</Link>
        <div className="flex items-center gap-4 text-sm opacity-80">
          <span title="ASR latency">ASR: -- ms</span>
          <span title="Diar latency">DIAR: -- ms</span>
          <span title="MT latency">MT: -- ms</span>
          <span title="LLM latency">LLM: -- ms</span>
        </div>
      </div>
    </header>
  )
}

