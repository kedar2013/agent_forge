import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Mail } from 'lucide-react'
import { ChatApiError, login } from '../api/chat'
import Logo from '../components/ui/Logo'
import StudioCredit from '../components/ui/StudioCredit'
import { setUserSession } from '../lib/auth'

export default function UserLoginPage() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const result = await login({ email, password })
      setUserSession(result.token, result.email)
      navigate('/chat')
    } catch (err) {
      setError(err instanceof ChatApiError ? err.message : 'Sign in failed.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-[--radius-card] border border-white/60 bg-white/70 p-8 shadow-[inset_0_1px_0_rgba(255,255,255,0.5),var(--shadow-card-hover)] backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/70">
        <div className="mb-6 flex flex-col items-center gap-2 text-center">
          <Logo size="lg" withWordmark={false} />
          <h1 className="text-lg font-semibold">Sign in to chat</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Use the account an admin has approved.
          </p>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3">
          <label className="block text-sm">
            <span className="mb-1 block font-medium">Email</span>
            <div className="relative">
              <Mail size={15} className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-slate-400" />
              <input
                type="email"
                required
                autoFocus
                className="w-full rounded-md border border-slate-300 py-1.5 pr-2 pl-8 text-sm focus:border-brand-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium">Password</span>
            <input
              type="password"
              required
              className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm focus:border-brand-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {error && <p className="text-xs text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-md bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
        <p className="mt-4 text-center text-xs text-slate-500 dark:text-slate-400">
          Don't have an account?{' '}
          <Link to="/register" className="font-medium text-brand-600 hover:underline dark:text-brand-400">
            Register
          </Link>
        </p>
        <p className="mt-1 text-center text-xs text-slate-400">
          <button onClick={() => navigate('/')} className="hover:underline">
            Admin? Sign in here
          </button>
        </p>
      </div>
      <StudioCredit className="mt-4" />
    </div>
  )
}
