import { FormEvent, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { api } from '../lib/config'

export default function Login() {
  const { login, authError, clearError } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const enableGoogleLogin = import.meta.env.VITE_ENABLE_GOOGLE_LOGIN === 'true'

  const handleGoogleLogin = () => {
    const next = searchParams.get('next') || '/'
    const base = api('/api/auth/google/login')
    const target = new URL(base, window.location.origin)
    if (next) {
      target.searchParams.set('next', next)
    }
    window.location.href = target.toString()
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setLocalError(null)
    clearError()
    setSubmitting(true)
    try {
      await login(email, password)
      const next = searchParams.get('next') || '/meetings'
      navigate(next, { replace: true })
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : 'ログインに失敗しました')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {(authError || localError) && (
        <div className="rounded-lg border border-red-200 bg-red-50 text-sm text-red-700 p-3">
          {authError || localError}
        </div>
      )}
      <div>
        <label className="block text-sm font-medium mb-1" htmlFor="email">
          メールアドレス
        </label>
        <input
          id="email"
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full rounded-xl border border-black/10 dark:border-white/10 px-4 py-2 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/30 outline-none bg-[--panel]"
          placeholder="you@example.com"
        />
      </div>
      <div>
        <label className="block text-sm font-medium mb-1" htmlFor="password">
          パスワード
        </label>
        <input
          id="password"
          type="password"
          required
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full rounded-xl border border-black/10 dark:border-white/10 px-4 py-2 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/30 outline-none bg-[--panel]"
          placeholder="••••••••"
        />
      </div>
      <button
        type="submit"
        disabled={submitting}
        className="w-full rounded-xl bg-blue-600 disabled:opacity-60 text-white py-2.5 font-semibold shadow hover:bg-blue-500 transition-colors"
      >
        {submitting ? 'サインイン中…' : 'サインイン'}
      </button>
      {enableGoogleLogin && (
        <>
          <div className="text-center text-xs text-gray-500 dark:text-gray-400">または</div>
          <button
            type="button"
            onClick={handleGoogleLogin}
            className="w-full rounded-xl border border-black/10 dark:border-white/10 py-2.5 font-semibold bg-white dark:bg-black hover:bg-gray-50 dark:hover:bg-gray-900 transition-colors flex items-center justify-center gap-2"
          >
            <span role="img" aria-hidden="true">🔒</span>
            Googleでログイン
          </button>
        </>
      )}
      <p className="text-sm text-gray-600 dark:text-gray-300 text-center">
        アカウントをお持ちでない場合は <Link to="/auth/register" className="text-blue-600 hover:underline">こちら</Link>
      </p>
    </form>
  )
}
