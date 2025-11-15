import { NavLink } from 'react-router-dom'
import { isRecordingActive } from '../lib/navigation'

const linkCls = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-3 px-3 py-2 rounded-xl hover:bg-black/5 dark:hover:bg-white/5 ${isActive ? 'bg-black/5 dark:bg-white/10' : ''}`

const handleNavClick = (e: React.MouseEvent, to: string) => {
  if (isRecordingActive()) {
    e.preventDefault()
    window.open(to, '_blank', 'noopener,noreferrer')
  }
}

export default function SidebarNav() {
  return (
    <nav className="space-y-1 text-sm">
      <NavLink to="/" className={linkCls} onClick={(e) => handleNavClick(e, '/')}>
        <span>🏠</span><span>ホーム</span>
      </NavLink>
      <NavLink to="/recording" className={linkCls} onClick={(e) => handleNavClick(e, '/recording')}>
        <span>🎙️</span><span>録音</span>
      </NavLink>
      <NavLink to="/meetings" className={linkCls} onClick={(e) => handleNavClick(e, '/meetings')}>
        <span>🗓️</span><span>会議一覧</span>
      </NavLink>
      <NavLink to="/calendar" className={linkCls} onClick={(e) => handleNavClick(e, '/calendar')}>
        <span>📅</span><span>カレンダー</span>
      </NavLink>
      <NavLink to="/settings" className={linkCls} onClick={(e) => handleNavClick(e, '/settings')}>
        <span>⚙️</span><span>設定</span>
      </NavLink>
      <NavLink to="/help" className={linkCls} onClick={(e) => handleNavClick(e, '/help')}>
        <span>❓</span><span>ヘルプ</span>
      </NavLink>
    </nav>
  )
}
