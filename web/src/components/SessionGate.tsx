import { useState } from 'react'
import type { FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { LockKeyhole, ShieldCheck } from 'lucide-react'
import { api, getSessionToken, setSessionToken } from '../lib/api'
import App from '../App'

export function SessionGate() {
  const qc = useQueryClient()
  const [username, setUsername] = useState('operator')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const token = getSessionToken()

  const health = useQuery({
    queryKey: ['health-bootstrap'],
    queryFn: api.health,
    staleTime: 10_000,
    retry: 1,
  })

  const authRequired = health.data?.authRequired === true
  if (health.isLoading) {
    return <BootScreen label="Initializing secure terminal…" />
  }
  if (health.isError) {
    return <BootScreen label="Backend unavailable" detail="Start the Auric gateway and retry." />
  }
  if (!authRequired || token) {
    return <App />
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const result = await api.login(username, password)
      setSessionToken(result.token)
      await qc.invalidateQueries()
      window.location.reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="terminal-grid flex min-h-screen items-center justify-center bg-ink-950 px-4 text-fg-200">
      <section className="w-full max-w-md rounded-2xl border border-ink-700 bg-ink-900/95 p-6 shadow-2xl">
        <div className="mb-6 flex items-center gap-3">
          <div className="grid h-11 w-11 place-items-center rounded-xl border border-gold-600/40 bg-gold-600/10">
            <ShieldCheck className="h-5 w-5 text-gold-300" />
          </div>
          <div>
            <h1 className="text-lg font-black tracking-tight text-fg-100">Auric Production Console</h1>
            <p className="mt-1 text-[10px] uppercase tracking-[0.14em] text-fg-500">
              Operator authentication required
            </p>
          </div>
        </div>

        <form onSubmit={submit} className="space-y-3">
          <label className="block">
            <span className="mb-1 block text-[9px] font-bold uppercase tracking-[0.12em] text-fg-500">Username</span>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              className="h-10 w-full rounded-lg border border-ink-700 bg-ink-950 px-3 text-sm text-fg-100 outline-none focus:border-gold-600/70"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-[9px] font-bold uppercase tracking-[0.12em] text-fg-500">Password</span>
            <div className="flex h-10 items-center gap-2 rounded-lg border border-ink-700 bg-ink-950 px-3 focus-within:border-gold-600/70">
              <LockKeyhole className="h-4 w-4 text-fg-600" />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                className="w-full bg-transparent text-sm text-fg-100 outline-none"
              />
            </div>
          </label>

          {error ? (
            <div className="rounded-lg border border-bear-500/30 bg-bear-500/10 px-3 py-2 text-[11px] text-bear-400">
              {error}
            </div>
          ) : null}

          <button
            type="submit"
            disabled={submitting || !username || !password}
            className="mt-2 h-10 w-full rounded-lg border border-gold-600/40 bg-gold-600/15 text-[10px] font-black uppercase tracking-[0.12em] text-gold-300 hover:bg-gold-600/20 disabled:opacity-40"
          >
            {submitting ? 'Authenticating…' : 'Enter Terminal'}
          </button>
        </form>

        <p className="mt-4 text-[9px] leading-relaxed text-fg-600">
          Session credentials are kept in sessionStorage and cleared when the browser session ends.
          Live execution still requires the separate execution key.
        </p>
      </section>
    </main>
  )
}

function BootScreen({ label, detail }: { label: string; detail?: string }) {
  return (
    <main className="terminal-grid flex min-h-screen items-center justify-center bg-ink-950 text-fg-300">
      <div className="text-center">
        <div className="mx-auto mb-3 h-7 w-7 animate-spin rounded-full border-2 border-ink-700 border-t-gold-400" />
        <div className="text-sm font-semibold">{label}</div>
        {detail ? <div className="mt-1 text-[10px] text-fg-600">{detail}</div> : null}
      </div>
    </main>
  )
}
