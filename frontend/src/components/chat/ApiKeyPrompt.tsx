import { useState } from 'react'
import { KeyRound } from 'lucide-react'
import { setProviderKey, type Provider } from '../../lib/providerKeys'
import Button from '../ui/Button'
import Input from '../ui/Input'
import Modal from '../ui/Modal'

const PROVIDER_LABEL: Record<Provider, string> = {
  gemini: 'Gemini (Google)',
  anthropic: 'Claude (Anthropic)',
}

/** Opens after a MissingApiKeyError (see api/chat.ts) — the bot the visitor
 * picked needs a key for `provider` that isn't in sessionStorage yet.
 * Submitting stores the key (see lib/providerKeys.ts — sessionStorage only,
 * never sent anywhere but as a per-request header) and re-sends the same
 * message so the visitor doesn't have to retype it. */
export default function ApiKeyPrompt({
  provider,
  onSubmit,
  onClose,
}: {
  provider: Provider
  onSubmit: () => void
  onClose: () => void
}) {
  const [key, setKey] = useState('')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = key.trim()
    if (!trimmed) return
    setProviderKey(provider, trimmed)
    onSubmit()
  }

  return (
    <Modal open onClose={onClose} title="API key required" maxWidth="max-w-sm">
      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="flex items-start gap-2 text-sm text-slate-600 dark:text-slate-300">
          <KeyRound size={16} className="mt-0.5 shrink-0 text-brand-600 dark:text-brand-400" />
          <p>
            This bot uses <strong>{PROVIDER_LABEL[provider]}</strong>. Add your own {PROVIDER_LABEL[provider]} API
            key to continue — it stays in this browser tab only and is never saved on our servers.
          </p>
        </div>
        <Input
          label={`${PROVIDER_LABEL[provider]} API key`}
          hideLabel={false}
          type="password"
          autoFocus
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder={provider === 'anthropic' ? 'sk-ant-...' : 'AIza...'}
        />
        <Button type="submit" className="w-full" disabled={!key.trim()}>
          Continue
        </Button>
      </form>
    </Modal>
  )
}
