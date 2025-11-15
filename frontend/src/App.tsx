import { Outlet } from 'react-router-dom'
import AppHeader from './components/AppHeader'
import SidebarNav from './components/SidebarNav'
import RecorderDock from './components/RecorderDock'

export default function App() {
  return (
    <div className="min-h-screen bg-[--bg] text-gray-900 dark:text-gray-100">
      <AppHeader />
      <div className="mx-auto max-w-[1200px] px-6 grid grid-cols-1 md:grid-cols-[240px_1fr] gap-6 my-6">
        <aside className="hidden md:block">
          <SidebarNav />
        </aside>
        <main>
          <Outlet />
        </main>
      </div>
      <RecorderDock />
    </div>
  )
}
