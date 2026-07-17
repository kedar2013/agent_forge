import { useEffect, useState } from 'react'
import {
  Activity,
  Bot,
  Bug,
  ChevronDown,
  Database,
  DatabaseZap,
  FileClock,
  Home,
  LogOut,
  MessageSquare,
  PlusSquare,
  Receipt,
  Rocket,
  Search,
  ShieldCheck,
  Sparkles,
  UserCog,
  Wrench,
} from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'
import CommandPalette from './CommandPalette'
import HelpButton from './ui/HelpButton'
import Logo from './ui/Logo'
import StudioCredit from './ui/StudioCredit'
import ThemeToggle from './ui/ThemeToggle'
import { clearStoredToken, getStoredRole, type AdminShellRole } from '../lib/auth'

interface NavItem {
  to: string
  label: string
  icon: typeof Home
  end: boolean
  roles: AdminShellRole[]
}

const overviewItems: NavItem[] = [{ to: '/', label: 'Home', icon: Home, end: true, roles: ['admin', 'viewer', 'developer'] }]

const buildItems: NavItem[] = [
  { to: '/agents', label: 'Agents', icon: Bot, end: false, roles: ['admin', 'viewer', 'developer'] },
  { to: '/tools', label: 'Tools', icon: Wrench, end: false, roles: ['admin', 'viewer', 'developer'] },
  { to: '/access-policies', label: 'Access Policies', icon: ShieldCheck, end: false, roles: ['admin', 'viewer'] },
  { to: '/data-entities', label: 'Data Entities', icon: Database, end: false, roles: ['admin', 'viewer'] },
  { to: '/onboarding/new-domain', label: 'New Domain', icon: PlusSquare, end: false, roles: ['admin'] },
  { to: '/skills', label: 'Skills', icon: Sparkles, end: false, roles: ['admin', 'viewer', 'developer'] },
]

const chatItem: NavItem = { to: '/chat', label: 'Chat', icon: MessageSquare, end: false, roles: ['admin', 'developer'] }

const governanceItems: NavItem[] = [
  { to: '/publish-requests', label: 'Publish requests', icon: Rocket, end: false, roles: ['admin'] },
  { to: '/my-publish-requests', label: 'My publish requests', icon: Rocket, end: false, roles: ['developer'] },
  { to: '/users', label: 'Users', icon: UserCog, end: false, roles: ['admin'] },
]

const observeItems: NavItem[] = [
  { to: '/monitoring', label: 'Monitoring', icon: Activity, end: false, roles: ['admin', 'viewer'] },
  { to: '/usage', label: 'Usage', icon: Receipt, end: false, roles: ['admin', 'viewer'] },
  { to: '/audit', label: 'Audit', icon: FileClock, end: false, roles: ['admin', 'viewer'] },
  { to: '/debug', label: 'Debug Console', icon: Bug, end: false, roles: ['admin', 'viewer', 'developer'] },
  { to: '/scil', label: 'SCIL', icon: DatabaseZap, end: false, roles: ['admin'] },
]

const ROLE_LABEL: Record<AdminShellRole, string> = { admin: 'Admin', viewer: 'Viewer', developer: 'Developer' }

const navItemClass = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
    isActive
      ? 'bg-gradient-to-r from-brand-600 to-accent-600 text-white shadow-sm'
      : 'text-slate-700 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
  }`

function handleLogout() {
  clearStoredToken()
  window.location.reload()
}

function NavList({ items }: { items: NavItem[] }) {
  return (
    <nav className="space-y-0.5">
      {items.map(({ to, label, icon: Icon, end }) => (
        <NavLink key={to} to={to} className={navItemClass} end={end}>
          <Icon size={16} />
          {label}
        </NavLink>
      ))}
    </nav>
  )
}

/** Persists open/closed per group across sessions — defaults open so
 * nothing is hidden until the user chooses to collapse it. */
function useSidebarGroupOpen(key: string): [boolean, (open: boolean) => void] {
  const storageKey = `af:sidebar:${key}`
  const [open, setOpen] = useState(() => localStorage.getItem(storageKey) !== 'false')
  function set(next: boolean) {
    setOpen(next)
    localStorage.setItem(storageKey, String(next))
  }
  return [open, set]
}

function CollapsibleNavGroup({ title, items, storageKey }: { title: string; items: NavItem[]; storageKey: string }) {
  const [open, setOpen] = useSidebarGroupOpen(storageKey)
  if (items.length === 0) return null
  return (
    <details open={open} onToggle={(e) => setOpen(e.currentTarget.open)} className="group mt-4">
      <summary className="flex cursor-pointer list-none items-center justify-between px-3 py-1 text-[11px] font-semibold tracking-wide text-slate-400 uppercase [&::-webkit-details-marker]:hidden">
        {title}
        <ChevronDown size={12} className="transition-transform group-open:rotate-180" />
      </summary>
      <div className="mt-1">
        <NavList items={items} />
      </div>
    </details>
  )
}

export default function Layout() {
  const [paletteOpen, setPaletteOpen] = useState(false)
  const role = getStoredRole()
  const visibleBuildItems = buildItems.filter((item) => item.roles.includes(role))
  const visibleGovernanceItems = governanceItems.filter((item) => item.roles.includes(role))
  const visibleObserveItems = observeItems.filter((item) => item.roles.includes(role))
  const chatVisible = chatItem.roles.includes(role)

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen((open) => !open)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  return (
    <div className="flex min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <aside className="flex w-52 shrink-0 flex-col border-r border-white/60 bg-white/60 p-4 backdrop-blur-xl dark:border-white/5 dark:bg-slate-950/60">
        <div className="mb-6 flex items-center justify-between px-2">
          <Logo size="md" />
        </div>

        <button
          onClick={() => setPaletteOpen(true)}
          className="mb-4 flex items-center gap-2 rounded-md border border-slate-200 px-3 py-1.5 text-sm text-slate-400 hover:border-slate-300 hover:text-slate-500 dark:border-slate-800 dark:hover:border-slate-700"
        >
          <Search size={15} />
          <span className="flex-1 text-left">Search…</span>
          <kbd className="rounded border border-slate-200 px-1 text-[10px] dark:border-slate-700">Ctrl K</kbd>
        </button>

        <NavList items={overviewItems} />

        <div className="mt-4 mb-1 px-3 text-[11px] font-semibold tracking-wide text-slate-400 uppercase">Build</div>
        <NavList items={visibleBuildItems} />

        {chatVisible && (
          <div className="mt-0.5">
            <NavList items={[chatItem]} />
          </div>
        )}

        <CollapsibleNavGroup title="Governance" items={visibleGovernanceItems} storageKey="governance" />
        <CollapsibleNavGroup title="Observability" items={visibleObserveItems} storageKey="observability" />

        <div className="mt-auto border-t border-slate-200 pt-3 dark:border-slate-800">
          <div className="mb-2 flex items-center justify-between gap-2 px-3 text-xs text-slate-400">
            <span className="flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> {ROLE_LABEL[role]}
            </span>
            <div className="flex items-center gap-2">
              <HelpButton />
              <ThemeToggle />
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            <LogOut size={16} />
            Log out
          </button>
          <StudioCredit className="mt-3 px-3" />
        </div>
      </aside>
      <main className="min-w-0 flex-1 p-6">
        <Outlet />
      </main>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  )
}
