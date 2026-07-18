import { useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Toaster } from 'sonner'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import UserLoginPage from './pages/UserLoginPage'
import ChatPage from './pages/ChatPage'
import HomePage from './pages/HomePage'
import ToolsPage from './pages/ToolsPage'
import AccessPoliciesPage from './pages/AccessPoliciesPage'
import DataEntitiesPage from './pages/DataEntitiesPage'
import NewDomainWizard from './pages/onboarding/NewDomainWizard'
import SkillsPage from './pages/SkillsPage'
import AgentsPage from './pages/AgentsPage'
import AgentBuilderPage from './pages/AgentBuilderPage'
import PlaygroundPage from './pages/PlaygroundPage'
import MonitoringPage from './pages/MonitoringPage'
import UsagePage from './pages/UsagePage'
import AuditPage from './pages/AuditPage'
import UsersPage from './pages/UsersPage'
import PublishRequestsPage from './pages/PublishRequestsPage'
import DebugConsolePage from './pages/DebugConsolePage'
import ScilDashboardPage from './pages/ScilDashboardPage'
import ReliabilityDashboardPage from './pages/ReliabilityDashboardPage'
import PromptEvaluatorPage from './pages/PromptEvaluatorPage'
import { getStoredRole, getStoredToken, type AdminShellRole } from './lib/auth'

const queryClient = new QueryClient()

function AuthGate({ children }: { children: React.ReactNode }) {
  const [authed, setAuthed] = useState(() => !!getStoredToken())
  if (!authed) return <LoginPage onSuccess={() => setAuthed(true)} />
  return <>{children}</>
}

/** Client-side route guard — a bounce-to-home for a role that has no
 * business being on this page. The real enforcement is server-side
 * (require_role(...) on every endpoint); this just avoids rendering a page
 * that would immediately fail every request it makes. */
function RequireRole({ roles, children }: { roles: AdminShellRole[]; children: React.ReactNode }) {
  const role = getStoredRole()
  if (!roles.includes(role)) return <Navigate to="/" replace />
  return <>{children}</>
}

function AdminApp() {
  return (
    <AuthGate>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/tools" element={<ToolsPage />} />
          <Route path="/access-policies" element={<AccessPoliciesPage />} />
          <Route path="/data-entities" element={<DataEntitiesPage />} />
          <Route
            path="/onboarding/new-domain"
            element={
              <RequireRole roles={['admin']}>
                <NewDomainWizard />
              </RequireRole>
            }
          />
          <Route path="/skills" element={<SkillsPage />} />
          <Route path="/agents" element={<AgentsPage />} />
          <Route path="/agents/new" element={<AgentBuilderPage />} />
          <Route path="/agents/:id" element={<AgentBuilderPage />} />
          <Route path="/agents/:id/playground" element={<PlaygroundPage />} />
          <Route
            path="/prompt-evaluator"
            element={
              <RequireRole roles={['admin', 'developer']}>
                <PromptEvaluatorPage />
              </RequireRole>
            }
          />
          <Route
            path="/monitoring"
            element={
              <RequireRole roles={['admin', 'viewer']}>
                <MonitoringPage />
              </RequireRole>
            }
          />
          <Route
            path="/usage"
            element={
              <RequireRole roles={['admin', 'viewer', 'developer']}>
                <UsagePage />
              </RequireRole>
            }
          />
          <Route
            path="/audit"
            element={
              <RequireRole roles={['admin', 'viewer']}>
                <AuditPage />
              </RequireRole>
            }
          />
          <Route path="/debug" element={<DebugConsolePage />} />
          <Route
            path="/scil"
            element={
              <RequireRole roles={['admin', 'developer']}>
                <ScilDashboardPage />
              </RequireRole>
            }
          />
          <Route
            path="/reliability"
            element={
              <RequireRole roles={['admin']}>
                <ReliabilityDashboardPage />
              </RequireRole>
            }
          />
          <Route
            path="/users"
            element={
              <RequireRole roles={['admin']}>
                <UsersPage />
              </RequireRole>
            }
          />
          <Route
            path="/publish-requests"
            element={
              <RequireRole roles={['admin']}>
                <PublishRequestsPage />
              </RequireRole>
            }
          />
          <Route
            path="/my-publish-requests"
            element={
              <RequireRole roles={['developer']}>
                <PublishRequestsPage mine />
              </RequireRole>
            }
          />
        </Route>
      </Routes>
    </AuthGate>
  )
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Toaster richColors position="top-right" />
      <BrowserRouter>
        <Routes>
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/user-login" element={<UserLoginPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/*" element={<AdminApp />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
