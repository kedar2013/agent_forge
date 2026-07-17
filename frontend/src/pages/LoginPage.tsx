import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Lock, Mail } from 'lucide-react'
import { ChatApiError, login, verifyAdminToken } from '../api/chat'
import Logo from '../components/ui/Logo'
import StudioCredit from '../components/ui/StudioCredit'
import { setStoredRole, setStoredToken, setUserSession } from '../lib/auth'

function TokenLoginForm({ onSuccess }: { onSuccess: () => void }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      // Verified server-side, never client-side — see api/chat.ts's
      // verifyAdminToken docstring: a client-side comparison would compare
      // against a value Vite bakes verbatim into the public JS bundle.
      const ok = await verifyAdminToken(password)
      if (!ok) {
        setError('Incorrect admin password.')
        return
      }
      setStoredToken(password)
      setStoredRole('admin')
      // Same bridge as the named-account login below — the static token
      // resolves to role=admin server-side too (principal.py), so it's a
      // valid chat credential; without this, clicking "Chat" in the sidebar
      // would bounce straight to a redundant second login.
      setUserSession(password, 'admin (static token)')
      onSuccess()
    } catch {
      setError('Sign in failed — please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <label className="block text-sm">
        <span className="mb-1 block font-medium">Admin password</span>
        <div className="relative">
          <Lock size={15} className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-slate-400" />
          <input
            type="password"
            autoFocus
            className="w-full rounded-md border border-slate-300 py-1.5 pr-2 pl-8 text-sm focus:border-brand-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value)
              setError(null)
            }}
          />
        </div>
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
  )
}

function NamedAccountLoginForm({ onSuccess }: { onSuccess: () => void }) {
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
      if (result.role === 'chat_user') {
        setError('This account is chat-only — use "Sign in here" below to reach the chat surface instead.')
        return
      }
      setStoredToken(result.token)
      setStoredRole(result.role)
      // ChatPage checks a separate token (af_user_token, from the /user-login
      // flow) since it's a distinct white-labeled surface — but the token
      // itself is the same kind of per-user credential either way (see
      // principal.py's get_current_principal), so bridge it here rather than
      // forcing a developer/admin to log in a second time just to reach the
      // "Chat" link in the sidebar.
      setUserSession(result.token, result.email)
      onSuccess()
    } catch (err) {
      setError(err instanceof ChatApiError ? err.message : 'Sign in failed.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
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
      <p className="text-center text-xs text-slate-400">
        No account yet?{' '}
        <Link to="/register" className="font-medium text-brand-600 hover:underline dark:text-brand-400">
          Register as a developer
        </Link>
      </p>
    </form>
  )
}

export default function LoginPage({ onSuccess }: { onSuccess: () => void }) {
  const [tab, setTab] = useState<'token' | 'account'>('token')

  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-[--radius-card] border border-white/60 bg-white/70 p-8 shadow-[inset_0_1px_0_rgba(255,255,255,0.5),var(--shadow-card-hover)] backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/70">
        <div className="mb-6 flex flex-col items-center gap-2 text-center">
          <Logo size="lg" withWordmark={false} />
          <h1 className="text-lg font-semibold">Eärendil</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {tab === 'token' ? 'Admin access required' : 'Sign in with your admin, viewer, or developer account'}
          </p>
        </div>

        <div className="mb-4 flex gap-1 rounded-md bg-slate-100 p-1 text-xs font-medium dark:bg-slate-800">
          <button
            onClick={() => setTab('token')}
            className={`flex-1 rounded px-2 py-1.5 transition-colors ${
              tab === 'token' ? 'bg-white shadow-sm dark:bg-slate-700' : 'text-slate-500 dark:text-slate-400'
            }`}
          >
            Admin token
          </button>
          <button
            onClick={() => setTab('account')}
            className={`flex-1 rounded px-2 py-1.5 transition-colors ${
              tab === 'account' ? 'bg-white shadow-sm dark:bg-slate-700' : 'text-slate-500 dark:text-slate-400'
            }`}
          >
            Email &amp; password
          </button>
        </div>

        {tab === 'token' ? <TokenLoginForm onSuccess={onSuccess} /> : <NamedAccountLoginForm onSuccess={onSuccess} />}

        <p className="mt-4 text-center text-xs text-slate-400">
          Looking to chat instead of configure?{' '}
          <Link to="/user-login" className="font-medium text-brand-600 hover:underline dark:text-brand-400">
            Sign in here
          </Link>
        </p>
      </div>
      <StudioCredit className="mt-4" />
    </div>
  )
}
