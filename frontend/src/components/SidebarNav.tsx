import { NavLink } from 'react-router-dom'

const linkCls = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-3 px-3 py-2 rounded-xl hover:bg-black/5 dark:hover:bg-white/5 ${isActive ? 'bg-black/5 dark:bg-white/10' : ''}`

export default function SidebarNav() {
  return (
    <nav className="space-y-1 text-sm">
      <NavLink to="/" className={linkCls}><span>🏠</span><span>ホーム</span></NavLink>
      <NavLink to="/recording" className={linkCls}><span>🎙️</span><span>録音</span></NavLink>
      <NavLink to="/meetings" className={linkCls}><span>🗓️</span><span>会議一覧</span></NavLink>
      <NavLink to="/calendar" className={linkCls}><span>📅</span><span>カレンダー</span></NavLink>
      <NavLink to="/settings" className={linkCls}><span>⚙️</span><span>設定</span></NavLink>
      <NavLink to="/help" className={linkCls}><span>❓</span><span>ヘルプ</span></NavLink>
    </nav>
  )
}
