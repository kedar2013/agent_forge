import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { CheckCircle2, Mail } from 'lucide-react'
import { ChatApiError, register } from '../api/chat'
import Logo from '../components/ui/Logo'
import StudioCredit from '../components/ui/StudioCredit'

export default function RegisterPage() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [role, setRole] = useState<'chat_user' | 'developer'>('chat_user')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (password.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }
    if (password !== confirmPassword) {
      setError("Passwords don't match.")
      return
    }
    setSubmitting(true)
    try {
      await register({ email, password, role })
      setSubmitted(true)
    } catch (err) {
      setError(err instanceof ChatApiError ? err.message : 'Registration failed.')
    } finally {
      setSubmitting(false)
    }
  }

  if (submitted) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center px-4">
        <div className="w-full max-w-sm rounded-[--radius-card] border border-white/60 bg-white/70 p-8 text-center shadow-[inset_0_1px_0_rgba(255,255,255,0.5),var(--shadow-card-hover)] backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/70">
          <CheckCircle2 size={36} className="mx-auto mb-3 text-emerald-500" />
          <h1 className="mb-1 text-lg font-semibold">Request submitted</h1>
          <p className="mb-5 text-sm text-slate-500 dark:text-slate-400">
            An admin needs to approve <strong>{email}</strong> before you can sign in.
            {role === 'developer' &&
              ' Once approved, sign in from the admin shell (Email & password tab) to start building agents — every agent you publish will still need a separate admin review before it goes live.'}{' '}
            Check back shortly.
          </p>
          <Link
            to={role === 'developer' ? '/' : '/user-login'}
            className="text-sm font-medium text-brand-600 hover:underline dark:text-brand-400"
          >
            Back to sign in
          </Link>
        </div>
        <StudioCredit className="mt-4" />
      </div>
    )
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-[--radius-card] border border-white/60 bg-white/70 p-8 shadow-[inset_0_1px_0_rgba(255,255,255,0.5),var(--shadow-card-hover)] backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/70">
        <div className="mb-6 flex flex-col items-center gap-2 text-center">
          <Logo size="lg" withWordmark={false} />
          <h1 className="text-lg font-semibold">Create an account</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Register to chat with the assistant — an admin approves new accounts.
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
          <label className="block text-sm">
            <span className="mb-1 block font-medium">Confirm password</span>
            <input
              type="password"
              required
              className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm focus:border-brand-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium">Account type</span>
            <select
              className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm focus:border-brand-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
              value={role}
              onChange={(e) => setRole(e.target.value as typeof role)}
            >
              <option value="chat_user">Chat user — talk to the assistant only</option>
              <option value="developer">Developer — build/test agents, plus chat</option>
            </select>
            {role === 'developer' && (
              <span className="mt-1 block text-xs text-slate-400">
                You'll be able to create agents and sub-agents and run them in the Playground. Publishing one to make
                it live still needs a separate admin approval.
              </span>
            )}
          </label>
          {error && <p className="text-xs text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-md bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            {submitting ? 'Submitting…' : 'Register'}
          </button>
        </form>
        <p className="mt-4 text-center text-xs text-slate-500 dark:text-slate-400">
          Already approved?{' '}
          <Link
            to={role === 'developer' ? '/' : '/user-login'}
            className="font-medium text-brand-600 hover:underline dark:text-brand-400"
          >
            Sign in
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
