import { useEffect, useState, MouseEvent, useCallback } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../lib/config'
import { navigateApp } from '../lib/navigation'

type Item = { event_id: string; title: string; start_ts: number; created_at: number }

export default function MeetingsList() {
  const [params, setParams] = useSearchParams()
  const [items, setItems] = useState<Item[]>([])
  const queryParam = params.get('q') || ''
  const [q, setQ] = useState(queryParam)
  const [title, setTitle] = useState('')
  const [selectedItems, setSelectedItems] = useState<Set<string>>(new Set())
  const [isSelectionMode, setIsSelectionMode] = useState(false)

  const fetchByTitle = useCallback(async (query: string) => {
    const res = await fetch(api(`/api/events/search?q=${encodeURIComponent(query || '*')}`), {
      credentials: 'include',
    })
    const j = await res.json()
    setItems(Array.isArray(j.items) ? j.items : [])
  }, [])

  useEffect(() => {
    setQ(queryParam)
    void fetchByTitle(queryParam)
  }, [queryParam, fetchByTitle])

  const formatDateTime = (ts?: number | null) => {
    if (!ts) return '-'
    return new Date(ts * 1000).toLocaleString()
  }

  const remove = async (id: string) => {
    if (!confirm('この会議を削除しますか？この操作は元に戻せません。')) return
    await fetch(api(`/api/events/${id}`), { method: 'DELETE', credentials: 'include' })
    // 再検索 or ローカル更新
    setItems(prev => prev.filter(i => i.event_id !== id))
  }

  const removeSelected = async () => {
    if (selectedItems.size === 0) return
    if (!confirm(`選択した${selectedItems.size}件の会議を削除しますか？この操作は元に戻せません。`)) return
    
    // 選択されたアイテムを並行して削除
    const deletePromises = Array.from(selectedItems).map(id =>
      fetch(api(`/api/events/${id}`), { method: 'DELETE', credentials: 'include' })
    )
    
    await Promise.all(deletePromises)
    
    // ローカル状態を更新
    setItems(prev => prev.filter(i => !selectedItems.has(i.event_id)))
    setSelectedItems(new Set())
    setIsSelectionMode(false)
  }

  const toggleSelection = (id: string) => {
    setSelectedItems(prev => {
      const newSet = new Set(prev)
      if (newSet.has(id)) {
        newSet.delete(id)
      } else {
        newSet.add(id)
      }
      return newSet
    })
  }

  const selectAll = () => {
    if (selectedItems.size === items.length) {
      setSelectedItems(new Set())
    } else {
      setSelectedItems(new Set(items.map(item => item.event_id)))
    }
  }

  const create = async () => {
    const now = Math.floor(Date.now()/1000)
    const res = await fetch(api('/api/events'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ title: title || '新規会議', start_ts: now, lang: 'ja' }),
    })
    const j = await res.json()
    navigateApp(`/meetings/${j.id}`)
  }

  const triggerSearch = () => {
    if (q.trim()) {
      setParams({ q: q.trim() })
    } else {
      setParams({})
    }
  }

  return (
    <div className="space-y-6">
      <form
        className="flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          triggerSearch()
        }}
      >
        <input
          value={q}
          onChange={e=> setQ(e.target.value)}
          placeholder="会議タイトルで検索"
          className="w-full px-4 py-2 rounded-xl bg-[--panel] text-sm focus:ring-2 focus:ring-blue-500/60 outline-none"
        />
        <button type="submit" className="btn btn-ghost">検索</button>
      </form>
      <div className="card flex items-center gap-2">
        <input value={title} onChange={e=>setTitle(e.target.value)} placeholder="会議タイトル" className="flex-1 bg-transparent outline-none" />
        <button onClick={create} className="btn btn-primary">+ 新規会議</button>
        <button 
          onClick={() => setIsSelectionMode(!isSelectionMode)} 
          className={`btn ${isSelectionMode ? 'btn-secondary' : 'btn-ghost'}`}
        >
          {isSelectionMode ? 'キャンセル' : '選択'}
        </button>
      </div>
      
      {isSelectionMode && items.length > 0 && (
        <div className="card flex items-center gap-2 bg-blue-50">
          <input 
            type="checkbox" 
            checked={selectedItems.size === items.length && items.length > 0}
            onChange={selectAll}
            className="mr-2"
          />
          <span className="text-sm text-gray-600">
            {selectedItems.size > 0 ? `${selectedItems.size}件選択中` : 'すべて選択'}
          </span>
          <div className="flex-1"></div>
          {selectedItems.size > 0 && (
            <button onClick={removeSelected} className="btn bg-red-500 hover:bg-red-600 text-white text-sm">
              選択項目を削除 ({selectedItems.size})
            </button>
          )}
        </div>
      )}
      {items.length === 0 ? (
        <div className="card text-center py-10 text-[--muted]">会議を作成して録音を開始しましょう</div>
      ) : (
        <div className="grid gap-2">
          {items.map(it=> (
            <div key={it.event_id} className="card hover:shadow flex items-center gap-3">
              {isSelectionMode && (
                <input 
                  type="checkbox" 
                  checked={selectedItems.has(it.event_id)}
                  onChange={() => toggleSelection(it.event_id)}
                  className="flex-shrink-0"
                />
              )}
              <Link
                to={`/meetings/${it.event_id}`}
                className="flex-1 min-w-0"
                onContextMenu={isSelectionMode ? (e: MouseEvent) => e.preventDefault() : (e: MouseEvent) => { e.preventDefault(); remove(it.event_id) }}
                title={isSelectionMode ? '' : "右クリックで削除"}
              >
                <div className="font-semibold truncate">{it.title || '無題の会議'}</div>
                <div className="text-xs text-[--muted]">{formatDateTime(it.start_ts || it.created_at)}</div>
              </Link>
              {!isSelectionMode && (
                <button 
                  onClick={(e) => { e.preventDefault(); remove(it.event_id) }}
                  className="btn btn-ghost btn-sm text-red-500 hover:bg-red-100 flex-shrink-0"
                  title="削除"
                >
                  🗑️
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
