import { FormEvent, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

export default function Register() {
  const { register, authError, clearError } = useAuth()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)
  const navigate = useNavigate()

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    clearError()
    setLocalError(null)
    if (password !== confirm) {
      setLocalError('パスワードが一致しません')
      return
    }
    setSubmitting(true)
    try {
      await register(name, email, password)
      navigate('/meetings', { replace: true })
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : '登録に失敗しました')
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
        <label className="block text-sm font-medium mb-1" htmlFor="name">
          表示名
        </label>
        <input
          id="name"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full rounded-xl border border-black/10 dark:border-white/10 px-4 py-2 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/30 outline-none bg-[--panel]"
          placeholder="山田 太郎"
        />
      </div>
      <div>
        <label className="block text-sm font-medium mb-1" htmlFor="reg-email">
          メールアドレス
        </label>
        <input
          id="reg-email"
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full rounded-xl border border-black/10 dark:border-white/10 px-4 py-2 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/30 outline-none bg-[--panel]"
          placeholder="you@example.com"
        />
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <div>
          <label className="block text-sm font-medium mb-1" htmlFor="reg-password">
            パスワード
          </label>
          <input
            id="reg-password"
            type="password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-xl border border-black/10 dark:border-white/10 px-4 py-2 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/30 outline-none bg-[--panel]"
            placeholder="••••••••"
          />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1" htmlFor="reg-confirm">
            パスワード（確認）
          </label>
          <input
            id="reg-confirm"
            type="password"
            required
            minLength={8}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            className="w-full rounded-xl border border-black/10 dark:border-white/10 px-4 py-2 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/30 outline-none bg-[--panel]"
            placeholder="••••••••"
          />
        </div>
      </div>
      <button
        type="submit"
        disabled={submitting}
        className="w-full rounded-xl bg-indigo-600 disabled:opacity-60 text-white py-2.5 font-semibold shadow hover:bg-indigo-500 transition-colors"
      >
        {submitting ? '登録中…' : 'アカウント登録'}
      </button>
      <div className="text-sm text-gray-600 dark:text-gray-300 text-center space-y-2">
        <Link to="/help#forgot-password" className="text-blue-600 hover:underline">
          パスワードを忘れた方はこちら
        </Link>
        <p>
          すでにアカウントをお持ちの方は{' '}
          <Link to="/auth/login" className="text-blue-600 hover:underline">
            ログイン
          </Link>
        </p>
      </div>
    </form>
  )
}
