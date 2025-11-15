import { Outlet, NavLink, useLocation } from 'react-router-dom'

export default function AuthLayout() {
  const location = useLocation()
  const isRegister = location.pathname.includes('/auth/register')
  const heading = isRegister ? 'サインアップ' : 'サインイン'
  const switchLink = isRegister
    ? { to: '/auth/login', label: 'サインインへ' }
    : { to: '/auth/register', label: 'サインアップへ' }

  return (
    <div className="min-h-screen bg-[--bg] flex items-center justify-center px-4">
      <div className="w-full max-w-4xl grid grid-cols-1 md:grid-cols-5 rounded-2xl shadow-xl overflow-hidden bg-white dark:bg-black border border-black/10 dark:border-white/10">
        <div className="hidden md:flex md:col-span-2 bg-gradient-to-br from-blue-500 to-indigo-600 text-white p-8 flex-col justify-between">
          <div>
            <p className="text-sm uppercase tracking-wide opacity-80">Local Minutes</p>
            <h1 className="text-3xl font-bold mt-3">どこでも安全に議事録を作成</h1>
            <p className="mt-4 text-sm text-white/90 leading-6">
              マイクの音声は端末で処理され、リアルタイムに文字起こしされます。ログインすると過去の議事録や予定を管理できます。
            </p>
          </div>
        </div>
        <div className="md:col-span-3 p-8 space-y-6">
          <div className="flex items-center justify-between">
            <p className="text-2xl font-semibold text-gray-900 dark:text-white">
              {heading}
            </p>
            <NavLink to={switchLink.to} className="text-sm text-blue-600 hover:underline">
              {switchLink.label}
            </NavLink>
          </div>
          <Outlet />
        </div>
      </div>
    </div>
  )
}
