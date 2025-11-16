import { useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

export default function LoginSuccess() {
  const [params] = useSearchParams()
  const next = params.get('next') || '/meetings'
  const { refresh } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    void (async () => {
      try {
        await refresh()
      } finally {
        navigate(next, { replace: true })
      }
    })()
  }, [refresh, next, navigate])

  return (
    <div className="p-6">
      <h1 className="text-lg font-semibold mb-2">ログイン処理中…</h1>
      <p className="text-sm opacity-80">このままお待ちください。</p>
    </div>
  )
}
