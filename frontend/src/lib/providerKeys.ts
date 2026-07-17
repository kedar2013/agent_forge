/** BYOK provider keys — sessionStorage, not localStorage: per product
 * decision, a visitor's key must be wiped when they close the tab, never
 * survive a browser restart. Read fresh on every chat/playground request
 * (see api/chat.ts) and sent only as a request header — never written to
 * this app's backend/DB (see backend/app/agent_runtime/byok.py). */

export type Provider = 'gemini' | 'anthropic'

const STORAGE_KEY: Record<Provider, string> = {
  gemini: 'af_byok_gemini',
  anthropic: 'af_byok_anthropic',
}

export function getProviderKey(provider: Provider): string | null {
  return sessionStorage.getItem(STORAGE_KEY[provider])
}

export function setProviderKey(provider: Provider, key: string): void {
  sessionStorage.setItem(STORAGE_KEY[provider], key)
}
