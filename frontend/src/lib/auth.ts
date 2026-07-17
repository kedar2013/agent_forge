const ADMIN_STORAGE_KEY = 'af_admin_token'
const ADMIN_ROLE_KEY = 'af_admin_role'
const USER_STORAGE_KEY = 'af_user_token'
const USER_EMAIL_KEY = 'af_user_email'
const CHAT_SESSION_KEY = 'af_chat_session_id'

export type AdminShellRole = 'admin' | 'viewer' | 'developer'

export function getStoredToken(): string | null {
  return localStorage.getItem(ADMIN_STORAGE_KEY)
}

export function setStoredToken(token: string): void {
  localStorage.setItem(ADMIN_STORAGE_KEY, token)
}

export function clearStoredToken(): void {
  localStorage.removeItem(ADMIN_STORAGE_KEY)
  localStorage.removeItem(ADMIN_ROLE_KEY)
}

/** Role of whoever is signed into the admin shell (Layout.tsx + AdminApp
 * routes) — the static break-glass token always resolves to "admin" since
 * that's the only role it can ever carry server-side (see principal.py).
 * A per-user login (LoginPage's email/password tab) stores the role the
 * backend actually returned, so the sidebar/routes can differ for
 * admin/viewer/developer without a second round-trip. */
export function getStoredRole(): AdminShellRole {
  const role = localStorage.getItem(ADMIN_ROLE_KEY)
  return role === 'viewer' || role === 'developer' ? role : 'admin'
}

export function setStoredRole(role: AdminShellRole): void {
  localStorage.setItem(ADMIN_ROLE_KEY, role)
}

export function getUserToken(): string | null {
  return localStorage.getItem(USER_STORAGE_KEY)
}

export function setUserSession(token: string, email: string): void {
  localStorage.setItem(USER_STORAGE_KEY, token)
  localStorage.setItem(USER_EMAIL_KEY, email)
}

export function getUserEmail(): string | null {
  return localStorage.getItem(USER_EMAIL_KEY)
}

export function clearUserSession(): void {
  localStorage.removeItem(USER_STORAGE_KEY)
  localStorage.removeItem(USER_EMAIL_KEY)
  localStorage.removeItem(CHAT_SESSION_KEY)
}

/** Remembers which conversation was open, so reopening /chat resumes where
 * you left off instead of always landing on a blank new one. The list of
 * conversations itself is server-side truth (chat_api's /conversations),
 * this is just a "last viewed" hint. */
export function getLastActiveSessionId(): string | null {
  return localStorage.getItem(CHAT_SESSION_KEY)
}

export function setLastActiveSessionId(id: string): void {
  localStorage.setItem(CHAT_SESSION_KEY, id)
}
