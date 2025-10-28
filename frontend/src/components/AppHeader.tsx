import * as React from 'react'
import { Link, useNavigate } from 'react-router-dom'
import * as Dialog from '@radix-ui/react-dialog'
import SidebarNav from './SidebarNav'

export default function AppHeader() {
  const nav = useNavigate()
  const searchRef = React.useRef<HTMLInputElement>(null)
  const [theme, setTheme] = React.useState<string>(() => localStorage.getItem('theme') || (import.meta.env.VITE_THEME || 'auto'))

  React.useEffect(() => {
    const root = document.documentElement
    if (theme === 'dark' || (theme === 'auto' && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
      root.classList.add('dark')
    } else {
      root.classList.remove('dark')
    }
    localStorage.setItem('theme', theme)
  }, [theme])

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === '/' && !e.metaKey && !e.ctrlKey) {
        e.preventDefault()
        searchRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const [q, setQ] = React.useState('')
  const onSearch = (e: React.FormEvent) => {
    e.preventDefault()
    nav(`/meetings?q=${encodeURIComponent(q)}`)
  }

  return (
    <header className="sticky top-0 z-40 border-b border-black/10 dark:border-white/10 backdrop-blur bg-white/70 dark:bg-black/30">
      <div className="mx-auto max-w-[1200px] px-6 h-16 flex items-center gap-4">
        <div className="min-w-[120px] flex items-center gap-2">
          {/* モバイル: サイドバーをシートで開く */}
          <div className="md:hidden">
            <Dialog.Root>
              <Dialog.Trigger asChild>
                <button className="btn btn-ghost" aria-label="メニュー">☰</button>
              </Dialog.Trigger>
              <Dialog.Portal>
                <Dialog.Overlay className="fixed inset-0 bg-black/40 data-[state=open]:animate-in" />
                <Dialog.Content className="fixed inset-y-0 left-0 w-[280px] bg-[--panel] p-4 data-[state=open]:animate-in">
                  <div className="mb-4 font-semibold">メニュー</div>
                  <SidebarNav />
                  <Dialog.Close asChild>
                    <button className="btn btn-ghost mt-4 w-full" aria-label="閉じる">閉じる</button>
                  </Dialog.Close>
                </Dialog.Content>
              </Dialog.Portal>
            </Dialog.Root>
          </div>
          <Link to="/meetings" className="font-semibold text-lg">Local Minutes</Link>
        </div>
        <form onSubmit={onSearch} className="flex-1">
          <input
            ref={searchRef}
            value={q}
            onChange={e=>setQ(e.target.value)}
            placeholder="/ で検索"
            aria-label="検索"
            className="w-full px-4 py-2 rounded-xl bg-[--panel] text-sm focus:ring-2 focus:ring-blue-500/60 outline-none"
          />
        </form>
        <div className="ml-auto flex items-center gap-2 text-sm text-[--muted]">
          <button className="btn btn-ghost" aria-label="設定">⚙︎</button>
          <button className="btn btn-ghost" aria-label="テーマ切替" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
            {theme === 'dark' ? '☼' : '☾'}
          </button>
        </div>
      </div>
    </header>
  )
}
